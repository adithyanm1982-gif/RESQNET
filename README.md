# RESQNET — fully local (backend + frontend on your laptop)

```
RESQNET/
  backend/                  FastAPI (patched: adds /api/datasets/* + local CORS)
  frontend/                 React + Vite (black theme, no API key)
  disaster_scenarios.json   ┐
  drone_config.json         ├ read by the BACKEND from this folder; the frontend gets them via the backend
  failure_scenarios.json    ┘
```

## 1. Backend (PowerShell, from `RESQNET\backend`)
```powershell
py -3.12 -m venv .venv ; .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }   # set DATABASE_URL as in backend\README.md
python -m uvicorn app.main:app --reload
```
Check: http://127.0.0.1:8000/api/simulations/scenarios and http://127.0.0.1:8000/api/datasets/drone-config

## 2. Frontend (second PowerShell, from `RESQNET\frontend`)
```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm install
npm run dev
```
Open http://localhost:5173 — the dev server proxies `/api` to the backend, so no CORS and **no API key**.
If PostgreSQL is stopped the header shows "API ONLINE · DB OFFLINE"; simulations still run (they are in memory).

## What the backend does NOT do yet (UI shows the truth)
- No failure-injection endpoint (POST /api/simulations/{id}/failures -> 404 is shown as-is).
- `mode` (centralized/decentralized/hybrid) is accepted but ignored, so the three modes currently give identical results.
- Drone battery is not in the run state; the UI models it from drone_config.json drain rates (marked `*`).
