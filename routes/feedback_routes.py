"""
routes/feedback_routes.py — User feedback / correction submission.

Rate limiting (OWASP A04):
  POST /feedback/{id}  15/minute per USER+IP
    Feedback is more frequent than predictions but still bounded.
    User+IP combined key: prevents one account from gaming the points system
    by submitting hundreds of corrections across rotating proxies.

Input validation (OWASP A03):
  - prediction_id UUID v4 validated via Path() regex.
  - correct_class validated against the FEEDBACK_CLASS_NAMES allowlist.
  - BBox coordinates bounded to [0, MAX_IMAGE_DIM] via BBoxCoord annotated type.
  - extra="forbid" rejects unexpected fields (parameter pollution).
"""

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, field_validator

from auth import get_current_user
from domain.classes import FEEDBACK_CLASS_NAMES, UNKNOWN_CLASS
from limiter import get_user_or_ip, limiter
from services.feedback_service import submit_feedback as submit_feedback_service
from validators import BBoxCoord, validated_uuid

router = APIRouter(tags=["feedback"])


# ── Request schemas ───────────────────────────────────────────────────────────

class BBox(BaseModel):
    """
    Pixel bounding-box coordinates.
    BBoxCoord = Annotated[float, Field(ge=0.0, le=4096.0)] — clamped at schema level.
    Out-of-bounds coordinates would corrupt YOLO label files on HuggingFace.
    """
    model_config = ConfigDict(extra="forbid")

    x1: BBoxCoord
    y1: BBoxCoord
    x2: BBoxCoord
    y2: BBoxCoord


class FeedbackRequest(BaseModel):
    """
    extra="forbid" prevents mass-assignment. correct_class is validated against
    an explicit allowlist — unknown class names are rejected before DB insert.
    """
    model_config = ConfigDict(extra="forbid")

    correct_class: str = UNKNOWN_CLASS
    was_correct:   bool
    bbox:          Optional[BBox] = None

    @field_validator("correct_class")
    @classmethod
    def validate_correct_class(cls, value: str) -> str:
        if value not in FEEDBACK_CLASS_NAMES:
            allowed = ", ".join(FEEDBACK_CLASS_NAMES)
            raise ValueError(f"correct_class must be one of: {allowed}")
        return value


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/feedback/{prediction_id}")
@limiter.limit("15/minute", key_func=get_user_or_ip)
async def submit_feedback(
    request: Request,
    response: Response,
    prediction_id: str = validated_uuid("prediction_id"),
    body: FeedbackRequest = ...,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    current_user: dict = Depends(get_current_user),
):
    request.state.user_id = current_user["user_id"]

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
