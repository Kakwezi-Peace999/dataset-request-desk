"""The request workflow: valid transitions only, by the right role only, with an audit trail."""
import pytest


def move(client, headers, rid, to, comment=None):
    return client.post(f"/api/requests/{rid}/transition", json={"to": to, "comment": comment}, headers=headers)


@pytest.fixture()
def world(client, make_user, auth, new_request, make_episodes):
    c, other = make_user("client"), make_user("client")
    op = make_user("operator")
    rid = new_request(c, count=2)
    eps = make_episodes(2, "good")
    return dict(client=c, other=other, op=op, rid=rid, eps=eps, h_client=auth(c), h_other=auth(other), h_op=auth(op))


def assign(client, w, ids=None):
    return client.post(f"/api/requests/{w['rid']}/assignments", json={"episode_ids": ids or w["eps"]}, headers=w["h_op"])


def test_new_request_starts_submitted_with_history(client, world):
    r = client.get(f"/api/requests/{world['rid']}", headers=world["h_client"]).json()
    assert r["status"] == "submitted"
    assert [(h["from_status"], h["to_status"]) for h in r["history"]] == [(None, "submitted")]


def test_full_happy_path_records_who_and_when(client, world):
    w = world
    assert move(client, w["h_op"], w["rid"], "in_progress").status_code == 200
    assert assign(client, w).status_code == 201
    assert move(client, w["h_op"], w["rid"], "delivered").status_code == 200
    assert move(client, w["h_client"], w["rid"], "accepted", "looks great").status_code == 200
    hist = client.get(f"/api/requests/{w['rid']}", headers=w["h_op"]).json()["history"]
    assert [h["to_status"] for h in hist] == ["submitted", "in_progress", "delivered", "accepted"]
    assert hist[1]["actor"] == w["op"].name and hist[3]["actor"] == w["client"].name
    assert hist[3]["comment"] == "looks great" and all(h["at"] for h in hist)


@pytest.mark.parametrize("path", [
    ["delivered"],                       # skip in_progress
    ["accepted"],                        # skip everything
    ["rejected"],
    ["submitted"],                       # cannot go back to the start
])
def test_invalid_transitions_from_submitted_are_409(client, world, path):
    assert move(client, world["h_op"], world["rid"], path[0]).status_code == 409


def test_cannot_go_backwards_or_repeat(client, world):
    w = world
    move(client, w["h_op"], w["rid"], "in_progress")
    assert move(client, w["h_op"], w["rid"], "in_progress").status_code == 409
    assert move(client, w["h_op"], w["rid"], "submitted").status_code == 409


def test_roles_own_their_steps(client, world):
    w = world
    # a client cannot start work, an operator cannot accept/reject on the client's behalf
    assert move(client, w["h_client"], w["rid"], "in_progress").status_code == 403
    move(client, w["h_op"], w["rid"], "in_progress")
    assign(client, w)
    assert move(client, w["h_client"], w["rid"], "delivered").status_code == 403
    move(client, w["h_op"], w["rid"], "delivered")
    assert move(client, w["h_op"], w["rid"], "accepted").status_code == 403
    assert move(client, w["h_op"], w["rid"], "rejected").status_code == 403


def test_another_client_cannot_accept_or_reject(client, world):
    w = world
    move(client, w["h_op"], w["rid"], "in_progress")
    assign(client, w)
    move(client, w["h_op"], w["rid"], "delivered")
    assert move(client, w["h_other"], w["rid"], "accepted").status_code == 404
    assert move(client, w["h_other"], w["rid"], "rejected").status_code == 404
    assert client.get(f"/api/requests/{w['rid']}", headers=w["h_client"]).json()["status"] == "delivered"


def test_cannot_deliver_without_enough_episodes(client, world, make_episodes):
    w = world
    move(client, w["h_op"], w["rid"], "in_progress")
    assert move(client, w["h_op"], w["rid"], "delivered").status_code == 409  # 0 of 2
    assign(client, w, w["eps"][:1])
    r = move(client, w["h_op"], w["rid"], "delivered")
    assert r.status_code == 409 and "1 of 2" in r.json()["detail"]
    assign(client, w, make_episodes(1, "usable"))
    assert move(client, w["h_op"], w["rid"], "delivered").status_code == 200


def test_rejection_leads_to_rework_and_second_delivery(client, world, make_episodes):
    w = world
    move(client, w["h_op"], w["rid"], "in_progress")
    assign(client, w)
    move(client, w["h_op"], w["rid"], "delivered")
    assert move(client, w["h_client"], w["rid"], "rejected", "wrong cups").status_code == 200
    assert move(client, w["h_client"], w["rid"], "accepted").status_code == 409  # rejected is not accepted-able
    assert move(client, w["h_op"], w["rid"], "in_progress").status_code == 200   # rework
    assign(client, w, make_episodes(1, "good"))                                    # may add more during rework
    assert move(client, w["h_op"], w["rid"], "delivered").status_code == 200
    assert move(client, w["h_client"], w["rid"], "accepted").status_code == 200


def test_accepted_is_final(client, world):
    w = world
    move(client, w["h_op"], w["rid"], "in_progress")
    assign(client, w)
    move(client, w["h_op"], w["rid"], "delivered")
    move(client, w["h_client"], w["rid"], "accepted")
    for who in ("h_op", "h_client"):
        for to in ("in_progress", "delivered", "rejected", "submitted"):
            assert move(client, w[who], w["rid"], to).status_code in (403, 409)


def test_unknown_status_value_is_rejected(client, world):
    assert move(client, world["h_op"], world["rid"], "teleported").status_code == 422


def test_allowed_transitions_are_exposed_per_role(client, world):
    w = world
    assert client.get(f"/api/requests/{w['rid']}", headers=w["h_op"]).json()["allowed_transitions"] == ["in_progress"]
    assert client.get(f"/api/requests/{w['rid']}", headers=w["h_client"]).json()["allowed_transitions"] == []
