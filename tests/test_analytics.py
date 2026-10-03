"""Analytics: computed in SQL, checked against numbers worked out by hand."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.db import SessionLocal


def seed_history(request_id, actor_id, submitted, delivered):
    with SessionLocal() as db:
        db.execute(text("DELETE FROM request_status_history WHERE request_id=:r"), {"r": request_id})
        db.execute(text("UPDATE requests SET created_at=:t WHERE id=:r"), {"t": submitted, "r": request_id})
        rows = [(request_id, None, "submitted", actor_id, submitted)]
        if delivered:
            rows.append((request_id, "in_progress", "delivered", actor_id, delivered))
        for r in rows:
            db.execute(text("INSERT INTO request_status_history (request_id, from_status, to_status, actor_id, at) "
                            "VALUES (:a,:b,:c,:d,:e)"), dict(zip("abcde", r)))
        db.commit()


def test_episodes_per_day_per_robot_and_top_tasks(client, make_user, auth, make_episodes):
    h = auth(make_user("operator"))
    make_episodes(2, "good", "pick cup", "arm-01", when="2026-09-01T10:00:00+00:00")
    make_episodes(1, "good", "pick cup", "arm-02", when="2026-09-01T23:59:00+00:00")
    make_episodes(1, "bad", "pick cup", "arm-01", when="2026-09-02T00:01:00+00:00")
    make_episodes(3, "good", "fold towel", "arm-01", when="2026-09-02T12:00:00+00:00")
    make_episodes(1, "usable", "wipe table", "arm-03", when="2026-09-05T12:00:00+00:00")
    make_episodes(5, "good", "pour water", "arm-03", when="2026-10-20T12:00:00+00:00")  # outside the range

    r = client.get("/api/analytics?from=2026-09-01&to=2026-09-30", headers=h).json()
    got = {(e["date"], e["robot_id"]): e["count"] for e in r["episodes_per_day_per_robot"]}
    assert got == {
        ("2026-09-01", "arm-01"): 2, ("2026-09-01", "arm-02"): 1,
        ("2026-09-02", "arm-01"): 4,   # 1 bad pick cup + 3 fold towel
        ("2026-09-05", "arm-03"): 1,
    }
    # only GOOD episodes count towards the ranking; 'wipe table' has none; october's data is excluded
    assert r["top_tasks_by_good_episodes"] == [
        {"task_name": "fold towel", "good_episodes": 3}, {"task_name": "pick cup", "good_episodes": 3},
    ]


def test_top_tasks_is_capped_at_five(client, make_user, auth, make_episodes):
    h = auth(make_user("operator"))
    for i, t in enumerate(["a", "b", "c", "d", "e", "f", "g"]):
        make_episodes(i + 1, "good", t)
    top = client.get("/api/analytics", headers=h).json()["top_tasks_by_good_episodes"]
    assert [t["task_name"] for t in top] == ["g", "f", "e", "d", "c"]


def test_status_counts_and_median_delivery_time(client, make_user, auth, new_request):
    c, op = make_user("client"), make_user("operator")
    h = auth(op)
    base = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)
    ids = [new_request(c) for _ in range(4)]
    seed_history(ids[0], op.id, base, base + timedelta(hours=1))        # 1h
    seed_history(ids[1], op.id, base, base + timedelta(hours=3))        # 3h
    seed_history(ids[2], op.id, base, base + timedelta(hours=10))       # 10h  -> median of (1,3,10) = 3h
    seed_history(ids[3], op.id, base, None)                              # never delivered: excluded from the median
    with SessionLocal() as db:
        db.execute(text("UPDATE requests SET status='delivered' WHERE id = ANY(:ids)"), {"ids": ids[:3]})
        db.commit()

    r = client.get("/api/analytics?from=2026-09-10&to=2026-09-10", headers=h).json()["requests"]
    assert r["by_status"]["delivered"] == 3 and r["by_status"]["submitted"] == 1 and r["total"] == 4
    assert r["median_seconds_submitted_to_delivered"] == 3 * 3600 and r["delivered_sample_size"] == 3

    # a range that contains none of them
    empty = client.get("/api/analytics?from=2026-01-01&to=2026-01-31", headers=h).json()["requests"]
    assert empty["total"] == 0 and empty["median_seconds_submitted_to_delivered"] is None


def test_median_of_an_even_number_averages_the_middle_two(client, make_user, auth, new_request):
    c, op = make_user("client"), make_user("operator")
    base = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)
    for hours in (1, 2, 4, 9):
        rid = new_request(c)
        seed_history(rid, op.id, base, base + timedelta(hours=hours))
    r = client.get("/api/analytics", headers=auth(op)).json()["requests"]
    assert r["median_seconds_submitted_to_delivered"] == 3 * 3600  # (2h + 4h) / 2


def test_range_validation(client, make_user, auth):
    h = auth(make_user("operator"))
    assert client.get("/api/analytics?from=2026-09-30&to=2026-09-01", headers=h).status_code == 422
    assert client.get("/api/analytics?from=not-a-date", headers=h).status_code == 422
