"""Request/response shapes. Input validation happens here, before any business logic runs."""
import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Role = Literal["client", "operator", "admin"]
Status = Literal["submitted", "in_progress", "delivered", "accepted", "rejected"]


def normalize_task(value: str) -> str:
    """Same normalisation the CSV import applies, so request task names match episode task names."""
    return re.sub(r"\s+", " ", value.strip()).lower()


class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
    role: Role
    organisation: str | None = None
    is_active: bool


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    role: Role
    organisation: str | None = Field(default=None, max_length=200)


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)


class RequestCreate(BaseModel):
    task_name: str = Field(min_length=1, max_length=200)
    episodes_requested: int = Field(gt=0, le=1_000_000)
    deadline: date
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator("task_name")
    @classmethod
    def _task(cls, v: str) -> str:
        v = normalize_task(v)
        if not v:
            raise ValueError("task_name must not be blank")
        return v

    @field_validator("deadline")
    @classmethod
    def _deadline(cls, v: date) -> date:
        if v < date.today():
            raise ValueError("deadline cannot be in the past")
        return v


class TransitionIn(BaseModel):
    to: Status
    comment: str | None = Field(default=None, max_length=1000)


class AssignIn(BaseModel):
    episode_ids: list[str] = Field(min_length=1, max_length=500)


class EpisodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    episode_id: str
    robot_id: str
    task_name: str
    recorded_at: datetime
    duration_seconds: int
    operator_name: str | None
    quality: str
