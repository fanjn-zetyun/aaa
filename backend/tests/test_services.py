"""services 层单元测试：workspace 工具函数、OpenclawManager。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.openclaw.runner import ProcessHandle, TaskInput
from app.services.openclaw.workspace import prepare_workspace, write_lab4ai_env


pytestmark = pytest.mark.asyncio


class TestPrepareWorkspace:
    def test_creates_workspace_dir(self, tmp_path: Path):
        with patch("app.services.openclaw.workspace.get_settings") as mock_settings:
            settings = mock_settings.return_value
            settings.workspace_root_path = tmp_path / "workspaces"
            settings.skills_dir_path = tmp_path / "skills"
            (tmp_path / "skills").mkdir()
            (tmp_path / "skills" / "test_skill").mkdir()

            ws = prepare_workspace(42)
            assert ws.exists()
            assert (ws / ".openclaw").is_dir()
            assert (ws / "skills").exists()

    def test_idempotent(self, tmp_path: Path):
        with patch("app.services.openclaw.workspace.get_settings") as mock_settings:
            settings = mock_settings.return_value
            settings.workspace_root_path = tmp_path / "workspaces"
            settings.skills_dir_path = tmp_path / "skills"
            (tmp_path / "skills").mkdir()

            ws1 = prepare_workspace(7)
            ws2 = prepare_workspace(7)
            assert ws1 == ws2

    def test_missing_skills_dir_raises(self, tmp_path: Path):
        with patch("app.services.openclaw.workspace.get_settings") as mock_settings:
            settings = mock_settings.return_value
            settings.workspace_root_path = tmp_path / "workspaces"
            settings.skills_dir_path = tmp_path / "nonexistent_skills"

            with pytest.raises(FileNotFoundError):
                prepare_workspace(99)


class TestWriteLab4aiEnv:
    def test_writes_env_file(self, tmp_path: Path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / ".openclaw").mkdir()

        write_lab4ai_env(ws, "13800138000", "mypassword")

        env_file = ws / ".openclaw" / ".env"
        assert env_file.exists()
        content = env_file.read_text()
        assert "LAB4AI_PHONE=13800138000" in content
        assert "LAB4AI_PASSWORD=mypassword" in content

    def test_skips_when_no_credentials(self, tmp_path: Path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / ".openclaw").mkdir()

        write_lab4ai_env(ws, None, None)
        assert not (ws / ".openclaw" / ".env").exists()

    def test_skips_when_partial_credentials(self, tmp_path: Path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / ".openclaw").mkdir()

        write_lab4ai_env(ws, "13800138000", None)
        assert not (ws / ".openclaw" / ".env").exists()


class TestOpenclawManager:
    async def test_start_task(self):
        from app.services.openclaw.manager import OpenclawManager

        mock_runner = AsyncMock()
        mock_proc = MagicMock()
        mock_proc.pid = 100
        handle = ProcessHandle(task_id=1, pid=100, workspace_path="/tmp/ws/1", process=mock_proc)
        mock_runner.start.return_value = handle
        mock_runner.wait.return_value = 0

        manager = OpenclawManager(mock_runner)

        mock_instance = MagicMock()
        mock_instance.status = "pending"

        with patch("app.services.openclaw.manager.SessionLocal") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_instance
            mock_session.execute.return_value = mock_result
            mock_session.commit = AsyncMock()

            result_handle = await manager.start_task(
                TaskInput(task_id=1, github_url="https://github.com/a/b")
            )

        assert result_handle.pid == 100
        assert manager.get_handle(1) is not None
        mock_runner.start.assert_called_once()

    async def test_start_task_idempotent(self):
        from app.services.openclaw.manager import OpenclawManager

        mock_runner = AsyncMock()
        mock_proc = MagicMock()
        mock_proc.pid = 100
        handle = ProcessHandle(task_id=1, pid=100, workspace_path="/tmp/ws/1", process=mock_proc)
        mock_runner.start.return_value = handle
        mock_runner.wait.return_value = 0

        manager = OpenclawManager(mock_runner)

        mock_instance = MagicMock()
        mock_instance.status = "pending"

        with patch("app.services.openclaw.manager.SessionLocal") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_instance
            mock_session.execute.return_value = mock_result
            mock_session.commit = AsyncMock()

            task = TaskInput(task_id=1, github_url="https://github.com/a/b")
            h1 = await manager.start_task(task)
            h2 = await manager.start_task(task)

        assert h1 is h2
        assert mock_runner.start.call_count == 1

    async def test_stop_task(self):
        from app.services.openclaw.manager import OpenclawManager

        mock_runner = AsyncMock()
        mock_proc = MagicMock()
        mock_proc.pid = 200
        handle = ProcessHandle(task_id=2, pid=200, workspace_path="/tmp/ws/2", process=mock_proc)
        mock_runner.start.return_value = handle
        mock_runner.stop.return_value = 0
        mock_runner.wait.return_value = 0

        manager = OpenclawManager(mock_runner)

        mock_instance = MagicMock()
        mock_instance.status = "running"

        with patch("app.services.openclaw.manager.SessionLocal") as mock_session_cls:
            mock_session = AsyncMock()
            mock_session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_instance
            mock_session.execute.return_value = mock_result
            mock_session.commit = AsyncMock()

            task = TaskInput(task_id=2, github_url="https://github.com/a/b")
            await manager.start_task(task)
            rc = await manager.stop_task(2)

        assert rc == 0
        mock_runner.stop.assert_called_once()

    async def test_stop_nonexistent_task(self):
        from app.services.openclaw.manager import OpenclawManager

        mock_runner = AsyncMock()
        manager = OpenclawManager(mock_runner)
        rc = await manager.stop_task(999)
        assert rc is None
