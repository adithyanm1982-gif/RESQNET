// Shared helpers. Everything here is derived from the backend's run state — nothing is invented.
export const rowsOf = (g: any): string[] => (g?.cells || []).map((r: any) => (typeof r === 'string' ? r : r.join('')))
export const dname = (id: string) => { const m = /^D(\d+)$/i.exec(id || ''); return m ? `DRONE ${m[1].padStart(2, '0')}` : String(id || '').toUpperCase() }
export const mmss = (s: number) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`
export const dl = (name: string, text: string, type: string) => { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([text], { type })); a.download = name; a.click() }
const cc = (v: any) => { const s = String(v ?? ''); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s }
export const toCsv = (rows: any[][]) => rows.map((r) => r.map(cc).join(',')).join('\n')

// Battery: the backend state has no battery field. It is MODELLED from drone_config.json (initial % per drone,
// drain % per tick by activity) as ticks advance, and marked "*". If the backend ever sends drone.battery, that wins.
export const batteryOf = (d: any, bat: Record<string, number>) =>
  d.battery != null ? { v: Math.round(d.battery), est: false } : { v: Math.max(0, Math.round(bat[d.drone_id] ?? 100)), est: true }
export const connOf = (d: any) => (d.connected != null ? !!d.connected : d.status !== 'disconnected')
export const healthOf = (d: any, bat: number): 'ok' | 'warn' | 'bad' =>
  !connOf(d) ? 'bad' : bat < 25 || d.status === 'recovering' || d.status === 'returning' ? 'warn' : 'ok'

// Observations computed from real backend states (used live and in Experiments)
export type Obs = { dup: number; safety: number; firstDisc: number | null; recovered: number | null; discNow: number; dupNow: number; dupKeys: Record<string, 1>; safeKeys: Record<string, 1> }
export const emptyObs = (): Obs => ({ dup: 0, safety: 0, firstDisc: null, recovered: null, discNow: 0, dupNow: 0, dupKeys: {}, safeKeys: {} })
export function observe(o: Obs, run: any): Obs {
  const n: Obs = { ...o, dupKeys: { ...o.dupKeys }, safeKeys: { ...o.safeKeys } }
  const rows = rowsOf(run.grid); n.dupNow = 0
  for (const t of run.tasks) if ((t.assigned_to || []).length > 1 && t.status !== 'completed') {
    n.dupNow++; const k = t.task_id + ':' + [...t.assigned_to].sort().join(',')
    if (!n.dupKeys[k]) { n.dupKeys[k] = 1; n.dup++ }
  }
  for (const d of run.drones) { const c = rows[d.y]?.[d.x]
    if (c === 'X' || c === '#') { const k = `${d.drone_id}:${d.x},${d.y}`; if (!n.safeKeys[k]) { n.safeKeys[k] = 1; n.safety++ } } }
  n.discNow = run.drones.filter((d: any) => d.status === 'disconnected').length
  if (n.discNow > 0 && n.firstDisc == null) n.firstDisc = run.tick
  if (n.discNow === 0 && n.firstDisc != null && n.recovered == null) n.recovered = run.tick - n.firstDisc
  return n
}
export const recoveryText = (metric: any, o: Obs | null) =>
  metric != null ? String(metric) : !o ? '—' : o.recovered != null ? `${o.recovered} ticks` : o.firstDisc != null ? 'NOT RECOVERED' : '—'

export const summary = (r: any, mode: string, o: Obs | null, extra: any = {}) => ({
  run_id: r.run_id, scenario_id: r.scenario_id, mode, tick: r.tick, saved_at: new Date().toISOString(),
  coverage: r.coverage?.percentage ?? 0, completed: r.completed_tasks?.length ?? 0, total_tasks: r.tasks?.length ?? 0,
  blocked: r.tasks?.filter((t: any) => t.status === 'blocked').length ?? 0,
  duplicates: r.metrics?.duplicate_assignments ?? o?.dup ?? null, safety: r.metrics?.safety_violations ?? o?.safety ?? null,
  recovery: recoveryText(r.metrics?.recovery_time, o), comm: r.metrics?.communication_overhead ?? null, metrics: r.metrics ?? null, ...extra,
})
