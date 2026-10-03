# NOTES

## 1. Design

**Data model** (PostgreSQL, all constraints enforced in the database as well as in code):

```
users ──< requests ──< request_status_history   (append-only audit: from, to, actor, comment, at)
              │
              └──< assignments >── episodes >── robots
                   UNIQUE(episode_pk)
```

* `users(role: client|operator|admin, is_active, argon2 hash)`; `robots` is reference data (the 5 known robots,
  inserted by the first migration); `episodes` has the business key `episode_id` (UNIQUE) plus CHECKs on
  quality and duration; `requests` carries the current `status`; `assignments` links one episode to one request.
* **Where state lives:** only in PostgreSQL. The API process keeps no state, so it can be restarted or scaled
  out freely. The JWT only says *who* the user is; role and active flag are re-read from the database on every
  request, so deactivating a user or changing a role takes effect immediately.
* The workflow table lives in one place (`app/domain.py`): `(from, to) -> roles allowed`. Everything else uses it.

**Hardest decisions**

1. *"An episode belongs to at most one request" under concurrency.* Checking in Python is not enough (two operators
   can both pass the check). The guarantee is `UNIQUE(assignments.episode_pk)`; the service also checks first so users
   get a readable per-episode reason, and it locks the request row (`SELECT ... FOR UPDATE`) so "count assignments"
   and "mark delivered" cannot interleave with "remove an assignment". If the constraint still fires, the user gets a
   409 asking them to retry. Assignment is all-or-nothing: if any episode in the batch is not allowed, nothing is assigned.
2. *Conflicting duplicates in the messy CSV* (e.g. EP-00011 is `bad` in one row and `good` in another; `ep-00003`
   collides with `EP-00003`). I did not want the import to guess, because quality decides what a client receives.
   Policy: IDs are normalised to upper case; identical repeats are skipped; different data for the same ID means
   **first occurrence wins and the other row is reported as a conflict**; an import never overwrites existing database
   rows. A human resolves conflicts from the report.
3. *404 vs 403.* A client asking for someone else's request gets 404, so request ids of other clients cannot be probed.
   A user who can see a request but whose role cannot perform a step gets 403; a step that is not valid for anyone
   from the current status gets 409. Order of checks: visibility, validity, role, business rule.

**Other ambiguities I decided (the brief left them open)**
* Only clients create requests. Episodes can be assigned or removed only while a request is `in_progress`
  (so a delivered set cannot change underneath the client); rework re-opens it. Assigning *more* than requested is allowed.
* Import cleaning: whitespace/case normalised; dates in ISO, space-separated, `Z`, or day-first `dd/mm/yyyy`; timestamps
  without a timezone are treated as **UTC**; future dates, non-numeric/negative/fractional/blank durations, and
  durations above 3600 s (configurable) are rejected; unknown or blank robots, invalid or blank quality, malformed rows
  are rejected; a missing operator is imported with a warning. Every outcome is reported with its line number.
* Analytics ranges are inclusive UTC days. Requests are counted by submission date. "Median time to deliver" uses
  the first time a request reached `delivered`; requests never delivered are excluded.

## 2. Left out / simplified, and the next two days

Left out: the stretch items, real-time updates, refresh tokens, password reset, login rate limiting, pagination
of the request list, background processing of big imports, frontend tests, deployment.

With two more days: (1) SSE so operators see new/changed requests live; (2) move imports to a background job with
progress (a 200k-row import is ~20 s inside a web request today); (3) `httpOnly` cookie sessions + CSP instead of a
token in `localStorage`; (4) login throttling and an audit log for user-admin actions; (5) browser tests for the UI;
(6) deploy with HTTPS and managed Postgres.

## 3. Something that went wrong

* **Import was slow at volume.** The first 200,000-row import took ~50 s. Instead of guessing, I profiled it
  (`cProfile`): about 40% of the time was SQLAlchemy *compiling* 100 huge multi-row `INSERT ... VALUES (...)`
  statements and large `IN (...)` lists, not PostgreSQL. Sending the rows as an `executemany` batch (statement compiled once)
  and looking up existing ids with a single `= ANY(array)` parameter cut it to ~22 s (re-runs 9 s -> 5 s). The idempotency test
  stayed green throughout, which is what let me change the internals safely.
* **Alembic could not import the app** (`ModuleNotFoundError: app`) the first time I generated the migration; fixed by
  `prepend_sys_path = .` in `alembic.ini`.
* * **Setting up Docker on Windows.** The first `docker compose up --build` failed because `pip` timed out while downloading packages on a slow connection (`ReadTimeoutError`). I read the build log, saw the failure was in the `pip install` step and not in the application code, added `--default-timeout=120 --retries 10` to the Dockerfile and re-ran the build, which then succeeded. Docker Desktop also needed `wsl --update` before its engine would start.


## 4. Security

* **Passwords:** argon2id hashes only (never stored or logged in clear); login returns the same 401 for unknown email,
  wrong password and deactivated account, and always performs a hash verification to keep timing similar.
* **Tokens:** signed JWT (HS256, 8 h) with the secret from `SECRET_KEY`; a warning is logged if the insecure default is used.
* **Authorization:** server-side dependencies (`require_roles`) on every route; client data access is filtered in the
  query itself; tests cover each role against each sensitive endpoint.
* **Input validation:** pydantic models (types, lengths, ranges), DB CHECK/UNIQUE/FK constraints, parameterised SQL only,
  CSV parsed by the `csv` module with size and encoding limits. The UI escapes all server data before inserting it into the page.
* **Two vulnerabilities I would worry about most:**
  1. *Token theft through XSS.* The token is in `localStorage`; any XSS would expose it. Mitigations today: strict output
     escaping; next: `httpOnly; SameSite` cookies, CSRF protection, and a Content-Security-Policy.
  2. *Broken access control as the system grows (IDOR).* Every new endpoint that takes a request id must remember to apply the
     ownership rule. I centralised it (`visible_to`, query-level filtering) and test it, but the long-term answer is
     PostgreSQL row-level security so a forgotten check cannot leak data. (Also unaddressed: no brute-force throttling on login.)

## 5. Scale

* **100x episodes (tens of millions):** first to break are the analytics scans over wide date ranges, the episode list
  (`COUNT(*)` plus `OFFSET` pagination), and web-request imports. Fixes: daily roll-up table or materialized view, monthly
  partitions on `recorded_at`, keyset pagination with approximate counts, and import via `COPY` into a staging table in a background job.
* **10x users:** the app is stateless, so run several workers/instances behind a load balancer and put PgBouncer in front of
  Postgres. Argon2 is deliberately CPU-heavy at login, so size CPU for login bursts. The unpaginated request list and the
  per-request lock on a hot request are the other early limits.

## 6. AI tooling

I used Claude (Anthropic) to generate the first version of the code and review the approach.
I ran the whole system on my own machine, tried each role's workflow in the browser (client creates a request, operator assigns episodes and delivers, client accepts, CSV re-import), and ran the test suite (67 passed). I read through the workflow rules, the import and the analytics queries so that I can explain and change them.
Verification was by running the tests, mutation checks (deliberately breaking a rule to confirm a test fails),a simulated-browser run through every role's workflow, and a 200k-row load test.
