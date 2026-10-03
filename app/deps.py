"""Authentication and authorization dependencies. Every protected route depends on one of these."""
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


def current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    if creds is None:
        raise unauthorized
    try:
        user_id = decode_access_token(creds.credentials)
    except (jwt.PyJWTError, ValueError):
        raise unauthorized
    # Role and active flag are read from the database on every request (not trusted from the token),
    # so deactivating a user or changing a role takes effect immediately.
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    request.state.user_id = user.id  # picked up by the access-log middleware
    return user


def require_roles(*roles: str):
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "You do not have permission to do this")
        return user

    return checker


require_staff = require_roles("operator", "admin")
require_admin = require_roles("admin")
require_client = require_roles("client")
