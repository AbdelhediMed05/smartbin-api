import time
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from db import supabase_svc

from auth import get_current_user
from config import get_settings

settings = get_settings()
router = APIRouter(prefix="/stats", tags=["stats"])


# Simple in-memory leaderboard cache
_leaderboard_cache: Optional[dict] = None
_leaderboard_ts: float = 0
LEADERBOARD_TTL = 60  # seconds


@router.get("/me")
async def my_stats(current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]

    # Profile
    try:
        profile_res = supabase_svc.table("profiles").select(
            "username"
        ).eq("id", user_id).single().execute()
        username = profile_res.data.get("username", "Unknown") if profile_res.data else "Unknown"
    except Exception:
        username = "Unknown"

    # Points breakdown
    try:
        points_res = supabase_svc.table("points").select(
            "amount,action"
        ).eq("user_id", user_id).execute()
        rows = points_res.data or []
        total_points = sum(r["amount"] for r in rows)
        from_predictions = sum(r["amount"] for r in rows if r["action"] == "prediction")
        from_corrections = sum(r["amount"] for r in rows if r["action"] == "correction")
        from_other = total_points - from_predictions - from_corrections
    except Exception:
        total_points = from_predictions = from_corrections = from_other = 0

    # Detection count
    try:
        det_res = supabase_svc.table("predictions").select(
            "id", count="exact"
        ).eq("user_id", user_id).execute()
        total_detections = det_res.count or 0
    except Exception:
        total_detections = 0

    # Correction count
    try:
        cor_res = supabase_svc.table("corrections").select(
            "id", count="exact"
        ).eq("user_id", user_id).execute()
        total_corrections = cor_res.count or 0
    except Exception:
        total_corrections = 0

    # Recent predictions (last 10)
    try:
        recent_res = supabase_svc.table("predictions").select(
            "id,predicted_class,confidence,created_at"
        ).eq("user_id", user_id).order("created_at", desc=True).limit(10).execute()
        recent = recent_res.data or []
    except Exception:
        recent = []

    return {
        "username":          username,
        "total_points":      total_points,
        "total_detections":  total_detections,
        "total_corrections": total_corrections,
        "points_breakdown": {
            "from_predictions": from_predictions,
            "from_corrections": from_corrections,
            "from_other":       from_other,
        },
        "recent_predictions": recent,
    }


@router.get("/leaderboard")
async def leaderboard():
    global _leaderboard_cache, _leaderboard_ts

    now = time.time()
    if _leaderboard_cache and (now - _leaderboard_ts) < LEADERBOARD_TTL:
        return _leaderboard_cache

    try:
        res = supabase_svc.table("leaderboard").select("*").limit(20).execute()
        data = res.data or []
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch leaderboard: {e}")

    result = {"leaderboard": data, "cached_at": int(now)}
    _leaderboard_cache = result
    _leaderboard_ts = now
    return result
