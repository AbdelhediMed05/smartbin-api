import time

from fastapi import APIRouter
from supabase import create_client

from config import get_settings
from inference import get_model

settings = get_settings()
router = APIRouter(tags=["health"])

supabase_svc = create_client(settings.supabase_url, settings.supabase_service_key)

_start_time = time.time()


@router.api_route("/health", methods=["GET", "HEAD"])
async def health():
    # DB check
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

    return {
        "status":         "ok" if db_status == "ok" and model_status == "ok" else "degraded",
        "db":             db_status,
        "model":          model_status,
        "version":        settings.app_version,
        "uptime_seconds": uptime,
    }
