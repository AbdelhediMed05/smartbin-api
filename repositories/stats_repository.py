from db import supabase_svc


def get_profile_username(user_id: str):
    return supabase_svc.table("profiles").select(
        "username"
    ).eq("id", user_id).single().execute().data


def get_user_points(user_id: str):
    return supabase_svc.table("points").select(
        "amount,action"
    ).eq("user_id", user_id).execute().data or []


def count_predictions(user_id: str) -> int:
    res = supabase_svc.table("predictions").select(
        "id", count="exact"
    ).eq("user_id", user_id).execute()
    return res.count or 0


def count_corrections(user_id: str) -> int:
    res = supabase_svc.table("corrections").select(
        "id", count="exact"
    ).eq("user_id", user_id).execute()
    return res.count or 0


def get_recent_predictions(user_id: str, limit: int = 10):
    return supabase_svc.table("predictions").select(
        "id,predicted_class,confidence,created_at"
    ).eq("user_id", user_id).order("created_at", desc=True).limit(limit).execute().data or []


def get_leaderboard_rows(limit: int = 20):
    return supabase_svc.table("leaderboard").select("*").limit(limit).execute().data or []
