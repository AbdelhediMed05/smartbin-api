import gc
import io
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from PIL import Image
from slowapi import Limiter
from slowapi.util import get_remote_address

from auth import get_current_user
from config import get_settings
from db import supabase_svc
from inference import get_model
from security import validate_image, hash_ip, sanitize_filename, strip_exif

settings = get_settings()
router   = APIRouter(tags=["predict"])
limiter  = Limiter(key_func=get_remote_address)
logger   = logging.getLogger(__name__)

MODEL_VERSION  = "v5"
MAX_BYTES      = settings.max_image_size_mb * 1024 * 1024
MAX_INFER_DIM  = 1280  # downscale large images before inference to save RAM


def _delete_pending(pending_path: str):
    """Background task — delete a pending image from Supabase Storage."""
    try:
        supabase_svc.storage.from_("smartbin-images").remove([pending_path])
        logger.info("Cancelled pending image deleted from storage")
    except Exception as e:
        logger.warning(f"Cancel cleanup failed: {e}")


@router.post("/predict")
@limiter.limit("10/minute")
async def predict(
    request: Request,
    file: UploadFile = File(...),
    conf: float = Form(default=0.45, ge=0.1, le=0.9),
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]

    # ── 1. Read & size-check ──────────────────────────────────────────────────
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"File too large. Max {settings.max_image_size_mb}MB.")

    # ── 2. Security validation ────────────────────────────────────────────────
    ok, reason = validate_image(data, file.filename or "upload")
    if not ok:
        del data
        raise HTTPException(422, reason)

    # ── 3. Open with PIL ──────────────────────────────────────────────────────
    try:
        pil_img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        del data
        raise HTTPException(422, "Cannot open image.")

    orig_w, orig_h = pil_img.size
    del data
    gc.collect()

    # ── 4. Downscale very large images before inference ───────────────────────
    # Phone cameras produce 8–12MP images. Model runs at 480px — no benefit
    # sending a 4000px image to letterbox. Downscaling saves significant RAM.
    if max(orig_w, orig_h) > MAX_INFER_DIM:
        pil_img.thumbnail((MAX_INFER_DIM, MAX_INFER_DIM), Image.BILINEAR)

    # ── 5. Strip EXIF ─────────────────────────────────────────────────────────
    pil_img = strip_exif(pil_img)

    # ── 6. Run inference ──────────────────────────────────────────────────────
    model = get_model()
    detections, inference_ms = model.predict(pil_img, conf=conf, iou=settings.iou_threshold)

    prediction_id      = str(uuid.uuid4())
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

    primary_class = detections[0].class_name if detections else None
    primary_conf  = round(detections[0].confidence, 4) if detections else None

    if detections:
        # ── 7. Cleanup stale pending images from this user ────────────────────
        try:
            stale = supabase_svc.table("predictions") \
                .select("pending_path") \
                .eq("user_id", user_id) \
                .not_.is_("pending_path", "null") \
                .execute()
            stale_paths = [r["pending_path"] for r in stale.data if r.get("pending_path")]
            if stale_paths:
                supabase_svc.storage.from_("smartbin-images").remove(stale_paths)
                supabase_svc.table("predictions") \
                    .update({"pending_path": None}) \
                    .eq("user_id", user_id) \
                    .not_.is_("pending_path", "null") \
                    .execute()
                logger.info(f"Cleaned {len(stale_paths)} stale pending image(s)")
        except Exception as e:
            logger.warning(f"Stale cleanup failed: {e}")

        # ── 8. Save to Supabase Storage (pending feedback) ────────────────────
        safe_name    = sanitize_filename("jpg")
        image_path   = f"images/{safe_name}"
        pending_path = f"pending/{safe_name}"

        # Stream directly from BytesIO — avoid .getvalue() double-buffer
        buf = io.BytesIO()
        pil_img.save(buf, format="JPEG", quality=75)  # 75 = good compression, ~30% smaller
        buf.seek(0)
        del pil_img  # free PIL image immediately after saving
        gc.collect()

        try:
            supabase_svc.storage.from_("smartbin-images").upload(
                path=pending_path,
                file=buf.read(),
                file_options={"content-type": "image/jpeg"},
            )
        except Exception as e:
            logger.warning(f"Supabase storage upload failed: {e}")
            pending_path = None
        finally:
            buf.close()
            del buf
            gc.collect()

        # ── 9. Save prediction record ─────────────────────────────────────────
        primary = detections[0]
        try:
            supabase_svc.table("predictions").insert({
                "id":               prediction_id,
                "user_id":          user_id,
                "image_path":       image_path,
                "pending_path":     pending_path,
                "predicted_class":  primary.class_name,
                "confidence":       round(primary.confidence, 4),
                "all_detections":   detections_payload,
                "image_width":      orig_w,
                "image_height":     orig_h,
                "model_version":    MODEL_VERSION,
                "created_at":       datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            logger.error(f"Supabase insert failed: {e}")

        # ── 10. Award 1 point per prediction ─────────────────────────────────
        try:
            supabase_svc.table("points").insert({
                "user_id":      user_id,
                "amount":       1,
                "action":       "prediction",
                "reference_id": prediction_id,
                "created_at":   datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            logger.warning(f"Points insert failed: {e}")

        # ── 11. Log hashed IP ─────────────────────────────────────────────────
        try:
            client_ip = request.client.host if request.client else "unknown"
            supabase_svc.table("rate_limit_log").insert({
                "user_id":    user_id,
                "endpoint":   "/predict",
                "ip_hash":    hash_ip(client_ip),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception:
            pass

    else:
        # No detections — still save record so user can correct with a drawn box
        del pil_img
        gc.collect()
        try:
            supabase_svc.table("predictions").insert({
                "id":               prediction_id,
                "user_id":          user_id,
                "image_path":       None,
                "pending_path":     None,
                "predicted_class":  None,
                "confidence":       None,
                "all_detections":   [],
                "image_width":      orig_w,
                "image_height":     orig_h,
                "model_version":    MODEL_VERSION,
                "created_at":       datetime.now(timezone.utc).isoformat(),
            }).execute()
        except Exception as e:
            logger.warning(f"No-detection record insert failed: {e}")

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


@router.delete("/predict/{prediction_id}/cancel")
async def cancel_prediction(
    request: Request,
    prediction_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """
    Called by the frontend when the user resets or uploads a new image
    before submitting feedback. Cleans up the pending image from Supabase
    Storage as a background task — response is immediate.
    """
    user_id = current_user["user_id"]

    try:
        pred_res = supabase_svc.table("predictions").select(
            "id,user_id,pending_path"
        ).eq("id", prediction_id).eq("user_id", user_id).single().execute()

        if not pred_res.data:
            return {"message": "Not found — nothing to cancel."}

        pending_path = pred_res.data.get("pending_path")

        if pending_path:
            # Clear pending_path in DB immediately
            supabase_svc.table("predictions").update(
                {"pending_path": None}
            ).eq("id", prediction_id).execute()

            # Delete from Storage as background task — don't block response
            background_tasks.add_task(_delete_pending, pending_path)

    except Exception as e:
        logger.warning(f"Cancel prediction failed: {e}")

    return {"message": "Cancellation scheduled."}
