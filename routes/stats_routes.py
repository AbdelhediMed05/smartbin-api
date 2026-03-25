from fastapi import APIRouter, Depends

from auth import get_current_user
from services.stats_service import get_leaderboard, get_my_stats

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/me")
async def my_stats(current_user: dict = Depends(get_current_user)):
    return get_my_stats(current_user["user_id"])


@router.get("/leaderboard")
async def leaderboard():
    return get_leaderboard()
