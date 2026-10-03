# Dataset Request Desk

Internal platform for a robotics data-collection company: clients request datasets, operators fulfil
them by assigning episodes, clients accept or reject the delivery. Replaces the spreadsheet.

**Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic migrations, PostgreSQL 16, argon2 + JWT auth,
a small no-build web UI (vanilla JS) served by the API. Tests run against a real PostgreSQL.

## Run it (one command)

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
docker compose up --build
```

This starts PostgreSQL, applies the migrations, creates the seed users, imports `seed/episodes.csv`
(idempotent) and serves the app. Then open **http://localhost:8000** (API docs: http://localhost:8000/docs,
health check: http://localhost:8000/health).

Stop with `Ctrl+C`. `docker compose down -v` also deletes the database.

### Seed accounts

| Role | Email | Password |
|---|---|---|
| admin | admin@example.com | admin123 |
| operator | ops1@example.com | ops123 |
| operator | ops2@example.com | ops123 |
| client (Acme Robotics) | client-a@example.com | client123 |
| client (Beta Labs) | client-b@example.com | client123 |

Passwords are stored only as argon2id hashes (see `seed/users.json` for the source of the demo data).
Set a real secret outside local development: `SECRET_KEY=<long random string> docker compose up`.

## Run the tests (one command)

```bash
docker compose run --rm api pytest
```

67 tests, about 6 seconds. They create a separate `drd_test` database, build it with the **real migrations**,
and cover what matters most:

| File | What it proves |
|---|---|
| `tests/test_auth.py` | login required everywhere; role checks on the server; clients only see their own requests; deactivated users are cut off immediately; passwords are hashed |
| `tests/test_transitions.py` | only valid transitions, only by the owning role; delivery gate; rework loop; audit history with actor and time |
| `tests/test_assignments.py` | only good/usable; one request per episode (service rule *and* DB constraint); all-or-nothing; in_progress only |
| `tests/test_import.py` | idempotency on the real messy file; every bad-row category rejected with a reason; conflicts never overwrite |
| `tests/test_analytics.py` | per-day-per-robot, status counts, median (odd and even), top-5 good, date ranges, checked against hand-computed numbers |
| `tests/test_ops.py` | `/health`, one structured log line per request, clean 500s, migrations match the models |

Without Docker: start a local PostgreSQL, `pip install -r requirements-dev.txt`, set `DATABASE_URL`, run `pytest`.
CI (`.github/workflows/ci.yml`) runs the same suite on every push.

## Using the app

* **Client:** sign in, create a request, watch its status, accept or reject a delivered request.
* **Operator / admin:** see all requests, start work, assign episodes (filter by task and quality), mark delivered,
  import a CSV, view analytics. **Admin** also manages users (create, change role, deactivate).

Import from the command line (same code as the upload endpoint):

```bash
docker compose run --rm api python -m app.cli import-episodes seed/episodes.csv
```

Load test with a large clean file (the import took about 22 s for 200,000 rows on my machine, and a repeat run
creates nothing new):

```bash
python3 seed/generate_episodes.py 200000 > episodes_large.csv
docker compose run --rm -v "$PWD:/data" api python -m app.cli import-episodes /data/episodes_large.csv
```

## API summary

All routes except `/health` and `POST /api/auth/login` need `Authorization: Bearer <token>`.

| Route | Who |
|---|---|
| `POST /api/auth/login`, `GET /api/auth/me` | anyone / any user |
| `GET/POST /api/users`, `PATCH /api/users/{id}` | admin |
| `POST /api/requests` | client |
| `GET /api/requests`, `GET /api/requests/{id}` | client (own only) / staff (all) |
| `POST /api/requests/{id}/transition` | role depends on the step (see NOTES.md) |
| `GET /api/requests/{id}/episodes` | owner client / staff |
| `POST /api/requests/{id}/assignments`, `DELETE .../{episode_id}` | staff |
| `GET /api/episodes`, `GET /api/episodes/task-names`, `POST /api/imports/episodes` | staff |
| `GET /api/analytics?from=YYYY-MM-DD&to=YYYY-MM-DD` | staff |
| `GET /health` | public |

Errors are JSON `{"detail": ...}`: 401 not signed in, 403 role not allowed, 404 not found (also used for other
clients' requests), 409 rule violated (invalid transition, assignment rule), 422 invalid input.

## Analytics and 5 million episodes

All three analytics are single SQL statements (`GROUP BY`, `percentile_cont`); nothing is loaded into Python.
Measured on 200,000 episodes (local PostgreSQL 16): a one-month range takes about 15 ms in the database
(`ix_episodes_recorded_at` bitmap index scan), a full-year or all-time range about 200 ms (it has to aggregate
every row).

Extrapolating to 5 million episodes (25x): narrow ranges stay fast because the date filter uses the index and the
work is proportional to rows *in the range*; wide ranges grow roughly linearly, so expect seconds. What I would do:

1. Keep the existing indexes (`recorded_at`, `(robot_id, recorded_at)`, `(task_name, quality)`).
2. Add a daily roll-up table (`day, robot_id, task_name, quality, count`) maintained at import time, or a
   materialized view refreshed after imports, so dashboards read thousands of rows instead of millions.
3. Partition `episodes` by month on `recorded_at` so old partitions are never touched by recent-range queries.
4. Request-side analytics (status counts, median delivery time) are bounded by the number of *requests*, not
   episodes, and stay cheap.

## Project layout

```
app/                 main.py (app + logging middleware), deps.py (auth), models.py, domain.py (state machine)
  routers/           HTTP layer, thin
  services/          workflow.py, assignments.py, importer.py, analytics.py: the business rules
  static/            the web UI
alembic/             migrations (0001 = full schema + the five known robots)
seed/                provided sample data + generator
tests/               pytest suite
NOTES.md             design decisions, trade-offs, security, scale
```

Stretch item: **none chosen** (time budget spent on correctness, tests and notes).
