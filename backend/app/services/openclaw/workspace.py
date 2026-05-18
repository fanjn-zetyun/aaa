"""创建 / 准备任务 workspace 的工具函数。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from app.core.config import get_settings


def prepare_workspace(task_id: int) -> Path:
    """为任务创建独立 workspace，并把 skills 目录链接进去。

    workspace 结构：
        runtime/workspaces/<task_id>/
        ├── skills/         # 软链到项目根 skills/（Windows 上无符号链接权限时改为复制）
        └── .openclaw/      # openclaw 配置目录（凭证 .env 由调用方写入）
    """
    settings = get_settings()
    workspace = settings.workspace_root_path / str(task_id)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / ".openclaw").mkdir(exist_ok=True)

    skills_link = workspace / "skills"
    skills_source = settings.skills_dir_path

    if skills_link.exists() or skills_link.is_symlink():
        return workspace

    if not skills_source.exists():
        raise FileNotFoundError(f"skills 源目录不存在: {skills_source}")

    try:
        if sys.platform == "win32":
            os.symlink(skills_source, skills_link, target_is_directory=True)
        else:
            skills_link.symlink_to(skills_source, target_is_directory=True)
    except (OSError, NotImplementedError):
        # 软链接失败（Windows 无开发者权限等）→ 退化为复制
        shutil.copytree(skills_source, skills_link)

    return workspace


def write_lab4ai_env(workspace: Path, phone: str | None, password: str | None) -> None:
    """把 Lab4AI 凭证写入 workspace 内的 .openclaw/.env，供 skills 读取。"""
    if not phone or not password:
        return
    env_path = workspace / ".openclaw" / ".env"
    env_path.write_text(
        f"LAB4AI_PHONE={phone}\nLAB4AI_PASSWORD={password}\n",
        encoding="utf-8",
    )
