"""Data model. Constraints live in the database as well as in code, so bad data cannot get in by any route."""
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('client','operator','admin')", name="ck_users_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)  # always stored lower-case
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    organisation: Mapped[str | None] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))  # argon2id hash, never the password
    is_active: Mapped[bool] = mapped_column(server_default=sa.true())
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class Robot(Base):
    """Reference data: the robots we know about. Episodes must point at one of them."""

    __tablename__ = "robots"
    robot_id: Mapped[str] = mapped_column(String(50), primary_key=True)


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (
        CheckConstraint("quality IN ('good','usable','bad')", name="ck_episodes_quality"),
        CheckConstraint("duration_seconds > 0", name="ck_episodes_duration_positive"),
        Index("ix_episodes_recorded_at", "recorded_at"),
        Index("ix_episodes_robot_recorded", "robot_id", "recorded_at"),
        Index("ix_episodes_task_quality", "task_name", "quality"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    episode_id: Mapped[str] = mapped_column(String(50), unique=True)  # business key, e.g. EP-00042
    robot_id: Mapped[str] = mapped_column(ForeignKey("robots.robot_id"))
    task_name: Mapped[str] = mapped_column(String(200))
    recorded_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    duration_seconds: Mapped[int]
    operator_name: Mapped[str | None] = mapped_column(String(200))
    quality: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class Request(Base):
    __tablename__ = "requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('submitted','in_progress','delivered','accepted','rejected')", name="ck_requests_status"
        ),
        CheckConstraint("episodes_requested > 0", name="ck_requests_count_positive"),
        Index("ix_requests_client", "client_id"),
        Index("ix_requests_status", "status"),
        Index("ix_requests_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    task_name: Mapped[str] = mapped_column(String(200))
    episodes_requested: Mapped[int]
    deadline: Mapped[date]
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default="submitted")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class RequestStatusHistory(Base):
    """Append-only audit trail of every status change."""

    __tablename__ = "request_status_history"
    __table_args__ = (
        Index("ix_history_request_at", "request_id", "at"),
        Index("ix_history_to_status", "to_status", "request_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())


class Assignment(Base):
    """An episode assigned to a request.

    UNIQUE(episode_pk) is what guarantees 'an episode belongs to at most one request':
    even two simultaneous requests cannot both win, the database rejects the second.
    """

    __tablename__ = "assignments"
    __table_args__ = (
        UniqueConstraint("episode_pk", name="uq_assignments_episode"),
        Index("ix_assignments_request", "request_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("requests.id"))
    episode_pk: Mapped[int] = mapped_column(BigInteger, ForeignKey("episodes.id"))
    assigned_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assigned_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
