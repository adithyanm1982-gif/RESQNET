// Everything comes from the local RESQNET backend (FastAPI on this laptop). In dev, Vite proxies /api -> backend,
// so no CORS setup, no API key and no remote server are needed.
async function req(path: string, init?: RequestInit) {
  const r = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json' } })
  let body: any = null
  try { body = await r.json() } catch { /* empty */ }
  if (!r.ok) throw new Error(`${r.status} ${typeof body?.detail === 'string' ? body.detail : r.statusText}`)
  return body
}
export const api = {
  // /api/health answers 503 when PostgreSQL is down but the API itself is fine: report that instead of throwing.
  // /api/health also pings PostgreSQL and can answer 503 (DB down) or hang. Never let that block the app: 5 s timeout.
  health: async () => {
    const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 5000)
    try { const r = await fetch('/api/health', { signal: ctl.signal }); try { return await r.json() } catch { return { status: 'unhealthy' } } }
    finally { clearTimeout(t) }
  },
  scenarios: () => req('/api/simulations/scenarios'),
  create: (scenario_id: string, mode?: string) => req('/api/simulations', { method: 'POST', body: JSON.stringify({ scenario_id, mode }) }),
  tick: (id: string, ticks = 1) => req(`/api/simulations/${id}/ticks`, { method: 'POST', body: JSON.stringify({ ticks }) }),
  state: (id: string) => req(`/api/simulations/${id}`),
  droneConfig: () => req('/api/datasets/drone-config'),
  failureScenarios: () => req('/api/datasets/failure-scenarios'),
  // Not implemented by the backend: its real response/error is surfaced in the UI, never faked.
  inject: (id: string, type: string, payload: any = {}) => req(`/api/simulations/${id}/failures`, { method: 'POST', body: JSON.stringify({ type, ...payload }) }),
}
