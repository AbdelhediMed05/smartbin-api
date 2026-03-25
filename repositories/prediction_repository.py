from db import hf_api, supabase_svc


def remove_storage_paths(paths: list[str]):
    if paths:
        return supabase_svc.storage.from_("smartbin-images").remove(paths)
    return None


def upload_pending_image(path: str, content: bytes, content_type: str = "image/jpeg"):
    return supabase_svc.storage.from_("smartbin-images").upload(
        path=path,
        file=content,
        file_options={"content-type": content_type},
    )


def download_pending_image(path: str):
    return supabase_svc.storage.from_("smartbin-images").download(path)


def insert_prediction(payload: dict):
    return supabase_svc.table("predictions").insert(payload).execute()


def update_prediction(prediction_id: str, payload: dict):
    return supabase_svc.table("predictions").update(payload).eq("id", prediction_id).execute()


def clear_prediction_pending_path(prediction_id: str):
    return update_prediction(prediction_id, {"pending_path": None})


def get_user_pending_paths(user_id: str) -> list[str]:
    res = supabase_svc.table("predictions").select(
        "pending_path"
    ).eq("user_id", user_id).not_.is_("pending_path", "null").execute()
    return [row["pending_path"] for row in (res.data or []) if row.get("pending_path")]


def clear_user_pending_paths(user_id: str):
    return supabase_svc.table("predictions").update(
        {"pending_path": None}
    ).eq("user_id", user_id).not_.is_("pending_path", "null").execute()


def insert_points(payload: dict):
    return supabase_svc.table("points").insert(payload).execute()


def insert_rate_limit_log(payload: dict):
    return supabase_svc.table("rate_limit_log").insert(payload).execute()


def get_prediction_for_user(prediction_id: str, user_id: str, fields: str):
    res = supabase_svc.table("predictions").select(fields).eq(
        "id", prediction_id
    ).eq("user_id", user_id).single().execute()
    return res.data


def get_existing_correction(prediction_id: str, user_id: str):
    res = supabase_svc.table("corrections").select("id").eq(
        "prediction_id", prediction_id
    ).eq("user_id", user_id).execute()
    return res.data or []


def insert_correction(payload: dict):
    return supabase_svc.table("corrections").insert(payload).execute()


def upload_training_image(path_in_repo: str, content: bytes, repo_id: str):
    return hf_api.upload_file(
        path_or_fileobj=content,
        path_in_repo=path_in_repo,
        repo_id=repo_id,
        repo_type="dataset",
    )
