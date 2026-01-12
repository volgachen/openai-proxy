from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Dict
import json
import os


class Settings(BaseSettings):
    # OpenAI backend configuration
    openai_backend_url: str = "https://api.openai.com"
    openai_api_key: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./llm_proxy.db"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Concurrency limit (0 = unlimited)
    max_concurrent_requests: int = 500

    # Request timeout in seconds for LLM API calls
    request_timeout: int = 300

    # Model name mapping file path
    model_mapping_file: str = "model_mapping.json"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


@lru_cache()
def get_model_mapping() -> Dict[str, str]:
    """Load model name mapping from JSON file."""
    settings = get_settings()
    if os.path.exists(settings.model_mapping_file):
        with open(settings.model_mapping_file, "r") as f:
            return json.load(f)
    return {}
