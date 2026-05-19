"""V2 smoke test: auth -> conversation -> agent loop -> llm config."""

from __future__ import annotations

import asyncio
import sys
from uuid import uuid4
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from httpx import ASGITransport, AsyncClient

from app.main import app


async def main() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            username = f"smoke_v2_{uuid4().hex[:8]}"
            password = "secret123"
            r = await client.post(
                "/api/auth/register",
                json={"username": username, "password": password},
            )
            assert r.status_code in (201, 409), r.text

            r = await client.post(
                "/api/auth/login",
                data={"username": username, "password": password},
            )
            assert r.status_code == 200, r.text
            headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
            print("[ok] login")

            r = await client.put(
                "/api/llm-config",
                json={
                    "provider": "anthropic",
                    "base_url": "https://api.anthropic.com",
                    "model": "claude-sonnet-4-6",
                    "max_tokens": 4096,
                },
                headers=headers,
            )
            assert r.status_code == 200, r.text
            assert r.json()["api_key_configured"] is False
            print("[ok] llm config")

            r = await client.post(
                "/api/conversations",
                json={
                    "task_type": "reproduce",
                    "github_url": "https://github.com/example/demo",
                    "user_prompt": "smoke v2",
                },
                headers=headers,
            )
            assert r.status_code == 201, r.text
            conversation_id = r.json()["id"]
            print("[ok] create conversation ->", conversation_id)

            for _ in range(30):
                await asyncio.sleep(0.2)
                r = await client.get(f"/api/conversations/{conversation_id}", headers=headers)
                assert r.status_code == 200, r.text
                data = r.json()
                if data["status"] in ("completed", "failed", "stopped"):
                    break
            assert data["status"] == "completed", data
            roles = [m["role"] for m in data["messages"]]
            assert "assistant" in roles and "tool" in roles, data
            print("[ok] final status ->", data["status"])
            print("[ok] messages ->", len(data["messages"]))


if __name__ == "__main__":
    asyncio.run(main())
