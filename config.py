from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # OpenAI backend configuration
    openai_backend_url: str = "https://api.openai.com"
    openai_api_key: str = ""

    # Database
    database_url: str = "sqlite+aiosqlite:///./llm_proxy.db"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
