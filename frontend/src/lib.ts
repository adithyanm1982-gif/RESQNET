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

// Task priority scale (from disaster_scenarios.json: 1 low ... 5 life-threatening) and its display colours.
export const PRIORITY_SCALE: Record<number, { label: string; color: string }> = {
  5: { label: 'Life-threatening', color: '#ff1744' },
  4: { label: 'Critical', color: '#ff6d00' },
  3: { label: 'High', color: '#ffea00' },
  2: { label: 'Moderate', color: '#00e676' },
  1: { label: 'Low', color: '#00e5ff' },
}
export const priorityColor = (level: number) => (PRIORITY_SCALE[level] ?? PRIORITY_SCALE[1]).color
export type DronePriority = { level: number; label: string; color: string; task: string; basis: 'current' | 'assigned' | 'completed' }
// A drone's priority comes from the simulation's task data:
//  1) the task it is working on now, else 2) the highest-priority unfinished task assigned to it,
//  else 3) the highest-priority task it has completed. Returns null if it has never owned a task.
export function dronePriority(run: any, d: any): DronePriority | null {
  const tasks: any[] = run?.tasks || []
  const owns = (t: any) => (t.assigned_to || []).includes(d.drone_id) || (t.claims || []).some((c: any) => c.drone_id === d.drone_id)
  const best = (list: any[]) => list.reduce((a: any, t: any) => (!a || (t.priority ?? 0) > (a.priority ?? 0) ? t : a), null)
  const make = (t: any, basis: DronePriority['basis']): DronePriority | null => {
    const level = Number(t?.priority)
    return t && level >= 1 ? { level, label: (PRIORITY_SCALE[level] ?? PRIORITY_SCALE[1]).label, color: priorityColor(level), task: t.task_id, basis } : null
  }
  const current = d.task_id ? tasks.find((t) => t.task_id === d.task_id) : null
  return make(current, 'current')
    ?? make(best(tasks.filter((t) => t.status !== 'completed' && owns(t))), 'assigned')
    ?? make(best(tasks.filter((t) => t.status === 'completed' && owns(t))), 'completed')
}

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