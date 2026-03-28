import io
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import BackgroundTasks, HTTPException

from config import get_settings
from domain.classes import CLASS_COLORS, CLASS_IDS, VALID_CLASSES
from repositories import prediction_repository

settings = get_settings()
logger = logging.getLogger(__name__)


def submit_feedback(
    *,
    prediction_id: str,
    user_id: str,
    correct_class: str,
    was_correct: bool,
    bbox_payload: Optional[dict],
    background_tasks: BackgroundTasks,
) -> dict:
    try:
        pred = prediction_repository.get_prediction_for_user(
            prediction_id,
            user_id,
            "id,user_id,image_path,predicted_class,confidence,all_detections,image_width,image_height,pending_path",
        )
        if not pred:
            raise HTTPException(404, "Prediction not found.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(404, "Prediction not found.")

    image_path = pred.get("image_path")
    predicted_class = pred.get("predicted_class")
    predicted_confidence = pred.get("confidence")
    all_detections = pred.get("all_detections") or []
    img_w = pred.get("image_width")
    img_h = pred.get("image_height")
    pending_path = pred.get("pending_path")

    try:
        existing = prediction_repository.get_existing_correction(prediction_id, user_id)
        if existing:
            raise HTTPException(409, "Feedback already submitted for this prediction.")
    except HTTPException:
        raise
    except Exception:
        pass

    raw_bbox = bbox_payload or (all_detections[0].get("bbox") if all_detections else None)
    normalized_bbox = _normalize_bbox(raw_bbox, img_w, img_h)

    if was_correct:
        final_class = predicted_class or correct_class
        final_confidence = predicted_confidence
        final_detections = all_detections
    else:
        final_class = correct_class
        if final_class in VALID_CLASSES and normalized_bbox:
            final_confidence = 1.0
            final_detections = [_build_detection(final_class, normalized_bbox, 1.0)]
        else:
            final_confidence = None
            final_detections = []

    try:
        prediction_repository.insert_correction({
            "prediction_id": prediction_id,
            "user_id": user_id,
            "correct_class": correct_class,
            "was_correct": was_correct,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        # OWASP A05: never forward raw DB exception strings to the client.
        logger.error("Correction insert failed for prediction %s: %s", prediction_id, exc)
        raise HTTPException(500, "Failed to save feedback. Please try again.")

    points_awarded = 1 if was_correct else 2
    try:
        prediction_repository.insert_points({
            "user_id": user_id,
            "amount": points_awarded,
            "action": "correction",
            "reference_id": prediction_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        pass

    if image_path:
        background_tasks.add_task(
            _sync_feedback_artifacts,
            image_path,
            pending_path,
            normalized_bbox,
            final_class,
            img_w,
            img_h,
            prediction_id,
            final_confidence,
            final_detections,
        )

    return {"message": "Feedback saved.", "points_awarded": points_awarded}


def _normalize_bbox(raw_bbox: Optional[dict], img_w: Optional[int], img_h: Optional[int]) -> Optional[dict]:
    if not raw_bbox or not img_w or not img_h:
        return None

    x1 = max(0, min(int(round(raw_bbox["x1"])), img_w))
    y1 = max(0, min(int(round(raw_bbox["y1"])), img_h))
    x2 = max(0, min(int(round(raw_bbox["x2"])), img_w))
    y2 = max(0, min(int(round(raw_bbox["y2"])), img_h))

    x1, x2 = sorted((x1, x2))
    y1, y2 = sorted((y1, y2))

    if x2 - x1 < 2 or y2 - y1 < 2:
        return None

    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


def _build_detection(correct_class: str, bbox: dict, confidence: float) -> dict:
    return {
        "class": correct_class,
        "class_id": CLASS_IDS[correct_class],
        "confidence": confidence,
        "bbox": bbox,
        "color": CLASS_COLORS[correct_class],
    }


def _sync_feedback_artifacts(
    image_path: str,
    pending_path: Optional[str],
    bbox: Optional[dict],
    final_class: str,
    img_w: int,
    img_h: int,
    prediction_id: str,
    final_confidence: Optional[float],
    final_detections: list,
):
    hf_required = final_class in VALID_CLASSES and bbox is not None
    hf_uploaded = False

    try:
        if hf_required:
            # Guard: pending_path can be None if Supabase storage upload failed earlier.
            # Attempting download_pending_image(None) would crash; skip HF upload instead.
            if not pending_path:
                logger.warning(
                    "HF upload skipped for %s — pending_path is None (storage upload failed)",
                    prediction_id,
                )
            else:
                img_bytes = prediction_repository.download_pending_image(pending_path)

                prediction_repository.upload_training_image(
                    image_path,
                    io.BytesIO(img_bytes),
                    settings.hf_dataset_repo,
                )

                cx = ((bbox["x1"] + bbox["x2"]) / 2) / img_w
                cy = ((bbox["y1"] + bbox["y2"]) / 2) / img_h
                bw = (bbox["x2"] - bbox["x1"]) / img_w
                bh = (bbox["y2"] - bbox["y1"]) / img_h
                yolo_line = f"{CLASS_IDS[final_class]} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n"
                label_path = image_path.replace("images/", "labels/").replace(".jpg", ".txt")

                prediction_repository.upload_training_image(
                    label_path,
                    yolo_line.encode(),
                    settings.hf_dataset_repo,
                )

                hf_uploaded = True

        update_payload = {
            "predicted_class": final_class,
            "confidence": final_confidence,
            "all_detections": final_detections,
        }

        if not hf_required or hf_uploaded:
            update_payload["pending_path"] = None

        prediction_repository.update_prediction(prediction_id, update_payload)

        if pending_path and (not hf_required or hf_uploaded):
            try:
                prediction_repository.remove_storage_paths([pending_path])
            except Exception as e:
                logger.warning(f"Pending image cleanup failed: {e}")

    except Exception as e:
        logger.warning(f"HF/background sync failed for prediction {prediction_id}: {e}")
