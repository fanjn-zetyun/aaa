"""应用配置（pydantic-settings）。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# 项目根目录：backend/app/core/config.py → 上 3 级
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / "backend" / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "LOBSTER 科研助手平台"
    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_debug: bool = True

    secret_key: str = "change-me"
    access_token_expire_minutes: int = 60 * 24
    jwt_algorithm: str = "HS256"

    database_url: str = "sqlite+aiosqlite:///./runtime/app.db"

    default_admin_username: str = "admin"
    default_admin_password: str = "admin123"

    workspace_root: str = "runtime/workspaces"
    skills_dir: str = "skills"

    lab4ai_credential_key: str = ""

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def workspace_root_path(self) -> Path:
        return PROJECT_ROOT / self.workspace_root

    @property
    def skills_dir_path(self) -> Path:
        return PROJECT_ROOT / self.skills_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
