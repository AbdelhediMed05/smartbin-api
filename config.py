from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    supabase_url: str
    supabase_anon_key: str
    supabase_service_key: str
    jwt_secret: str
    hf_token: str
    hf_dataset_repo: str
    onnx_model_path: str 
    confidence_threshold: float 
    iou_threshold: float 
    max_image_size_mb: int
    frontend_url: str 
    trusted_host: str
    debug: bool 
    app_version: str = "1.0.0"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
