import gc
import io
import logging
import uuid
from datetime import datetime, timezone

from fastapi import BackgroundTasks, HTTPException, UploadFile
from PIL import Image

from config import get_settings
from inference import get_model
from repositories import prediction_repository
from security import hash_ip, sanitize_filename, strip_exif, validate_image

settings = get_settings()
logger = logging.getLogger(__name__)

MODEL_VERSION = "v5"
MAX_BYTES = settings.max_image_size_mb * 1024 * 1024
MAX_INFER_DIM = 1280


def predict_image(*, user_id: str, upload_file: UploadFile, conf: float, client_ip: str) -> dict:
    data = _read_and_validate_upload(upload_file)
    pil_img, orig_w, orig_h = _open_image(data)

    infer_w, infer_h = orig_w, orig_h
    if max(orig_w, orig_h) > MAX_INFER_DIM:
        pil_img.thumbnail((MAX_INFER_DIM, MAX_INFER_DIM), Image.BILINEAR)
        infer_w, infer_h = pil_img.size

    pil_img = strip_exif(pil_img)

    model = get_model()
    detections, inference_ms = model.predict(pil_img, conf=conf, iou=settings.iou_threshold)

    prediction_id = str(uuid.uuid4())
    detections_payload = [
        {
            "class": d.class_name,
            "class_id": d.class_id,
            "confidence": round(d.confidence, 4),
            "bbox": {"x1": d.x1, "y1": d.y1, "x2": d.x2, "y2": d.y2},
            "color": d.color,
        }
        for d in detections
    ]
    detections_payload = _rescale_detections_to_original(
        detections_payload,
        infer_w=infer_w,
        infer_h=infer_h,
        orig_w=orig_w,
        orig_h=orig_h,
    )

    primary_class = detections[0].class_name if detections else None
    primary_conf = round(detections[0].confidence, 4) if detections else None

    _store_pending_image(user_id, pil_img, prediction_id, detections, detections_payload, orig_w, orig_h)

    if detections:
        _insert_prediction_points(user_id, prediction_id)
        _log_prediction_ip(user_id, client_ip)

    return {
        "prediction_id": prediction_id,
        "detections": detections_payload,
        "primary_class": primary_class,
        "primary_confidence": primary_conf,
        "image_width": orig_w,
        "image_height": orig_h,
        "model_version": MODEL_VERSION,
        "inference_ms": inference_ms,
    }


def _rescale_detections_to_original(
    detections_payload: list,
    *,
    infer_w: int,
    infer_h: int,
    orig_w: int,
    orig_h: int,
) -> list:
    if not detections_payload or (infer_w == orig_w and infer_h == orig_h):
        return detections_payload

    scale_x = orig_w / infer_w
    scale_y = orig_h / infer_h
    scaled_payload = []

    for detection in detections_payload:
        bbox = detection["bbox"]
        scaled_bbox = {
            "x1": max(0, min(int(round(bbox["x1"] * scale_x)), orig_w)),
            "y1": max(0, min(int(round(bbox["y1"] * scale_y)), orig_h)),
            "x2": max(0, min(int(round(bbox["x2"] * scale_x)), orig_w)),
            "y2": max(0, min(int(round(bbox["y2"] * scale_y)), orig_h)),
        }
        scaled_payload.append({
            **detection,
            "bbox": scaled_bbox,
        })

    return scaled_payload


def cancel_prediction(*, prediction_id: str, user_id: str, background_tasks: BackgroundTasks) -> dict:
    try:
        pred = prediction_repository.get_prediction_for_user(
            prediction_id,
            user_id,
            "id,user_id,pending_path",
        )
        if not pred:
            return {"message": "Not found — nothing to cancel."}

        pending_path = pred.get("pending_path")
        if pending_path:
            prediction_repository.clear_prediction_pending_path(prediction_id)
            background_tasks.add_task(_delete_pending, pending_path)
    except Exception as e:
        logger.warning(f"Cancel prediction failed: {e}")

    return {"message": "Cancellation scheduled."}


def _read_and_validate_upload(upload_file: UploadFile) -> bytes:
    data = upload_file.file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"File too large. Max {settings.max_image_size_mb}MB.")

    ok, reason = validate_image(data, upload_file.filename or "upload")
    if not ok:
        raise HTTPException(422, reason)
    return data


def _open_image(data: bytes):
    try:
        pil_img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(422, "Cannot open image.")

    orig_w, orig_h = pil_img.size
    return pil_img, orig_w, orig_h


def _store_pending_image(user_id: str, pil_img: Image.Image, prediction_id: str, detections: list, detections_payload: list, orig_w: int, orig_h: int):
    if detections:
        _cleanup_stale_pending_images(user_id)

    safe_name = sanitize_filename("jpg")
    image_path = f"images/{safe_name}"
    pending_path = f"pending/{safe_name}"

    buf = io.BytesIO()
    pil_img.save(buf, format="JPEG", quality=75)
    buf.seek(0)
    del pil_img
    gc.collect()

    try:
        prediction_repository.upload_pending_image(pending_path, buf.read(), "image/jpeg")
    except Exception as e:
        logger.warning(f"Supabase storage upload failed: {e}")
        pending_path = None
    finally:
        buf.close()
        del buf
        gc.collect()

    payload = {
        "id": prediction_id,
        "user_id": user_id,
        "image_path": image_path,
        "pending_path": pending_path,
        "all_detections": detections_payload if detections else [],
        "image_width": orig_w,
        "image_height": orig_h,
        "model_version": MODEL_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if detections:
        primary = detections[0]
        payload.update({
            "predicted_class": primary.class_name,
            "confidence": round(primary.confidence, 4),
        })

    try:
        prediction_repository.insert_prediction(payload)
    except Exception as e:
        if detections:
            logger.error(f"Supabase insert failed: {e}")
        else:
            logger.warning(f"No-detection record insert failed: {e}")

    return image_path, pending_path


def _cleanup_stale_pending_images(user_id: str):
    try:
        stale_paths = prediction_repository.get_user_pending_paths(user_id)
        if stale_paths:
            prediction_repository.remove_storage_paths(stale_paths)
            prediction_repository.clear_user_pending_paths(user_id)
            logger.info(f"Cleaned {len(stale_paths)} stale pending image(s)")
    except Exception as e:
        logger.warning(f"Stale cleanup failed: {e}")


def _insert_prediction_points(user_id: str, prediction_id: str):
    try:
        prediction_repository.insert_points({
            "user_id": user_id,
            "amount": 1,
            "action": "prediction",
            "reference_id": prediction_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        logger.warning(f"Points insert failed: {e}")


def _log_prediction_ip(user_id: str, client_ip: str):
    try:
        prediction_repository.insert_rate_limit_log({
            "user_id": user_id,
            "endpoint": "/predict",
            "ip_hash": hash_ip(client_ip or "unknown"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass


def _delete_pending(pending_path: str):
    try:
        prediction_repository.remove_storage_paths([pending_path])
        logger.info("Cancelled pending image deleted from storage")
    except Exception as e:
        logger.warning(f"Cancel cleanup failed: {e}")
