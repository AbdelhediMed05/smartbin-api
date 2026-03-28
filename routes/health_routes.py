"""
routes/health_routes.py — Service health check.

Rate limiting (OWASP A04):
  GET/HEAD /health  60/minute per IP
    HEAD is used by UptimeRobot (typically once per minute) and must not be
    blocked. GET is used by human operators. 60/min is generous for monitoring
    while still preventing /health from becoming a DoS amplifier.

Information disclosure (OWASP A05):
  - Version string is omitted in production (debug=False) to reduce fingerprinting surface.
  - DB check catches all exceptions and returns a generic "error" status string —
    the actual exception is never surfaced in the response.
"""

import time

from fastapi import APIRouter, Request, Response
from db import supabase_svc

from config import get_settings
from inference import get_model
from limiter import limiter

settings = get_settings()
router   = APIRouter(tags=["health"])

_start_time = time.time()


@router.api_route("/health", methods=["GET", "HEAD"])
@limiter.limit("60/minute")   # generous for monitoring tools; bounded for DoS
async def health(request: Request, response: Response):
    # HEAD requests (UptimeRobot pings) — skip DB query for speed
    if request.method == "HEAD":
        return {}

    # DB check — catch everything; never leak exception detail in response
    db_status = "ok"
    try:
        supabase_svc.table("profiles").select("id").limit(1).execute()
    except Exception:
        db_status = "error"

    # Model check
    model_status = "ok"
    try:
        get_model()
    except Exception:
        model_status = "error"

    uptime = int(time.time() - _start_time)

    response: dict = {
        "status":         "ok" if db_status == "ok" and model_status == "ok" else "degraded",
        "db":             db_status,
        "model":          model_status,
        "uptime_seconds": uptime,
    }

    # OWASP A05: only expose version in debug/development — reduces fingerprinting
    if settings.debug:
        response["version"] = settings.app_version

    return response
