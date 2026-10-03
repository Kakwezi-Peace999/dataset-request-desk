"""Operability: health endpoint and one structured log line per request."""
import json
import logging


def access_records(caplog):
    return [r for r in caplog.records if r.name == "drd.access"]


def test_one_log_line_per_request_with_the_required_fields(client, make_user, auth, caplog):
    user = make_user("client")
    headers = auth(user)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="drd.access"):
        client.get("/api/auth/me", headers=headers)
    (rec,) = access_records(caplog)
    ctx = rec.ctx
    assert (ctx["method"], ctx["path"], ctx["status"]) == ("GET", "/api/auth/me", 200)
    assert ctx["user_id"] == user.id and ctx["duration_ms"] >= 0


def test_anonymous_and_failed_requests_are_logged_too(client, caplog):
    with caplog.at_level(logging.INFO, logger="drd.access"):
        client.get("/api/requests")
        client.get("/health")
    a, b = access_records(caplog)
    assert (a.ctx["status"], a.ctx["user_id"]) == (401, None)
    assert (b.ctx["path"], b.ctx["status"]) == ("/health", 200)


def test_log_lines_are_valid_json():
    from app.logging_conf import JsonFormatter

    rec = logging.LogRecord("drd.access", logging.INFO, __file__, 1, "request", None, None)
    rec.ctx = {"method": "GET", "status": 200}
    data = json.loads(JsonFormatter().format(rec))
    assert data["msg"] == "request" and data["status"] == 200 and "ts" in data


def test_unexpected_errors_return_clean_500_and_are_logged(client, monkeypatch, caplog, make_user, auth):
    headers = auth(make_user("operator"))
    import app.routers.analytics as mod

    monkeypatch.setattr(mod, "build_report", lambda *a, **k: 1 / 0)
    with caplog.at_level(logging.INFO):
        r = client.get("/api/analytics", headers=headers)
    assert r.status_code == 500 and r.json() == {"detail": "Internal server error"}  # no stack trace leaked
    assert any(rec.name == "drd.access" and rec.ctx["status"] == 500 for rec in caplog.records)


def test_migrations_match_the_models():
    """Fails if someone changes models.py without writing a migration."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.db import engine
    from app.models import Base

    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []
