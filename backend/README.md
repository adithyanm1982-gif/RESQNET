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

## Google sign-in

Google sign-in is optional. With `GOOGLE_CLIENT_ID` unset, the simulation UI
continues in guest mode. To enable it, create a Google OAuth client of type
**Web application** and add each frontend URL under **Authorized JavaScript
origins** (for local development, `http://localhost:5173` and
`http://127.0.0.1:5173`; for deployment, the exact HTTPS frontend origin).
This Google Identity Services button returns an ID-token credential to the
frontend callback, so no OAuth redirect URI is used.

Set the following in `backend/.env` (copy the non-secret defaults from
`.env.example`; never commit `.env`):

- `GOOGLE_CLIENT_ID`: the web client ID. This public identifier is served to
  the configured frontend; the backend uses the same value as the only
  accepted token audience.
- `CORS_ORIGINS`: comma-separated, exact frontend origins. Keep the deployed
  origin and add local origins only for development.
- `AUTH_COOKIE_SECURE=false` and `AUTH_COOKIE_SAMESITE=lax` for local HTTP.
  For HTTPS deployments use `AUTH_COOKIE_SECURE=true` and
  `AUTH_COOKIE_SAMESITE=none` when the frontend and API are on different sites.
  The cross-site cookie requires `Secure`; browser third-party-cookie policies
  may still block it, so a same-origin `/api` proxy is preferred for production.

The API contract is `GET /api/auth/config`, `GET /api/auth/nonce`,
`POST /api/auth/google` with `{"credential":"<Google ID token>"}`,
`GET /api/auth/me`, and `POST /api/auth/logout`. The short-lived nonce is
bound to an HTTP-only cookie and must match the signed ID token, preventing
login CSRF and credential replay. A successful sign-in creates an eight-hour,
HTTP-only session cookie. The session is held in process memory and is revoked
on logout; restarting the backend clears all sessions. Google credentials are
verified server-side with `google-auth`. The UI routes require a session only
when authentication is configured. Health, dataset, and simulation routes
remain public for the current demo. Requests that create or revoke sessions
must come from a configured `CORS_ORIGINS` origin.

With credentials configured, visit `/login`, sign in with a Google account,
open the profile menu to confirm the verified identity, and select **Sign
out**. Without `GOOGLE_CLIENT_ID`, `/login` explains that Google sign-in is
disabled and the app remains in guest mode. Invalid credentials produce a
generic sign-in error; missing server-side `google-auth` produces a service
unavailable response rather than accepting the token.

Backend auth tests mock Google's verifier and need no Google account. Run the
full suite with `python -m pytest` from `backend`.

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

## Railway demo deployment

Create a Railway service from the `backend` branch with the repository root as
the service root so the scenario JSON files remain available. Set the build
command to `pip install -r backend/requirements.txt` and the start command to
`cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Set
`RESQNET_DEMO_MODE=true` and `CORS_ORIGINS=https://resqnet-eight-psi.vercel.app`
in the service variables. Add `DATABASE_URL` only when a real database is
configured; demo mode provides a local SQLite health-check database otherwise.
A configured `DATABASE_URL` takes precedence and preserves normal database
behavior. Simulation runs remain in process memory and can be lost when the
service restarts or is redeployed.

## Troubleshooting

- Confirm the `postgresql-x64-18` Windows service is running.
- Confirm `resqnet_db` and `resqnet_user` exist and the role can connect to that
  database on `127.0.0.1:5432`.
- Check that the password in `.env` is URL-encoded, and that the URL has the
  expected driver, host, port, database, and role.
- The API intentionally does not return connection details or credentials.
  Verify the local `.env` privately and check PostgreSQL availability without
  posting credentials in logs or chat.
