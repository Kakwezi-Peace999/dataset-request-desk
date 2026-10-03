from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas import LoginIn, UserOut
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    ok = verify_password(user.password_hash if user else None, body.password)
    # Same message for unknown email, wrong password and deactivated account: do not reveal which accounts exist.
    if not (ok and user and user.is_active):
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": create_access_token(user.id), "token_type": "bearer", "user": UserOut.model_validate(user)}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
