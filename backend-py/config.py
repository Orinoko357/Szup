from __future__ import annotations
import os
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///data/szup.db")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-me")
    JWT_REFRESH_SECRET: str = os.getenv("JWT_REFRESH_SECRET", "dev-refresh-secret-change-me")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    LDAP_ENCRYPTION_KEY: str = os.getenv("LDAP_ENCRYPTION_KEY", "")
    PDF_STORAGE_PATH: str = os.getenv("PDF_STORAGE_PATH", "/opt/szup-pdf")
    LOG_PATH: str = os.getenv("LOG_PATH", "/opt/szup-logs")
    PORT: int = int(os.getenv("PORT", "40273"))
    ALLOWED_ORIGIN: str = os.getenv("ALLOWED_ORIGIN", "http://localhost:5173")
    NODE_ENV: str = os.getenv("NODE_ENV", "development")
    SCHEDULER_ENABLED: bool = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"
    INIT_SUPERADMIN_USERNAME: str = os.getenv("INIT_SUPERADMIN_USERNAME", "admin")
    INIT_SUPERADMIN_PASSWORD: str = os.getenv("INIT_SUPERADMIN_PASSWORD", "Admin@12345678!Secure")

    @property
    def is_production(self) -> bool:
        return self.NODE_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
