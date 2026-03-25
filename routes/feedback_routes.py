from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

from auth import get_current_user
from domain.classes import FEEDBACK_CLASS_NAMES, UNKNOWN_CLASS
from services.feedback_service import submit_feedback as submit_feedback_service

router = APIRouter(tags=["feedback"])
limiter = Limiter(key_func=get_remote_address)


class BBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class FeedbackRequest(BaseModel):
    correct_class: str = UNKNOWN_CLASS
    was_correct: bool
    bbox: Optional[BBox] = None

    @field_validator("correct_class")
    @classmethod
    def validate_correct_class(cls, value: str) -> str:
        if value not in FEEDBACK_CLASS_NAMES:
            allowed = ", ".join(FEEDBACK_CLASS_NAMES)
            raise ValueError(f"correct_class must be one of: {allowed}")
        return value


@router.post("/feedback/{prediction_id}")
@limiter.limit("20/minute")
async def submit_feedback(
    request: Request,
    prediction_id: str,
    body: FeedbackRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    bbox_payload = None
    if body.bbox:
        bbox_payload = {
            "x1": body.bbox.x1,
            "y1": body.bbox.y1,
            "x2": body.bbox.x2,
            "y2": body.bbox.y2,
        }

    return submit_feedback_service(
        prediction_id=prediction_id,
        user_id=current_user["user_id"],
        correct_class=body.correct_class,
        was_correct=body.was_correct,
        bbox_payload=bbox_payload,
        background_tasks=background_tasks,
    )
