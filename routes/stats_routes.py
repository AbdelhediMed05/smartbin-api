from fastapi import APIRouter, Depends, Request, Response

from auth import get_current_user
from limiter import get_user_or_ip, limiter
from services.stats_service import get_leaderboard, get_my_stats

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/me")
@limiter.limit("30/minute", key_func=get_user_or_ip)   # user+IP bucket
async def my_stats(
    request: Request,
    response: Response,
    current_user: dict = Depends(get_current_user),
):
    request.state.user_id = current_user["user_id"]
    return get_my_stats(current_user["user_id"])


@router.get("/leaderboard")
@limiter.limit("20/minute")                             # IP-only (public endpoint)
async def leaderboard(request: Request, response: Response):
    return get_leaderboard()
