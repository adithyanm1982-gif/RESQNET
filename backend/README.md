# RESQNET Backend

This is the initial FastAPI and PostgreSQL backend. It provides a database-backed
health endpoint and the initial scenario and simulation-run table definitions.
The initial deterministic, tick-based grid simulation uses the scenario and
drone configuration JSON files in the repository root.

## Windows PowerShell setup

Run these commands from the repository's `backend` directory:

```powershell
Set-Location C:\Users\acer\RESQNET\backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Set `DATABASE_URL` in `backend\.env` to:

```text
postgresql+psycopg://resqnet_user:URL_ENCODED_PASSWORD@127.0.0.1:5432/resqnet_db
```

Replace `URL_ENCODED_PASSWORD` locally with the URL-encoded password for the
existing PostgreSQL role. Do not share the password or commit `.env`.

## Initialize tables

From `backend` with the virtual environment activated:

```powershell
python -m app.database.init_db
```

This uses SQLAlchemy `create_all`, which creates missing tables and does not
drop, reset, or overwrite existing tables or data. Schema evolution and
Alembic migrations can be introduced in a later milestone.

## Run the API

```powershell
python -m uvicorn app.main:app --reload
```

In another PowerShell window, check the health endpoint and interactive docs:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Start-Process http://127.0.0.1:8000/docs
```

The health endpoint returns HTTP 200 when `SELECT 1` succeeds and HTTP 503 with
a generic database-disconnected status otherwise.

## Basic drone simulation

The simulation API uses the root `disaster_scenarios.json`,
`drone_config.json`, and `failure_scenarios.json` files. Runs are held in
memory for the lifetime of the API process and are not persisted to PostgreSQL.
Each run initializes the six configured drones for its selected scenario.
Movement is deterministic and four-directional; tasks are assigned by priority
to reachable idle drones, including multi-drone tasks. Blocked and restricted
cells cannot be entered or counted toward coverage. Candidate detections remain
unverified, and ground-truth fields are not returned.

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/simulations/scenarios
$run = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/simulations `
  -ContentType 'application/json' `
  -Body '{"scenario_id":"earthquake"}'
$run.run_id
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/simulations/$($run.run_id)/ticks" `
  -ContentType 'application/json' `
  -Body '{"ticks":10}'
Invoke-RestMethod "http://127.0.0.1:8000/api/simulations/$($run.run_id)"
```

Each tick advances an assigned drone by at most one traversable grid cell.
All six drones must occupy distinct cells at initialization and after every
tick. Movement intentions are calculated from the same pre-tick snapshot and
resolved together. Conflicting destinations, direct swaps, and movement cycles
are rejected; rotating drone priority makes equal conflicts deterministic
without always favoring the same drone. A drone can wait while another move is
resolved safely. If an idle drone blocks an active task's only current route
and a safe adjacent parking cell exists, it yields once to that cell and stays
there. The engine does not promise deadlock recovery when no safe yield cell or
collision-free move exists.

For tasks requiring multiple drones, the engine assigns each drone a distinct
reachable work cell at the target or an orthogonally adjacent traversable cell.
The task completes only when every assigned drone reaches its own work cell;
drones do not need to co-locate on the target. Completion releases all assigned
drones. A task with no statically reachable distinct work assignment, or an
active task whose current route is blocked, is reported with status `blocked`;
unassigned blocked tasks are retried on later ticks, and active blocked tasks
retain their assignments and reservations. Coverage is the percentage of
unique traversable cells visited so far, including initial drone positions.
This is a grid-simulation policy, not a claim of real-world collision safety.

## Tests

From `backend` with the virtual environment activated:

```powershell
python -m pytest
```

The health endpoint tests mock the database connectivity check. Model tests
inspect SQLAlchemy metadata; neither is a PostgreSQL integration test.

## Troubleshooting

- Confirm the `postgresql-x64-18` Windows service is running.
- Confirm `resqnet_db` and `resqnet_user` exist and the role can connect to that
  database on `127.0.0.1:5432`.
- Check that the password in `.env` is URL-encoded, and that the URL has the
  expected driver, host, port, database, and role.
- The API intentionally does not return connection details or credentials.
  Verify the local `.env` privately and check PostgreSQL availability without
  posting credentials in logs or chat.
