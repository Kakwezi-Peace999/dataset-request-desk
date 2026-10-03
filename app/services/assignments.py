"""Assigning episodes to requests, with the business rules enforced in one place."""
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..domain import ASSIGNABLE_QUALITIES
from ..errors import Conflict, NotFound
from ..models import Assignment, Episode, User
from .workflow import lock_request


def assign_episodes(db: Session, request_id: int, actor: User, episode_ids: list[str]) -> int:
    req = lock_request(db, request_id)
    if req is None:
        raise NotFound("Request not found")
    if req.status != "in_progress":
        raise Conflict(f"Episodes can only be assigned while a request is 'in_progress' (it is '{req.status}')")

    wanted = list(dict.fromkeys(e.strip().upper() for e in episode_ids))  # dedupe, keep order
    found = {e.episode_id: e for e in db.scalars(select(Episode).where(Episode.episode_id.in_(wanted)))}
    taken = dict(
        db.execute(
            select(Episode.episode_id, Assignment.request_id)
            .join(Assignment, Assignment.episode_pk == Episode.id)
            .where(Episode.episode_id.in_(wanted))
        ).all()
    )

    problems = []
    for eid in wanted:
        ep = found.get(eid)
        if ep is None:
            problems.append({"episode_id": eid, "reason": "episode not found"})
        elif ep.quality not in ASSIGNABLE_QUALITIES:
            problems.append({"episode_id": eid, "reason": f"quality is '{ep.quality}'; only good or usable can be assigned"})
        elif eid in taken:
            where = "this request" if taken[eid] == req.id else f"request #{taken[eid]}"
            problems.append({"episode_id": eid, "reason": f"already assigned to {where}"})
    if problems:  # all-or-nothing: nothing is assigned if any episode is not allowed
        raise Conflict({"message": "Some episodes cannot be assigned; nothing was assigned", "problems": problems})

    try:
        db.add_all(Assignment(request_id=req.id, episode_pk=found[eid].id, assigned_by=actor.id) for eid in wanted)
        db.commit()
    except IntegrityError:
        # Someone else grabbed one of these episodes between our check and our insert.
        # The UNIQUE constraint on assignments.episode_pk is the real guarantee; we just report it nicely.
        db.rollback()
        raise Conflict("One of the episodes was just assigned to another request; please refresh and retry")
    return len(wanted)


def unassign_episode(db: Session, request_id: int, episode_id: str) -> None:
    req = lock_request(db, request_id)
    if req is None:
        raise NotFound("Request not found")
    if req.status != "in_progress":
        raise Conflict(f"Assignments can only change while a request is 'in_progress' (it is '{req.status}')")
    ep_pk = db.scalar(select(Episode.id).where(Episode.episode_id == episode_id.strip().upper()))
    result = db.execute(delete(Assignment).where(Assignment.request_id == req.id, Assignment.episode_pk == ep_pk))
    if result.rowcount == 0:
        db.rollback()
        raise NotFound("That episode is not assigned to this request")
    db.commit()
