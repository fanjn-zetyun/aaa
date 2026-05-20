"""WebSocket authentication helpers."""

from __future__ import annotations

from fastapi import WebSocket

from app.core.database import SessionLocal
from app.core.security import decode_access_token
from app.models import User


async def authenticate_ws(websocket: WebSocket) -> User | None:
    """Authenticate a websocket via the query-string token parameter."""
    token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except ValueError:
        return None
    user_id = payload.get("sub")
    if user_id is None:
        return None
    async with SessionLocal() as session:
        user = await session.get(User, int(user_id))
        if user and user.is_active:
            return user
    return None
