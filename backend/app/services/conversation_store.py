"""Append-only JSONL persistence for V2 conversation history."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings


def conversation_log_path(conversation_id: int) -> Path:
    root = get_settings().project_root / "runtime" / "conversations"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{conversation_id}.jsonl"


def append_conversation_event(conversation_id: int, event: dict) -> None:
    path = conversation_log_path(conversation_id)
    payload = {
        "timestamp": datetime.now(UTC).isoformat(),
        **event,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
