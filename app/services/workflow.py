"""Request status workflow. All status changes go through transition()."""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..domain import TRANSITIONS
from ..errors import Conflict, Forbidden, NotFound
from ..models import Assignment, Request, RequestStatusHistory, User


def lock_request(db: Session, request_id: int) -> Request | None:
    """Load a request and lock its row until the transaction ends (SELECT ... FOR UPDATE).

    Both transitions and assignment changes lock the same row, so 'count the assignments, then mark
    delivered' cannot interleave with 'remove an assignment'.
    """
    return db.execute(select(Request).where(Request.id == request_id).with_for_update()).scalar_one_or_none()


def assigned_count(db: Session, request_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Assignment).where(Assignment.request_id == request_id)) or 0


def visible_to(req: Request | None, user: User) -> bool:
    """Clients only see their own requests; staff see everything."""
    if req is None:
        return False
    return user.role != "client" or req.client_id == user.id


def transition(db: Session, request_id: int, actor: User, to: str, comment: str | None = None) -> Request:
    req = lock_request(db, request_id)
    # 404 (not 403) for other clients' requests, so ids of other clients' requests are not revealed.
    if not visible_to(req, actor):
        raise NotFound("Request not found")

    allowed_roles = TRANSITIONS.get((req.status, to))
    if allowed_roles is None:
        raise Conflict(f"Cannot move a request from '{req.status}' to '{to}'")
    if actor.role not in allowed_roles:
        raise Forbidden(f"Your role ({actor.role}) cannot move a request from '{req.status}' to '{to}'")

    if to == "delivered":
        have = assigned_count(db, req.id)
        if have < req.episodes_requested:
            raise Conflict(
                f"Cannot deliver: {have} of {req.episodes_requested} requested episodes are assigned "
                f"({req.episodes_requested - have} more needed)"
            )

    now = datetime.now(timezone.utc)
    db.add(
        RequestStatusHistory(
            request_id=req.id, from_status=req.status, to_status=to, actor_id=actor.id, comment=comment, at=now
        )
    )
    req.status = to
    req.updated_at = now
    db.commit()
    return req
