import io
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from PIL import Image
from slowapi import Limiter
from slowapi.util import get_remote_address
from supabase import create_client
from huggingface_hub import HfApi

from auth import get_current_user
from config import get_settings
from inference import get_model
from security import validate_image, hash_ip, sanitize_filename, strip_exif

settings = get_settings()
router = APIRouter(tags=["predict"])
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)

supabase_svc = create_client(settings.supabase_url, settings.supabase_service_key)
hf_api = HfApi(token=settings.hf_token)

MODEL_VERSION = "v5"
MAX_BYTES = settings.max_image_size_mb * 1024 * 1024


@router.post("/predict")
@limiter.limit("10/minute")
async def predict(
    request: Request,
    file: UploadFile = File(...),
    conf: float = Form(default=0.45, ge=0.1, le=0.9),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]

    # ── 1. Read file ──────────────────────────────────────────────────────────
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"File too large. Max {settings.max_image_size_mb}MB.")

    # ── 2. Security validation ────────────────────────────────────────────────
    ok, reason = validate_image(data, file.filename or "upload")
    if not ok:
        raise HTTPException(422, reason)

    # ── 3. Open with PIL (second open after verify) ───────────────────────────
    try:
        pil_img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(422, "Cannot open image.")

    orig_w, orig_h = pil_img.size

    # ── 4. Strip EXIF ─────────────────────────────────────────────────────────
    pil_img = strip_exif(pil_img)

    # ── 5. Run inference ──────────────────────────────────────────────────────
    model = get_model()
    detections, inference_ms = model.predict(pil_img, conf=conf, iou=settings.iou_threshold)

    prediction_id = str(uuid.uuid4())
    detections_payload = [
        {
            "class":      d.class_name,
            "class_id":   d.class_id,
            "confidence": round(d.confidence, 4),
            "bbox":       {"x1": d.x1, "y1": d.y1, "x2": d.x2, "y2": d.y2},
            "color":      d.color,
        }
        for d in detections
    ]

    if detections:
        # ── 6. Save image to HuggingFace Dataset ──────────────────────────────
        safe_name = sanitize_filename("jpg")
        image_path = f"images/{safe_name}"
        try:
            buf = io.BytesIO()
            pil_img.save(buf, format="JPEG", quality=85)
            buf.seek(0)
            hf_api.upload_file(
                path_or_fileobj=buf,
                path_in_repo=image_path,
                repo_id=settings.hf_dataset_repo,
                repo_type="dataset",
            )
        except Exception as e:
            logger.warning(f"HF upload failed: {e}")
            image_path = None

        # ── 7. Save prediction to Supabase ────────────────────────────────────
        primary = detections[0]
        try:
            supabase_svc.table("predictions").insert({
                "id":               prediction_id,
                "user_id":          user_id,
                "image_path":       image_path,
                "predicted_class":  primary.class_name,
                "confidence":       round(primary.confidence, 4),
                "all_detections":   detections_payload,
                "model_version":    MODEL_VERSION,
                "created_at":       datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            logger.error(f"Supabase insert failed: {e}")

        # ── 8. Award points (+1 per detection) ───────────────────────────────
        try:
            for det in detections:
                supabase_svc.table("points").insert({
                    "user_id":      user_id,
                    "amount":       1,
                    "action":       "prediction",
                    "reference_id": prediction_id,
                    "created_at":   datetime.now(timezone.utc).isoformat(),
                }).execute()
        except Exception as e:
            logger.warning(f"Points insert failed: {e}")

        # ── 9. Log rate limit entry with hashed IP ────────────────────────────
        try:
            client_ip = request.client.host if request.client else "unknown"
            supabase_svc.table("rate_limit_log").insert({
                "user_id":  user_id,
                "endpoint": "/predict",
                "ip_hash":  hash_ip(client_ip),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            logger.warning(f"Rate log failed: {e}")

    # ── 10. Build response ────────────────────────────────────────────────────
    primary_class = detections[0].class_name if detections else None
    primary_conf  = round(detections[0].confidence, 4) if detections else None

    return {
        "prediction_id":      prediction_id,
        "detections":         detections_payload,
        "primary_class":      primary_class,
        "primary_confidence": primary_conf,
        "image_width":        orig_w,
        "image_height":       orig_h,
        "model_version":      MODEL_VERSION,
        "inference_ms":       inference_ms,
    }
