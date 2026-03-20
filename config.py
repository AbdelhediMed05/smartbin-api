from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    supabase_url: str
    supabase_anon_key: str
    supabase_service_key: str
    jwt_secret: str
    hf_token: str
    hf_dataset_repo: str
    onnx_model_path: str = "best_combined.onnx"
    confidence_threshold: float = 0.45
    iou_threshold: float = 0.60
    max_image_size_mb: int = 5
    frontend_url: str = "https://smartbin-app.onrender.com"
    debug: bool = False
    app_version: str = "1.0.0"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
