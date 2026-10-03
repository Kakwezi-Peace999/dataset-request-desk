from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_staff
from ..errors import Invalid
from ..models import User
from ..services.analytics import build_report

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/analytics")
def analytics(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    if date_from and date_to and date_from > date_to:
        raise Invalid("'from' must be on or before 'to'")
    return build_report(db, date_from, date_to)
