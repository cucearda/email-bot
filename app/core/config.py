from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./inbox_automator.db"
    gmail_credentials_path: str = "./credentials.json"
    gmail_token_path: str = "./token.json"
    anthropic_api_key: str = ""
    agno_claude_model: str = "claude-sonnet-4-5-20250929"


@lru_cache
def get_settings() -> Settings:
    return Settings()
