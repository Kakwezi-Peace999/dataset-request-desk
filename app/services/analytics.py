"""Analytics. Every number is computed inside PostgreSQL; Python only shapes the result."""
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import Date, cast, func, select, text
from sqlalchemy.orm import Session

from ..domain import STATUSES
from ..models import Episode, Request


def _bounds(start: date | None, end: date | None):
    """Inclusive date range -> [start 00:00 UTC, end+1day 00:00 UTC). None means unbounded."""
    lo = datetime.combine(start, time.min, tzinfo=timezone.utc) if start else None
    hi = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc) if end else None
    return lo, hi


MEDIAN_SQL = text(
    """
    WITH submitted AS (
        SELECT request_id, MIN(at) AS at FROM request_status_history WHERE to_status = 'submitted' GROUP BY request_id
    ), delivered AS (
        SELECT request_id, MIN(at) AS at FROM request_status_history WHERE to_status = 'delivered' GROUP BY request_id
    )
    SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (d.at - s.at))) AS median_seconds,
           COUNT(*) AS sample_size
    FROM submitted s JOIN delivered d USING (request_id)
    WHERE (CAST(:lo AS timestamptz) IS NULL OR s.at >= :lo)
      AND (CAST(:hi AS timestamptz) IS NULL OR s.at <  :hi)
    """
)


def build_report(db: Session, start: date | None, end: date | None) -> dict:
    lo, hi = _bounds(start, end)

    def in_range(col):
        conds = []
        if lo is not None:
            conds.append(col >= lo)
        if hi is not None:
            conds.append(col < hi)
        return conds

    # 1) episodes recorded per day, per robot (day boundaries are in UTC)
    day = cast(func.timezone("UTC", Episode.recorded_at), Date).label("day")
    per_day = db.execute(
        select(day, Episode.robot_id, func.count().label("n"))
        .where(*in_range(Episode.recorded_at))
        .group_by(day, Episode.robot_id)
        .order_by(day, Episode.robot_id)
    ).all()

    # 2) requests by status (requests *submitted* inside the range) + median submitted -> delivered
    by_status = dict(
        db.execute(
            select(Request.status, func.count()).where(*in_range(Request.created_at)).group_by(Request.status)
        ).all()
    )
    median_row = db.execute(MEDIAN_SQL, {"lo": lo, "hi": hi}).one()

    # 3) top 5 task names by number of good episodes
    top = db.execute(
        select(Episode.task_name, func.count().label("n"))
        .where(Episode.quality == "good", *in_range(Episode.recorded_at))
        .group_by(Episode.task_name)
        .order_by(func.count().desc(), Episode.task_name)
        .limit(5)
    ).all()

    return {
        "range": {"from": start.isoformat() if start else None, "to": end.isoformat() if end else None},
        "episodes_per_day_per_robot": [{"date": d.isoformat(), "robot_id": r, "count": n} for d, r, n in per_day],
        "requests": {
            "by_status": {s: by_status.get(s, 0) for s in STATUSES},
            "total": sum(by_status.values()),
            "median_seconds_submitted_to_delivered": float(median_row.median_seconds) if median_row.median_seconds is not None else None,
            "delivered_sample_size": median_row.sample_size,
        },
        "top_tasks_by_good_episodes": [{"task_name": t, "good_episodes": n} for t, n in top],
    }
