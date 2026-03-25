from db import supabase_anon, supabase_svc


def sign_up(email: str, password: str, username: str, email_redirect_to: str | None = None):
    options = {"data": {"username": username}}
    if email_redirect_to:
        options["email_redirect_to"] = email_redirect_to

    return supabase_anon.auth.sign_up({
        "email": email,
        "password": password,
        "options": options,
    })


def sign_in(email: str, password: str):
    return supabase_anon.auth.sign_in_with_password({
        "email": email,
        "password": password,
    })


def refresh_session(refresh_token: str):
    return supabase_anon.auth.refresh_session(refresh_token)


def sign_out():
    return supabase_anon.auth.sign_out()


def get_profile_login_state(user_id: str):
    return supabase_svc.table("profiles").select(
        "failed_logins,locked_until,is_active"
    ).eq("id", user_id).single().execute().data


def get_profile_failed_logins(user_id: str):
    return supabase_svc.table("profiles").select(
        "id,failed_logins"
    ).eq("id", user_id).single().execute().data


def update_profile(user_id: str, payload: dict):
    return supabase_svc.table("profiles").update(payload).eq("id", user_id).execute()


def get_user_by_email(email: str):
    return supabase_svc.auth.admin.get_user_by_email(email)
