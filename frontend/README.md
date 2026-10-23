# RESQNET Frontend (React + Vite + TS) — black + dark-navy mission control
1. `cp .env.example .env`, set `VITE_API_KEY` (and `VITE_API_KEY_HEADER` if needed).
2. Start the backend (`uvicorn app.main:app --reload` on :8000).
3. `npm install && npm run dev` -> http://localhost:5173 (dev proxy forwards /api).

Windows: Home · Mission Control (Image-1 layout, 3D satellite map) · Scenarios · Experiments · Analytics · Settings.

Backend-derived: scenarios, grid, drones, tasks, coverage, candidates. Derived client-side from real states: events, alerts, handoffs, ownership conflicts, duplicate count, safety violations (drone in restricted/blocked cell), recovery time.
Not provided by backend yet (shown honestly): battery (estimated from distance flown, marked `*`), POST /failures (real reply/error is displayed), communication_overhead. Optional fields are used automatically if added: drone.battery, drone.connected, run.metrics.*.
