from typing import Any, Optional

import sentry_sdk
from fastapi import APIRouter, Request, status
from pydantic import Field

from request_limits import enforce_route_limits
from request_models import StrictRequestModel
from services.monitoring_service import scrub_text, scrub_value

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


class FrontendErrorRequest(StrictRequestModel):
    type: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=4000)
    stack: Optional[str] = Field(default=None, max_length=12000)
    url: Optional[str] = Field(default=None, max_length=2048)
    method: Optional[str] = Field(default=None, max_length=16)
    status_code: Optional[int] = None
    duration_ms: Optional[int] = None
    page: Optional[str] = Field(default=None, max_length=2048)
    user_agent: Optional[str] = Field(default=None, max_length=1024)
    context: dict[str, Any] = Field(default_factory=dict)


@router.post("/frontend-error", status_code=status.HTTP_202_ACCEPTED)
async def frontend_error(request: Request, body: FrontendErrorRequest):
    enforce_route_limits(request, scope="frontend_monitoring")
    cleaned_context = scrub_value(body.context)

    with sentry_sdk.push_scope() as scope:
        scope.set_tag("source", "frontend")
        scope.set_tag("error_type", scrub_text(body.type))
        if body.status_code is not None:
            scope.set_tag("status_code", str(body.status_code))
        if body.method:
            scope.set_tag("method", scrub_text(body.method))
        if body.url:
            scope.set_extra("url", scrub_text(body.url, "url"))
        if body.page:
            scope.set_extra("page", scrub_text(body.page, "page"))
        if body.stack:
            scope.set_extra("stack", scrub_text(body.stack, "stack"))
        if body.duration_ms is not None:
            scope.set_extra("duration_ms", body.duration_ms)
        if body.user_agent:
            scope.set_extra("user_agent", scrub_text(body.user_agent, "user_agent"))
        if cleaned_context:
            scope.set_context("frontend", cleaned_context)

        sentry_sdk.capture_message(scrub_text(body.message, "message"), level="error")

    return {"message": "accepted"}
