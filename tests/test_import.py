"""CSV import: normalisation, rejection reasons, conflicts, and above all idempotency."""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Episode
from app.services.importer import import_csv

HEADER = "episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality\n"
NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)
SEED = Path(__file__).resolve().parent.parent / "seed" / "episodes.csv"


def run(csv_text: str):
    with SessionLocal() as db:
        return import_csv(db, HEADER + csv_text, now=NOW)


def count() -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(Episode))


def get(eid: str) -> Episode:
    with SessionLocal() as db:
        return db.scalar(select(Episode).where(Episode.episode_id == eid))


def reasons(rep):
    return {i["episode_id"]: i["reason"] for i in rep["issues"] if i["outcome"] == "rejected"}


def test_import_is_idempotent_on_the_real_messy_file():
    text = SEED.read_text(encoding="utf-8-sig")
    with SessionLocal() as db:
        first = import_csv(db, text, now=NOW)
    n = count()
    assert first["imported"] == n == 172
    with SessionLocal() as db:
        second = import_csv(db, text, now=NOW)
    assert second["imported"] == 0 and second["already_imported"] == 172
    assert count() == n  # no duplicates created
    # And once more, for luck: stable counts.
    with SessionLocal() as db:
        assert import_csv(db, text, now=NOW)["imported"] == 0
    assert count() == n


def test_report_accounts_for_every_row():
    with SessionLocal() as db:
        rep = import_csv(db, SEED.read_text(encoding="utf-8-sig"), now=NOW)
    accounted = rep["imported"] + rep["already_imported"] + rep["duplicates_in_file"] + rep["conflicts"] + rep["rejected"]
    assert accounted == rep["total_rows"] == 189
    assert rep["rejected"] == 13 and rep["duplicates_in_file"] == 2 and rep["conflicts"] == 2


def test_normalises_whitespace_case_and_date_formats():
    rep = run(
        "ep-00001, arm-01 ,  Pick   CUP ,14/08/2026 09:15,34,Kevin,GOOD\n"
        "EP-00002,arm-02,pick cup,2026-08-14 09:12:00,10,Eric,Usable\n"
        "EP-00003,arm-03,pick cup,2026-08-14T09:20:00Z,11,Diane,good\n"
    )
    assert rep["imported"] == 3 and rep["rejected"] == 0
    e1 = get("EP-00001")
    assert (e1.robot_id, e1.task_name, e1.quality) == ("arm-01", "pick cup", "good")
    assert e1.recorded_at == datetime(2026, 8, 14, 9, 15, tzinfo=timezone.utc)  # day-first, treated as UTC
    assert get("EP-00002").quality == "usable"


def test_each_kind_of_bad_row_is_rejected_with_a_reason():
    rep = run(
        ",arm-01,pick cup,2026-08-01T10:00:00,30,Kevin,good\n"
        "EP-00010,arm-99,pick cup,2026-08-01T10:00:00,30,Kevin,good\n"
        "EP-00011,,pick cup,2026-08-01T10:00:00,30,Kevin,good\n"
        "EP-00012,arm-01,pick cup,not a date,30,Kevin,good\n"
        "EP-00013,arm-01,pick cup,2031-01-01T00:00:00,30,Kevin,good\n"
        "EP-00014,arm-01,pick cup,2026-08-01T10:00:00,-5,Kevin,good\n"
        "EP-00015,arm-01,pick cup,2026-08-01T10:00:00,N/A,Kevin,good\n"
        "EP-00016,arm-01,pick cup,2026-08-01T10:00:00,45.5,Kevin,good\n"
        "EP-00017,arm-01,pick cup,2026-08-01T10:00:00,999999,Kevin,good\n"
        "EP-00018,arm-01,pick cup,2026-08-01T10:00:00,30,Kevin,excellent\n"
        "EP-00019,arm-01,pick cup,2026-08-01T10:00:00,30,Kevin,\n"
        "EP-00020,arm-01,pick cup,2026-08-01T10:00:00\n"
    )
    assert rep["rejected"] == 12 and rep["imported"] == 0 and count() == 0
    r = reasons(rep)
    assert "unknown robot" in r["EP-00010"] and "missing" in r["EP-00011"]
    assert "not a recognised date" in r["EP-00012"] and "future" in r["EP-00013"]
    assert "positive" in r["EP-00014"] and "whole number" in r["EP-00015"] and "whole number" in r["EP-00016"]
    assert "maximum" in r["EP-00017"] and "excellent" in r["EP-00018"] and "quality is missing" in r["EP-00019"]
    assert "malformed" in r["EP-00020"]
    assert all(i["line"] >= 2 for i in rep["issues"])  # every issue says which line to look at


