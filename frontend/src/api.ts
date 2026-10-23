const BASE_URL = import.meta.env.VITE_BACKEND_URL || '';

// Everything comes from the RESQNET backend. In dev, Vite can fall back to local proxy if VITE_BACKEND_URL is unset.
async function req(path: string, init?: RequestInit) {
  const r = await fetch(`${BASE_URL}${path}`, { ...init, headers: { 'Content-Type': 'application/json' } })
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
    try { const r = await fetch(`${BASE_URL}/api/health`, { signal: ctl.signal }); try { return await r.json() } catch { return { status: 'unhealthy' } } }
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