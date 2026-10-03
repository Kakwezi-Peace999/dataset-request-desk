"""Seed step: creates the demo accounts (passwords hashed) and optionally imports the sample episodes.

Safe to run on every start: existing users are left untouched and the import is idempotent.
"""
import json
import logging
from pathlib import Path

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import User
from .security import hash_password
from .services.importer import import_csv

log = logging.getLogger("drd.seed")


def seed_users(seed_dir: Path) -> int:
    created = 0
    with SessionLocal() as db:
        for u in json.loads((seed_dir / "users.json").read_text(encoding="utf-8")):
            email = u["email"].strip().lower()
            if db.scalar(select(User.id).where(User.email == email)):
                continue
            db.add(User(email=email, name=u["name"], role=u["role"], organisation=u.get("organisation"),
                        password_hash=hash_password(u["password"])))
            created += 1
        db.commit()
    return created


def seed_episodes(seed_dir: Path) -> dict:
    with SessionLocal() as db:
        return import_csv(db, (seed_dir / "episodes.csv").read_text(encoding="utf-8-sig"))


def run_seed() -> None:
    seed_dir = Path(settings.seed_dir)
    created = seed_users(seed_dir)
    log.info("seed users", extra={"ctx": {"created": created}})
    if settings.seed_episodes:
        rep = seed_episodes(seed_dir)
        log.info("seed episodes", extra={"ctx": {k: v for k, v in rep.items() if k not in ("issues",)}})