def test_missing_operator_is_imported_with_a_warning():
    rep = run("EP-00030,mobile-01,pour water,2026-08-22T09:15:00,30,,usable\n")
    assert rep["imported"] == 1 and rep["imported_with_warnings"] == 1
    assert get("EP-00030").operator_name is None


def test_quoted_comma_in_a_field_is_handled_by_a_real_csv_parser():
    rep = run('EP-00040,arm-03,"pick cup, then place",2026-08-21T11:00:00,40,Eric,good\n')
    assert rep["imported"] == 1 and get("EP-00040").task_name == "pick cup, then place"


def test_identical_duplicate_rows_are_skipped_conflicting_ones_are_reported_first_wins():
    rep = run(
        "EP-00050,arm-01,pick cup,2026-08-01T10:00:00,30,Kevin,good\n"
        "EP-00050,arm-01,pick cup,2026-08-01T10:00:00,30,Kevin,good\n"      # identical
        "EP-00051,arm-01,pick cup,2026-08-01T10:00:00,30,Kevin,bad\n"
        "EP-00051,arm-01,pick cup,2026-08-01T10:00:00,30,Kevin,good\n"      # same id, different quality
        "ep-00050,arm-02,pick cup,2026-08-01T10:00:00,30,Kevin,good\n"      # same id (case-insensitive), different robot
    )
    assert (rep["imported"], rep["duplicates_in_file"], rep["conflicts"]) == (2, 1, 2)
    assert get("EP-00051").quality == "bad"  # first occurrence wins; we never guess


def test_import_never_overwrites_existing_data():
    run("EP-00060,arm-01,pick cup,2026-08-01T10:00:00,30,Kevin,good\n")
    rep = run("EP-00060,arm-01,pick cup,2026-08-01T10:00:00,99,Kevin,good\n")  # same id, different duration
    assert rep["imported"] == 0 and rep["conflicts"] == 1
    assert get("EP-00060").duration_seconds == 30


def test_wrong_header_is_a_clear_error_not_a_crash(client, make_user, auth):
    h = auth(make_user("operator"))
    r = client.post("/api/imports/episodes", headers=h, files={"file": ("x.csv", b"id,robot\n1,arm-01\n")})
    assert r.status_code == 422 and "header" in r.json()["detail"].lower()
    r = client.post("/api/imports/episodes", headers=h, files={"file": ("x.csv", b"")})
    assert r.status_code == 422


def test_upload_endpoint_returns_the_report_and_is_idempotent(client, make_user, auth):
    h = auth(make_user("operator"))
    body = SEED.read_bytes()
    r1 = client.post("/api/imports/episodes", headers=h, files={"file": ("episodes.csv", body)})
    assert r1.status_code == 200 and r1.json()["imported"] > 0 and r1.json()["rejected"] > 0
    r2 = client.post("/api/imports/episodes", headers=h, files={"file": ("episodes.csv", body)})
    assert r2.json()["imported"] == 0 and r2.json()["already_imported"] == r1.json()["imported"]


def test_non_utf8_upload_is_rejected(client, make_user, auth):
    h = auth(make_user("operator"))
    r = client.post("/api/imports/episodes", headers=h, files={"file": ("x.csv", b"\xff\xfe\x00bad")})
    assert r.status_code == 422
