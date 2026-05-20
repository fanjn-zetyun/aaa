"""Auth request and response schemas."""

from __future__ import annotations

from datetime import datetime

import phonenumbers
from pydantic import BaseModel, Field, field_validator

from app.models.user import UserRole


class RegisterRequest(BaseModel):
    phone: str = Field(min_length=1, max_length=32)
    institution: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=6, max_length=128)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        phone = value.strip()
        if not phone:
            raise ValueError("请输入手机号")
        try:
            parsed = phonenumbers.parse(phone, "CN")
        except phonenumbers.NumberParseException as exc:
            raise ValueError("请输入有效的中国大陆手机号") from exc
        if not phonenumbers.is_valid_number_for_region(parsed, "CN"):
            raise ValueError("请输入有效的中国大陆手机号")
        return phonenumbers.national_significant_number(parsed)

    @field_validator("institution")
    @classmethod
    def normalize_institution(cls, value: str) -> str:
        institution = value.strip()
        if not institution:
            raise ValueError("请输入机构或学校名称")
        return institution


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str
    institution: str
    role: UserRole
    gpu_quota_hours: float
    cpu_quota_hours: float
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
