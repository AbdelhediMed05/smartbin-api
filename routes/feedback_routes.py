import io
import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address

from auth import get_current_user
from config import get_settings
from db import supabase_svc, hf_api  # shared clients — no new instances

settings = get_settings()
router = APIRouter(tags=["feedback"])
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)

VALID_CLASSES = {"Plastic", "Glass", "Metal", "Paper"}
CLASS_IDS = {"Plastic": 0, "Glass": 1, "Metal": 2, "Paper": 3}
CLASS_COLORS = {
    "Plastic": "#1E90FF",
    "Glass": "#00CED1",
    "Metal": "#FF8C00",
    "Paper": "#22c55e",
}


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


def _upload_to_hf(
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
    """
    Background task.
    If final_class is one of the 4 supported classes and bbox is valid,
    upload image + YOLO label to HF.
    Always update the prediction row with the confirmed result.
    Only clear pending_path after HF upload succeeds, or immediately when
    no HF upload is required.
    """
    hf_required = final_class in VALID_CLASSES and bbox is not None
    hf_uploaded = False

    try:
        if hf_required:
            img_bytes = supabase_svc.storage.from_("smartbin-images").download(pending_path)

            hf_api.upload_file(
                path_or_fileobj=io.BytesIO(img_bytes),
                path_in_repo=image_path,
                repo_id=settings.hf_dataset_repo,
                repo_type="dataset",
            )

            cx = ((bbox["x1"] + bbox["x2"]) / 2) / img_w
            cy = ((bbox["y1"] + bbox["y2"]) / 2) / img_h
            bw = (bbox["x2"] - bbox["x1"]) / img_w
            bh = (bbox["y2"] - bbox["y1"]) / img_h
            yolo_line = f"{CLASS_IDS[final_class]} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n"
            label_path = image_path.replace("images/", "labels/").replace(".jpg", ".txt")

            hf_api.upload_file(
                path_or_fileobj=yolo_line.encode(),
                path_in_repo=label_path,
                repo_id=settings.hf_dataset_repo,
                repo_type="dataset",
            )

            hf_uploaded = True

        update_payload = {
            "predicted_class": final_class,
            "confidence": final_confidence,
            "all_detections": final_detections,
        }

        if not hf_required or hf_uploaded:
            update_payload["pending_path"] = None

        supabase_svc.table("predictions").update(update_payload).eq("id", prediction_id).execute()

        if pending_path and (not hf_required or hf_uploaded):
            try:
                supabase_svc.storage.from_("smartbin-images").remove([pending_path])
            except Exception as e:
                logger.warning(f"Pending image cleanup failed: {e}")

    except Exception as e:
        logger.warning(f"HF/background sync failed for prediction {prediction_id}: {e}")


class BBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class FeedbackRequest(BaseModel):
    correct_class: Literal["Plastic", "Glass", "Metal", "Paper", "Unknown"] = "Unknown"
    was_correct: bool
    bbox: Optional[BBox] = None


@router.post("/feedback/{prediction_id}")
@limiter.limit("20/minute")
async def submit_feedback(
    request: Request,
    prediction_id: str,
    body: FeedbackRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]

    try:
        pred_res = supabase_svc.table("predictions").select(
            "id,user_id,image_path,predicted_class,confidence,all_detections,image_width,image_height,pending_path"
        ).eq("id", prediction_id).eq("user_id", user_id).single().execute()
        if not pred_res.data:
            raise HTTPException(404, "Prediction not found.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(404, "Prediction not found.")

    image_path = pred_res.data.get("image_path")
    predicted_class = pred_res.data.get("predicted_class")
    predicted_confidence = pred_res.data.get("confidence")
    all_detections = pred_res.data.get("all_detections") or []
    img_w = pred_res.data.get("image_width")
    img_h = pred_res.data.get("image_height")
    pending_path = pred_res.data.get("pending_path")

    try:
        existing = supabase_svc.table("corrections").select("id").eq(
            "prediction_id", prediction_id
        ).eq("user_id", user_id).execute()
        if existing.data:
            raise HTTPException(409, "Feedback already submitted for this prediction.")
    except HTTPException:
        raise
    except Exception:
        pass

    raw_bbox = None
    if body.bbox:
        raw_bbox = {
            "x1": body.bbox.x1,
            "y1": body.bbox.y1,
            "x2": body.bbox.x2,
            "y2": body.bbox.y2,
        }
    elif all_detections:
        raw_bbox = all_detections[0].get("bbox")

    normalized_bbox = _normalize_bbox(raw_bbox, img_w, img_h)

    if body.was_correct:
        final_class = predicted_class or body.correct_class
        final_confidence = predicted_confidence
        final_detections = all_detections
    else:
        final_class = body.correct_class
        if final_class in VALID_CLASSES and normalized_bbox:
            final_confidence = 1.0
            final_detections = [_build_detection(final_class, normalized_bbox, 1.0)]
        else:
            final_confidence = None
            final_detections = []

    try:
        supabase_svc.table("corrections").insert({
            "prediction_id": prediction_id,
            "user_id": user_id,
            "correct_class": body.correct_class,
            "was_correct": body.was_correct,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        raise HTTPException(500, f"Failed to save feedback: {e}")

    points_awarded = 1 if body.was_correct else 2
    try:
        supabase_svc.table("points").insert({
            "user_id": user_id,
            "amount": points_awarded,
            "action": "correction",
            "reference_id": prediction_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        pass

    if image_path:
        background_tasks.add_task(
            _upload_to_hf,
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
