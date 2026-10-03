"""Test setup: a real PostgreSQL test database, built by running the real migrations."""
import itertools
import os
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# Must happen BEFORE the app is imported, so the app connects to the test database.
_base = make_url(os.getenv("DATABASE_URL", "postgresql+psycopg://drd:drd@localhost:5432/drd"))
TEST_DB = _base.database + "_test"
TEST_URL = _base.set(database=TEST_DB).render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = TEST_URL
os.environ["SECRET_KEY"] = "test-secret-key-at-least-32-characters-long"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Episode, User  # noqa: E402
import app.security as security  # noqa: E402
from argon2 import PasswordHasher  # noqa: E402

# Tests only: cheap argon2 settings so the suite is fast. Production uses the library defaults.
security._hasher = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
hash_password = security.hash_password


@pytest.fixture(scope="session", autouse=True)
def _database():
    admin = create_engine(_base.set(database="postgres").render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    admin.dispose()
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_URL.replace("%", "%%"))
    command.upgrade(cfg, "head")  # the tests exercise the real migrations, not create_all()
    yield


@pytest.fixture(autouse=True)
def _clean():
    with SessionLocal() as db:
        db.execute(text("TRUNCATE assignments, request_status_history, requests, episodes, users RESTART IDENTITY CASCADE"))
        db.commit()
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def make_user():
    def _make(role="client", email=None, password="password123", organisation=None, active=True) -> User:
        email = email or f"{role}-{os.urandom(3).hex()}@example.com"
        with SessionLocal() as db:
            u = User(email=email, name=email.split("@")[0], role=role, organisation=organisation,
                     password_hash=hash_password(password), is_active=active)
            db.add(u)
            db.commit()
            return u

    return _make


@pytest.fixture()
def auth(client):
    """auth(user) -> Authorization headers for that user (logs in through the real endpoint)."""

    def _auth(user: User, password="password123"):
        r = client.post("/api/auth/login", json={"email": user.email, "password": password})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _auth


_counter = itertools.count(900000)


@pytest.fixture()
def make_episodes():
    """make_episodes(n, quality, task, robot, when) -> list of new episode ids (EP-900000, ...)."""

    def _make(n=1, quality="good", task="pick cup", robot="arm-01", when="2026-09-01T10:00:00+00:00"):
        from datetime import datetime

        ids = []
        with SessionLocal() as db:
            for i in range(n):
                eid = f"EP-{next(_counter)}"
                db.add(Episode(episode_id=eid, robot_id=robot, task_name=task, recorded_at=datetime.fromisoformat(when),
                               duration_seconds=30, operator_name="Test", quality=quality))
                ids.append(eid)
            db.commit()
        return ids

    return _make


@pytest.fixture()
def future_deadline() -> str:
    return (date.today() + timedelta(days=30)).isoformat()


@pytest.fixture()
def new_request(client, auth, future_deadline):
    """new_request(client_user, count=2, task='pick cup') -> request id, created through the API."""

    def _new(user, count=2, task="pick cup"):
        r = client.post("/api/requests", headers=auth(user),
                        json={"task_name": task, "episodes_requested": count, "deadline": future_deadline})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    return _new
