"""Password hashing (argon2id) and signed access tokens (JWT)."""
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .config import settings

_hasher = PasswordHasher()
# Verified against when the email is unknown, so "unknown email" and "wrong password" take similar time.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=settings.access_token_minutes)}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> int:
    """Returns the user id or raises jwt.PyJWTError."""
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"], options={"require": ["exp", "sub"]})
    return int(payload["sub"])
