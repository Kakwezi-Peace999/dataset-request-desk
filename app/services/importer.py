"""CSV episode import: validate + normalise every row, never crash on bad data, report everything, safe to re-run.

Decisions (also documented in NOTES.md):
  * Normalise cheaply-fixable formatting (whitespace, case, date formats) instead of rejecting.
  * Reject rows whose *meaning* is missing or wrong (no id, unknown robot, invalid quality/date/duration).
  * Never guess between conflicting versions of the same episode: first one wins, the other is reported.
  * Existing database rows are never overwritten by an import.
"""
import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import String, any_, bindparam, select
from sqlalchemy.dialects.postgresql import ARRAY, insert as pg_insert
from sqlalchemy.orm import Session

from ..config import settings
from ..domain import QUALITIES
from ..errors import Invalid
from ..models import Episode, Robot

EXPECTED_HEADER = ["episode_id", "robot_id", "task_name", "recorded_at", "duration_seconds", "operator_name", "quality"]
LEGACY_DATE_FORMATS = ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y")  # day-first, as used in the export
EARLIEST = datetime(2020, 1, 1, tzinfo=timezone.utc)
ID_RE = re.compile(r"^EP-\d+$")
CHUNK = 2000
MAX_ISSUES_REPORTED = 1000


class RowError(Exception):
    pass


@dataclass
class Clean:
    episode_id: str
    robot_id: str
    task_name: str
    recorded_at: datetime
    duration_seconds: int
    operator_name: str | None
    quality: str

    def content(self) -> tuple:
        """Everything except the id, used to tell 'identical duplicate' from 'conflicting duplicate'."""
        return (self.robot_id, self.task_name, self.recorded_at, self.duration_seconds, self.operator_name, self.quality)


def _parse_datetime(raw: str, now: datetime) -> datetime:
    raw = raw.strip()
    if not raw:
        raise RowError("recorded_at is missing")
    dt = None
    try:
        dt = datetime.fromisoformat(raw)  # handles 2026-08-14T09:15:00, 2026-08-14 09:15:00 and ...Z
    except ValueError:
        for fmt in LEGACY_DATE_FORMATS:
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        raise RowError(f"recorded_at '{raw}' is not a recognised date")
    # Assumption: timestamps without a timezone are UTC. Aware timestamps are converted to UTC.
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    if dt > now + timedelta(minutes=5):
        raise RowError(f"recorded_at '{raw}' is in the future")
    if dt < EARLIEST:
        raise RowError(f"recorded_at '{raw}' is implausibly old")
    return dt


def _clean_row(row: list[str], robots: set[str], now: datetime) -> tuple[Clean, list[str]]:
    warnings: list[str] = []
    raw = dict(zip(EXPECTED_HEADER, row))

    episode_id = raw["episode_id"].strip().upper()
    if not episode_id:
        raise RowError("episode_id is missing")
    if not ID_RE.match(episode_id):
        raise RowError(f"episode_id '{raw['episode_id'].strip()}' is not in the form EP-<digits>")

    robot_id = raw["robot_id"].strip().lower()
    if not robot_id:
        raise RowError("robot_id is missing")
    if robot_id not in robots:
        raise RowError(f"unknown robot '{robot_id}'")

    task_name = re.sub(r"\s+", " ", raw["task_name"].strip()).lower()
    if not task_name:
        raise RowError("task_name is missing")
    if len(task_name) > 200:
        raise RowError("task_name is too long")

    recorded_at = _parse_datetime(raw["recorded_at"], now)

    dur = raw["duration_seconds"].strip()
    if not dur:
        raise RowError("duration_seconds is missing")
    if not re.fullmatch(r"-?\d+", dur):
        raise RowError(f"duration_seconds '{dur}' is not a whole number")
    duration = int(dur)
    if duration <= 0:
        raise RowError(f"duration_seconds {duration} must be positive")
    if duration > settings.max_duration_seconds:
        raise RowError(f"duration_seconds {duration} exceeds the maximum of {settings.max_duration_seconds}")

    operator = re.sub(r"\s+", " ", raw["operator_name"].strip()) or None
    if operator is None:
        warnings.append("operator_name is missing (imported with no operator)")

    quality = raw["quality"].strip().lower()
    if quality not in QUALITIES:
        raise RowError(f"quality '{raw['quality'].strip()}' is not one of good/usable/bad" if quality else "quality is missing")

    return Clean(episode_id, robot_id, task_name, recorded_at, duration, operator, quality), warnings


