"""Assignment rules: quality, one request per episode, in_progress only, all-or-nothing."""
import pytest
from sqlalchemy.exc import IntegrityError


@pytest.fixture()
def setup(client, make_user, auth, new_request):
    op = make_user("operator")
    h = auth(op)
    c1, c2 = make_user("client"), make_user("client")
    r1, r2 = new_request(c1, 3), new_request(c2, 3)
    for rid in (r1, r2):
        assert client.post(f"/api/requests/{rid}/transition", json={"to": "in_progress"}, headers=h).status_code == 200
    return dict(h=h, r1=r1, r2=r2, c1=c1, c2=c2)


def assign(client, w, rid, ids, who="h"):
    return client.post(f"/api/requests/{rid}/assignments", json={"episode_ids": ids}, headers=w[who])


def test_good_and_usable_can_be_assigned(client, setup, make_episodes):
    ids = make_episodes(1, "good") + make_episodes(1, "usable")
    r = assign(client, setup, setup["r1"], ids)
    assert r.status_code == 201 and r.json()["assigned_count"] == 2


def test_bad_episodes_cannot_be_assigned(client, setup, make_episodes):
    bad = make_episodes(1, "bad")
    r = assign(client, setup, setup["r1"], bad)
    assert r.status_code == 409
    assert "bad" in r.json()["detail"]["problems"][0]["reason"]


def test_an_episode_can_belong_to_only_one_request(client, setup, make_episodes):
    (ep,) = make_episodes(1, "good")
    assert assign(client, setup, setup["r1"], [ep]).status_code == 201
    r = assign(client, setup, setup["r2"], [ep])
    assert r.status_code == 409 and f"request #{setup['r1']}" in r.json()["detail"]["problems"][0]["reason"]
    assert assign(client, setup, setup["r1"], [ep]).status_code == 409  # not twice on the same request either


def test_database_itself_blocks_double_assignment(setup, make_episodes):
    """The service checks first, but the UNIQUE constraint is what makes this safe under concurrency."""
    from app.db import SessionLocal
    from app.models import Assignment, Episode
    from sqlalchemy import select

    (ep,) = make_episodes(1, "good")
    with SessionLocal() as db:
        pk = db.scalar(select(Episode.id).where(Episode.episode_id == ep))
        db.add(Assignment(request_id=setup["r1"], episode_pk=pk, assigned_by=1))
        db.commit()
        db.add(Assignment(request_id=setup["r2"], episode_pk=pk, assigned_by=1))
        with pytest.raises(IntegrityError):
            db.commit()


def test_all_or_nothing(client, setup, make_episodes):
    good = make_episodes(2, "good")
    bad = make_episodes(1, "bad")
    r = assign(client, setup, setup["r1"], good + bad + ["EP-NOPE"])
    assert r.status_code == 409 and len(r.json()["detail"]["problems"]) == 2
    assert client.get(f"/api/requests/{setup['r1']}", headers=setup["h"]).json()["assigned_count"] == 0


def test_only_staff_may_assign(client, setup, make_episodes, auth):
    (ep,) = make_episodes(1, "good")
    setup["hc"] = auth(setup["c1"])
    assert assign(client, setup, setup["r1"], [ep], who="hc").status_code == 403


def test_assign_only_while_in_progress(client, setup, make_episodes, new_request, make_user, auth):
    (ep,) = make_episodes(1, "good")
    fresh = new_request(make_user("client"), 1)  # still 'submitted'
    r = assign(client, setup, fresh, [ep])
    assert r.status_code == 409 and "in_progress" in r.json()["detail"]


def test_unassign_frees_the_episode(client, setup, make_episodes):
    (ep,) = make_episodes(1, "good")
    assign(client, setup, setup["r1"], [ep])
    assert client.delete(f"/api/requests/{setup['r1']}/assignments/{ep}", headers=setup["h"]).status_code == 200
    assert assign(client, setup, setup["r2"], [ep]).status_code == 201
    assert client.delete(f"/api/requests/{setup['r1']}/assignments/{ep}", headers=setup["h"]).status_code == 404


def test_cannot_change_assignments_after_delivery(client, setup, make_episodes, auth):
    eps = make_episodes(3, "good")
    assign(client, setup, setup["r1"], eps)
    client.post(f"/api/requests/{setup['r1']}/transition", json={"to": "delivered"}, headers=setup["h"])
    assert client.delete(f"/api/requests/{setup['r1']}/assignments/{eps[0]}", headers=setup["h"]).status_code == 409
    more = make_episodes(1, "good")
    assert assign(client, setup, setup["r1"], more).status_code == 409


def test_episode_list_filters(client, setup, make_episodes):
    make_episodes(2, "good", task="fold towel")
    make_episodes(1, "bad", task="fold towel")
    make_episodes(1, "good", task="pick cup")
    h = setup["h"]
    assert client.get("/api/episodes?task_name=fold towel", headers=h).json()["total"] == 3
    assert client.get("/api/episodes?task_name=fold towel&quality=good", headers=h).json()["total"] == 2
    assert client.get("/api/episodes?quality=nonsense", headers=h).status_code == 422
    first = client.get("/api/episodes?quality=good&task_name=pick cup", headers=h).json()["items"][0]["episode_id"]
    assign(client, setup, setup["r1"], [first])
    assert client.get("/api/episodes?task_name=pick cup&unassigned_only=true", headers=h).json()["total"] == 0
