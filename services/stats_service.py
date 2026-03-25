import time
from typing import Optional

from fastapi import HTTPException

from repositories import stats_repository

_leaderboard_cache: Optional[dict] = None
_leaderboard_ts: float = 0
LEADERBOARD_TTL = 60


def get_my_stats(user_id: str) -> dict:
    try:
        profile = stats_repository.get_profile_username(user_id)
        username = profile.get("username", "Unknown") if profile else "Unknown"
    except Exception:
        username = "Unknown"

    try:
        rows = stats_repository.get_user_points(user_id)
        total_points = sum(row["amount"] for row in rows)
        from_predictions = sum(row["amount"] for row in rows if row["action"] == "prediction")
        from_corrections = sum(row["amount"] for row in rows if row["action"] == "correction")
        from_other = total_points - from_predictions - from_corrections
    except Exception:
        total_points = from_predictions = from_corrections = from_other = 0

    try:
        total_detections = stats_repository.count_predictions(user_id)
    except Exception:
        total_detections = 0

    try:
        total_corrections = stats_repository.count_corrections(user_id)
    except Exception:
        total_corrections = 0

    try:
        recent = stats_repository.get_recent_predictions(user_id)
    except Exception:
        recent = []

    return {
        "username": username,
        "total_points": total_points,
        "total_detections": total_detections,
        "total_corrections": total_corrections,
        "points_breakdown": {
            "from_predictions": from_predictions,
            "from_corrections": from_corrections,
            "from_other": from_other,
        },
        "recent_predictions": recent,
    }


def get_leaderboard() -> dict:
    global _leaderboard_cache, _leaderboard_ts

    now = time.time()
    if _leaderboard_cache and (now - _leaderboard_ts) < LEADERBOARD_TTL:
        return _leaderboard_cache

    try:
        data = stats_repository.get_leaderboard_rows(limit=20)
    except Exception as e:
        raise HTTPException(500, f"Failed to fetch leaderboard: {e}")

    result = {"leaderboard": data, "cached_at": int(now)}
    _leaderboard_cache = result
    _leaderboard_ts = now
    return result