def import_csv(db: Session, text: str, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    robots = set(db.scalars(select(Robot.robot_id)))

    report = {
        "total_rows": 0, "imported": 0, "imported_with_warnings": 0, "already_imported": 0,
        "duplicates_in_file": 0, "conflicts": 0, "rejected": 0, "blank_lines": 0,
        "issues": [], "issues_truncated": False,
    }

    def issue(line: int, episode_id: str | None, outcome: str, reason: str) -> None:
        if len(report["issues"]) < MAX_ISSUES_REPORTED:
            report["issues"].append({"line": line, "episode_id": episode_id, "outcome": outcome, "reason": reason})
        else:
            report["issues_truncated"] = True

    reader = csv.reader(io.StringIO(text, newline=""))
    header = None
    first_seen: dict[str, tuple[int, Clean]] = {}
    candidates: list[tuple[int, Clean, list[str]]] = []

    for row in reader:
        line = reader.line_num
        if not row or all(not cell.strip() for cell in row):
            report["blank_lines"] += 1
            continue
        if header is None:
            header = [h.strip().lower().lstrip("\ufeff") for h in row]
            if header != EXPECTED_HEADER:
                raise Invalid(f"Unexpected CSV header. Expected: {','.join(EXPECTED_HEADER)}")
            continue

        report["total_rows"] += 1
        if len(row) != len(EXPECTED_HEADER):
            issue(line, row[0].strip() or None, "rejected", f"malformed row: expected {len(EXPECTED_HEADER)} fields, found {len(row)}")
            report["rejected"] += 1
            continue
        try:
            clean, warnings = _clean_row(row, robots, now)
        except RowError as exc:
            issue(line, row[0].strip() or None, "rejected", str(exc))
            report["rejected"] += 1
            continue

        earlier = first_seen.get(clean.episode_id)
        if earlier is not None:
            first_line, first_clean = earlier
            if first_clean.content() == clean.content():
                issue(line, clean.episode_id, "duplicate", f"identical to line {first_line}; skipped")
                report["duplicates_in_file"] += 1
            else:
                issue(line, clean.episode_id, "conflict", f"same episode_id as line {first_line} but different data; first occurrence kept, this row skipped")
                report["conflicts"] += 1
            continue
        first_seen[clean.episode_id] = (line, clean)
        candidates.append((line, clean, warnings))

    if header is None:
        raise Invalid("The file is empty or has no header row")

    # Compare against what is already in the database (in chunks, so a 200k-row file does not build a giant query).
    # Plain column tuples + a single array parameter (= ANY(:ids)) keep this fast: no ORM objects, one cached statement.
    lookup = (
        select(Episode.episode_id, Episode.robot_id, Episode.task_name, Episode.recorded_at,
               Episode.duration_seconds, Episode.operator_name, Episode.quality)
        .where(Episode.episode_id == any_(bindparam("ids", type_=ARRAY(String))))
    )
    to_insert: list[tuple[int, Clean, list[str]]] = []
    for i in range(0, len(candidates), CHUNK):
        chunk = candidates[i : i + CHUNK]
        existing = {row[0]: tuple(row[1:]) for row in db.execute(lookup, {"ids": [c.episode_id for _, c, _ in chunk]})}
        for line, clean, warnings in chunk:
            db_row = existing.get(clean.episode_id)
            if db_row is None:
                to_insert.append((line, clean, warnings))
            elif db_row == clean.content():
                report["already_imported"] += 1
            else:
                report["conflicts"] += 1
                issue(line, clean.episode_id, "conflict", "already exists in the database with different data; existing record kept")

    # Insert with ON CONFLICT DO NOTHING: if two imports race, the unique index still prevents duplicates.
    # Passing a list of dicts makes SQLAlchemy batch the rows (executemany) and compile the statement only once.
    insert_stmt = pg_insert(Episode).on_conflict_do_nothing(index_elements=["episode_id"]).returning(Episode.episode_id)
    for i in range(0, len(to_insert), CHUNK):
        chunk = to_insert[i : i + CHUNK]
        values = [
            dict(episode_id=c.episode_id, robot_id=c.robot_id, task_name=c.task_name, recorded_at=c.recorded_at,
                 duration_seconds=c.duration_seconds, operator_name=c.operator_name, quality=c.quality)
            for _, c, _ in chunk
        ]
        inserted = set(db.scalars(insert_stmt, values))
        for line, clean, warnings in chunk:
            if clean.episode_id not in inserted:
                report["already_imported"] += 1  # lost a race with a concurrent import of the same id
                continue
            report["imported"] += 1
            if warnings:
                report["imported_with_warnings"] += 1
                issue(line, clean.episode_id, "imported_with_warning", "; ".join(warnings))
    db.commit()
    report["issues"].sort(key=lambda x: x["line"])
    return report
