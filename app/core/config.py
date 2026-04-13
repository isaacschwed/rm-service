from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str

    # Redis
    redis_url: str

    # Encryption
    fernet_master_key: str  # base64-encoded 32-byte key for HKDF

    # Rent Manager
    rm_base_url: str = "https://api.rentmanager.com"

    # Auth
    admin_api_key: str

    # Sentry
    sentry_dsn: str = ""

    # App
    app_version: str = "1.0.0"
    app_env: str = "development"  # development | production
    log_level: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
