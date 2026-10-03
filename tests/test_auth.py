"""Authentication and role-based authorization, enforced by the server."""
import pytest

STAFF_ENDPOINTS = [
    ("get", "/api/episodes"),
    ("get", "/api/episodes/task-names"),
    ("get", "/api/analytics"),
]


@pytest.mark.parametrize("method,path", [("get", "/api/auth/me"), ("get", "/api/requests"), ("post", "/api/requests"),
                                         ("get", "/api/users"), ("post", "/api/imports/episodes")] + STAFF_ENDPOINTS)
def test_every_endpoint_requires_login(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_login_ok_and_wrong_password(client, make_user):
    user = make_user("client")
    assert client.post("/api/auth/login", json={"email": user.email, "password": "password123"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": user.email, "password": "nope"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "x"}).status_code == 401


def test_passwords_are_hashed_not_stored(make_user):
    from app.db import SessionLocal
    from app.models import User

    make_user("client", email="h@example.com", password="plain-secret-1")
    with SessionLocal() as db:
        stored = db.query(User).filter_by(email="h@example.com").one().password_hash
    assert "plain-secret-1" not in stored and stored.startswith("$argon2")


def test_deactivated_user_cannot_login_and_old_token_stops_working(client, make_user, auth):
    admin = make_user("admin")
    victim = make_user("client")
    victim_headers = auth(victim)
    assert client.get("/api/auth/me", headers=victim_headers).status_code == 200

    r = client.patch(f"/api/users/{victim.id}", json={"is_active": False}, headers=auth(admin))
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=victim_headers).status_code == 401  # existing token rejected at once
    assert client.post("/api/auth/login", json={"email": victim.email, "password": "password123"}).status_code == 401


def test_tampered_token_is_rejected(client, make_user, auth):
    headers = auth(make_user("client"))
    bad = {"Authorization": headers["Authorization"][:-3] + "abc"}
    assert client.get("/api/auth/me", headers=bad).status_code == 401


@pytest.mark.parametrize("method,path", STAFF_ENDPOINTS)
def test_client_cannot_use_staff_endpoints(client, make_user, auth, method, path):
    assert getattr(client, method)(path, headers=auth(make_user("client"))).status_code == 403


def test_client_cannot_import(client, make_user, auth):
    r = client.post("/api/imports/episodes", headers=auth(make_user("client")), files={"file": ("x.csv", b"a,b\n")})
    assert r.status_code == 403


def test_operator_cannot_manage_users_but_admin_can(client, make_user, auth):
    op, admin = make_user("operator"), make_user("admin")
    body = {"email": "new@example.com", "name": "New", "password": "password123", "role": "operator"}
    assert client.get("/api/users", headers=auth(op)).status_code == 403
    assert client.post("/api/users", json=body, headers=auth(op)).status_code == 403
    assert client.post("/api/users", json=body, headers=auth(admin)).status_code == 201
    assert client.post("/api/users", json=body, headers=auth(admin)).status_code == 409  # duplicate email


def test_admin_can_change_roles_but_not_their_own(client, make_user, auth):
    admin, other = make_user("admin"), make_user("client")
    h = auth(admin)
    assert client.patch(f"/api/users/{other.id}", json={"role": "operator"}, headers=h).json()["role"] == "operator"
    assert client.patch(f"/api/users/{admin.id}", json={"role": "client"}, headers=h).status_code == 409
    assert client.patch(f"/api/users/{admin.id}", json={"is_active": False}, headers=h).status_code == 409


def test_client_sees_only_their_own_requests(client, make_user, auth, new_request):
    a, b = make_user("client"), make_user("client")
    mine, theirs = new_request(a), new_request(b)
    listed = [r["id"] for r in client.get("/api/requests", headers=auth(a)).json()]
    assert listed == [mine]
    assert client.get(f"/api/requests/{mine}", headers=auth(a)).status_code == 200
    # Someone else's request looks exactly like a request that does not exist.
    assert client.get(f"/api/requests/{theirs}", headers=auth(a)).status_code == 404
    assert client.get(f"/api/requests/{theirs}/episodes", headers=auth(a)).status_code == 404
    staff = auth(make_user("operator"))
    assert len(client.get("/api/requests", headers=staff).json()) == 2


def test_only_clients_create_requests(client, make_user, auth, future_deadline):
    body = {"task_name": "pick cup", "episodes_requested": 3, "deadline": future_deadline}
    assert client.post("/api/requests", json=body, headers=auth(make_user("operator"))).status_code == 403
    assert client.post("/api/requests", json=body, headers=auth(make_user("admin"))).status_code == 403
    assert client.post("/api/requests", json=body, headers=auth(make_user("client"))).status_code == 201


def test_request_input_validation(client, make_user, auth, future_deadline):
    h = auth(make_user("client"))
    ok = {"task_name": "pick cup", "episodes_requested": 3, "deadline": future_deadline}
    assert client.post("/api/requests", json={**ok, "episodes_requested": 0}, headers=h).status_code == 422
    assert client.post("/api/requests", json={**ok, "task_name": "   "}, headers=h).status_code == 422
    assert client.post("/api/requests", json={**ok, "deadline": "2020-01-01"}, headers=h).status_code == 422
    r = client.post("/api/requests", json={**ok, "task_name": "  Pick   CUP "}, headers=h)
    assert r.json()["task_name"] == "pick cup"  # normalised like imported episodes
