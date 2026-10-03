from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import require_staff
from ..domain import QUALITIES
from ..errors import Invalid
from ..models import Assignment, Episode, User
from ..services.importer import import_csv

router = APIRouter(prefix="/api", tags=["episodes"])


@router.get("/episodes")
def list_episodes(
    task_name: str | None = Query(default=None, max_length=200),
    quality: str | None = Query(default=None, pattern="^(" + "|".join(QUALITIES) + ")$"),
    robot_id: str | None = Query(default=None, max_length=50),
    unassigned_only: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_staff),
):
    base = select(Episode).outerjoin(Assignment, Assignment.episode_pk == Episode.id)
    if task_name:
        base = base.where(Episode.task_name == task_name.strip().lower())
    if quality:
        base = base.where(Episode.quality == quality)
    if robot_id:
        base = base.where(Episode.robot_id == robot_id.strip().lower())
    if unassigned_only:
        base = base.where(Assignment.id.is_(None))
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    rows = db.execute(
        base.add_columns(Assignment.request_id)
        .order_by(Episode.recorded_at.desc(), Episode.id)
        .limit(limit).offset(offset)
    ).all()
    items = [
        {
            "episode_id": e.episode_id, "robot_id": e.robot_id, "task_name": e.task_name,
            "recorded_at": e.recorded_at, "duration_seconds": e.duration_seconds,
            "operator_name": e.operator_name, "quality": e.quality, "assigned_request_id": rid,
        }
        for e, rid in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/episodes/task-names")
def task_names(db: Session = Depends(get_db), _: User = Depends(require_staff)):
    return db.scalars(select(Episode.task_name).distinct().order_by(Episode.task_name)).all()


@router.post("/imports/episodes")
async def import_episodes(file: UploadFile = File(...), db: Session = Depends(get_db), _: User = Depends(require_staff)):
    limit = settings.max_upload_mb * 1024 * 1024
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise Invalid(f"File is larger than {settings.max_upload_mb} MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Invalid("File must be UTF-8 encoded text")
    return import_csv(db, text)
