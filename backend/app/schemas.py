from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=10, max_length=128)
    role: Literal["citizen", "authority"] = "citizen"
    invite_code: str | None = None
    department_code: str | None = None
    jurisdiction_area: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    name: str
    role: str
    model_config = ConfigDict(from_attributes=True)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class StatusUpdate(BaseModel):
    status: Literal["IN_PROGRESS", "RESOLVED", "CLOSED"]
    comment: str | None = Field(default=None, max_length=2000)


class VerificationRequest(BaseModel):
    is_resolved: bool
    comment: str | None = Field(default=None, max_length=2000)
