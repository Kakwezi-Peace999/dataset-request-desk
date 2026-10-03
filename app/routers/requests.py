from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import current_user, require_client, require_staff
from ..domain import STATUSES, allowed_next
from ..errors import NotFound
from ..models import Assignment, Episode, Request, RequestStatusHistory, User
from ..schemas import AssignIn, EpisodeOut, RequestCreate, TransitionIn
from ..services import assignments, workflow

router = APIRouter(prefix="/api/requests", tags=["requests"])


def _summary(req: Request, client: User, count: int, user: User) -> dict:
    return {
        "id": req.id, "task_name": req.task_name, "episodes_requested": req.episodes_requested,
        "deadline": req.deadline.isoformat(), "notes": req.notes, "status": req.status,
        "created_at": req.created_at, "updated_at": req.updated_at,
        "client": {"id": client.id, "name": client.name, "organisation": client.organisation},
        "assigned_count": count,
        "allowed_transitions": allowed_next(req.status, user.role),
    }


@router.post("", status_code=201)
def create_request(body: RequestCreate, db: Session = Depends(get_db), user: User = Depends(require_client)):
    req = Request(client_id=user.id, task_name=body.task_name, episodes_requested=body.episodes_requested,
                  deadline=body.deadline, notes=body.notes, status="submitted")
    db.add(req)
    db.flush()
    db.add(RequestStatusHistory(request_id=req.id, from_status=None, to_status="submitted", actor_id=user.id))
    db.commit()
    return _summary(req, user, 0, user)


@router.get("")
def list_requests(
    status: str | None = Query(default=None, pattern="^(" + "|".join(STATUSES) + ")$"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    counts = (
        select(Assignment.request_id, func.count().label("n")).group_by(Assignment.request_id).subquery()
    )
    q = (
        select(Request, User, func.coalesce(counts.c.n, 0))
        .join(User, User.id == Request.client_id)
        .outerjoin(counts, counts.c.request_id == Request.id)
        .order_by(Request.created_at.desc(), Request.id.desc())
    )
    if user.role == "client":  # authorization happens in the query itself
        q = q.where(Request.client_id == user.id)
    if status:
        q = q.where(Request.status == status)
    return [_summary(r, c, n, user) for r, c, n in db.execute(q).all()]


def _get_visible(db: Session, request_id: int, user: User) -> Request:
    req = db.get(Request, request_id)
    if not workflow.visible_to(req, user):
        raise NotFound("Request not found")
    return req


@router.get("/{request_id}")
def get_request(request_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    req = _get_visible(db, request_id, user)
    client = db.get(User, req.client_id)
    history = db.execute(
        select(RequestStatusHistory, User.name)
        .join(User, User.id == RequestStatusHistory.actor_id)
        .where(RequestStatusHistory.request_id == req.id)
        .order_by(RequestStatusHistory.at, RequestStatusHistory.id)
    ).all()
    out = _summary(req, client, workflow.assigned_count(db, req.id), user)
    out["history"] = [
        {"from_status": h.from_status, "to_status": h.to_status, "actor": name, "comment": h.comment, "at": h.at}
        for h, name in history
    ]
    return out


@router.post("/{request_id}/transition")
def transition(request_id: int, body: TransitionIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    req = workflow.transition(db, request_id, user, body.to, body.comment)
    return _summary(req, db.get(User, req.client_id), workflow.assigned_count(db, req.id), user)


@router.get("/{request_id}/episodes", response_model=list[EpisodeOut])
def request_episodes(request_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    req = _get_visible(db, request_id, user)
    return db.scalars(
        select(Episode).join(Assignment, Assignment.episode_pk == Episode.id)
        .where(Assignment.request_id == req.id).order_by(Episode.episode_id)
    ).all()


@router.post("/{request_id}/assignments", status_code=201)
def assign(request_id: int, body: AssignIn, db: Session = Depends(get_db), user: User = Depends(require_staff)):
    n = assignments.assign_episodes(db, request_id, user, body.episode_ids)
    return {"assigned": n, "assigned_count": workflow.assigned_count(db, request_id)}


@router.delete("/{request_id}/assignments/{episode_id}")
def unassign(request_id: int, episode_id: str, db: Session = Depends(get_db), _: User = Depends(require_staff)):
    assignments.unassign_episode(db, request_id, episode_id)
    return {"assigned_count": workflow.assigned_count(db, request_id)}
