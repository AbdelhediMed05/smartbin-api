from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from supabase import create_client

from auth import get_current_user
from config import get_settings

settings = get_settings()
router = APIRouter(tags=["feedback"])
limiter = Limiter(key_func=get_remote_address)

supabase_svc = create_client(settings.supabase_url, settings.supabase_service_key)

VALID_CLASSES = {"Plastic", "Glass", "Metal", "Paper", "Unknown"}


class FeedbackRequest(BaseModel):
    correct_class: Literal["Plastic", "Glass", "Metal", "Paper", "Unknown"]
    was_correct: bool


@router.post("/feedback/{prediction_id}")
@limiter.limit("20/minute")
async def submit_feedback(
    request: Request,
    prediction_id: str,
    body: FeedbackRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = current_user["user_id"]

    # Verify the prediction belongs to this user (belt + RLS suspenders)
    try:
        pred_res = supabase_svc.table("predictions").select("id,user_id").eq(
            "id", prediction_id
        ).eq("user_id", user_id).single().execute()
        if not pred_res.data:
            raise HTTPException(404, "Prediction not found.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(404, "Prediction not found.")

    # Check for duplicate feedback
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

    # Save correction
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

    # Award points
    points_awarded = 1 if body.was_correct else 2
    try:
        supabase_svc.table("points").insert({
            "user_id":      user_id,
            "amount":       points_awarded,
            "action":       "correction",
            "reference_id": prediction_id,
            "created_at":   datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        pass  # Points failure shouldn't block response

    return {"message": "Feedback saved.", "points_awarded": points_awarded}
