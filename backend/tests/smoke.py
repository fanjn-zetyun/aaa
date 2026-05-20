"""端到端冒烟测试：注册 → 登录 → 创建任务 → 等 mock 跑完 → 查询状态。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from httpx import ASGITransport, AsyncClient

from app.main import app


async def main() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 触发 lifespan（建表 + 创建默认 admin）
        async with app.router.lifespan_context(app):
            # 健康检查
            r = await client.get("/api/health")
            assert r.status_code == 200, r.text
            print("[ok] /api/health ->", r.json())

            # 注册新用户
            r = await client.post(
                "/api/auth/register",
                json={
                    "phone": "13800138888",
                    "institution": "Smoke Test Lab",
                    "password": "secret123",
                },
            )
            assert r.status_code in (201, 409), r.text
            print("[ok] register ->", r.status_code)

            # 登录
            r = await client.post(
                "/api/auth/login",
                data={"username": "13800138888", "password": "secret123"},
            )
            assert r.status_code == 200, r.text
            token = r.json()["access_token"]
            print("[ok] login ->", token[:24], "...")
            headers = {"Authorization": f"Bearer {token}"}

            # 当前用户
            r = await client.get("/api/auth/me", headers=headers)
            assert r.status_code == 200, r.text
            print("[ok] /api/auth/me ->", r.json()["username"])

            # 创建一个任务（mock runner 会拉起 _mock_script.py 输出 17 行日志）
            r = await client.post(
                "/api/claw-instances",
                json={
                    "github_url": "https://github.com/example/demo",
                    "user_prompt": "smoke test",
                },
                headers=headers,
            )
            assert r.status_code == 201, r.text
            instance = r.json()
            print(
                "[ok] create instance -> id={id} status={status} pid={pid}".format(**instance)
            )
            instance_id = instance["id"]

            # 列表
            r = await client.get("/api/claw-instances", headers=headers)
            assert r.status_code == 200 and len(r.json()) >= 1, r.text
            print("[ok] list instances -> count =", len(r.json()))

            # mock 脚本每秒一行，17 行 → 等不超过 25 秒
            for _ in range(60):
                await asyncio.sleep(0.5)
                r = await client.get(
                    f"/api/claw-instances/{instance_id}", headers=headers
                )
                inst = r.json()
                if inst["status"] in ("completed", "failed", "stopped"):
                    print("[ok] final status ->", inst["status"])
                    return
            print("[fail] task 在超时窗口内未完成；当前状态 =", inst["status"])
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
