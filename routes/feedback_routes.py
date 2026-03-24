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
router   = APIRouter(tags=["feedback"])
limiter  = Limiter(key_func=get_remote_address)
logger   = logging.getLogger(__name__)


def _upload_to_hf(
    image_path: str,
    pending_path: str,
    bbox: dict,
    correct_class: str,
    img_w: int,
    img_h: int,
):
    """
    Background task — runs after response is sent to user.
    Downloads image from Supabase Storage, uploads to HuggingFace,
    deletes from Storage, writes YOLO label file.
    """
    try:
        img_bytes = supabase_svc.storage.from_("smartbin-images").download(pending_path)

        hf_api.upload_file(
            path_or_fileobj=io.BytesIO(img_bytes),
            path_in_repo=image_path,
            repo_id=settings.hf_dataset_repo,
            repo_type="dataset",
        )

        try:
            supabase_svc.storage.from_("smartbin-images").remove([pending_path])
        except Exception:
            pass  # Non-critical — nightly cron handles orphans

        if bbox and img_w and img_h:
            CLASS_IDS = {"Plastic": 0, "Glass": 1, "Metal": 2, "Paper": 3}
            class_id  = CLASS_IDS.get(correct_class, 0)
            cx = ((bbox["x1"] + bbox["x2"]) / 2) / img_w
            cy = ((bbox["y1"] + bbox["y2"]) / 2) / img_h
            bw = (bbox["x2"] - bbox["x1"]) / img_w
            bh = (bbox["y2"] - bbox["y1"]) / img_h
            yolo_line  = f"{class_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n"
            label_path = image_path.replace("images/", "labels/").replace(".jpg", ".txt")
            hf_api.upload_file(
                path_or_fileobj=yolo_line.encode(),
                path_in_repo=label_path,
                repo_id=settings.hf_dataset_repo,
                repo_type="dataset",
            )
    except Exception as e:
        logger.warning(f"HF background upload failed: {e}")


class BBox(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int


class FeedbackRequest(BaseModel):
    # correct_class is Optional — when was_correct=True and no detection,
    # it may not be meaningful. Defaults to "Unknown" if omitted.
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
            "id,user_id,image_path,predicted_class,all_detections,image_width,image_height,pending_path"
        ).eq("id", prediction_id).eq("user_id", user_id).single().execute()
        if not pred_res.data:
            raise HTTPException(404, "Prediction not found.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(404, "Prediction not found.")

    image_path      = pred_res.data.get("image_path")
    predicted_class = pred_res.data.get("predicted_class")
    all_detections  = pred_res.data.get("all_detections") or []
    img_w           = pred_res.data.get("image_width")
    img_h           = pred_res.data.get("image_height")
    pending_path    = pred_res.data.get("pending_path")

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

    try:
        supabase_svc.table("corrections").insert({
            "prediction_id": prediction_id,
            "user_id":       user_id,
            "correct_class": body.correct_class,
            "was_correct":   body.was_correct,
            "created_at":    datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        raise HTTPException(500, f"Failed to save feedback: {e}")

    points_awarded = 1 if body.was_correct else 2
    try:
        supabase_svc.table("points").insert({
            "user_id":      user_id,
            "amount":       points_awarded,
            "action":       "correction",
            "reference_id": prediction_id,
            "created_at":   datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception:
        pass

    if image_path and img_w and img_h and pending_path:
        if body.bbox:
            bbox = {"x1": body.bbox.x1, "y1": body.bbox.y1,
                    "x2": body.bbox.x2, "y2": body.bbox.y2}
        elif all_detections:
            bbox = all_detections[0].get("bbox")
        else:
            bbox = None

        # was_correct=True → use predicted_class; False → use user's correct_class
        # If no predicted_class (no-detection case), always use body.correct_class
        correct_class = (predicted_class or body.correct_class) if body.was_correct else body.correct_class

        # Only upload if we have a valid class
        if correct_class and correct_class != "Unknown":
            background_tasks.add_task(
                _upload_to_hf,
                image_path, pending_path, bbox, correct_class, img_w, img_h,
            )
    # No-detection case: no image in storage but feedback still recorded —
    # this is correct. Points are still awarded. No HF upload needed.

    return {"message": "Feedback saved.", "points_awarded": points_awarded}
