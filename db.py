"""
db.py — Shared Supabase clients and HuggingFace API instance.
Import from here instead of creating new clients in every module.
"""
from huggingface_hub import HfApi
from supabase import create_client

from config import get_settings

settings = get_settings()

# One service-role client shared across all routes
supabase_svc  = create_client(settings.supabase_url, settings.supabase_service_key)

# One anon client shared across all routes
supabase_anon = create_client(settings.supabase_url, settings.supabase_anon_key)

# One HuggingFace API instance
hf_api = HfApi(token=settings.hf_token)
