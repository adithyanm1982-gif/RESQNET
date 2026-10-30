import { create } from 'zustand'
import { api, type CoordinationMode, type CustomFailureEvent, validateCustomFailurePlan } from './api'
import { Obs, emptyObs, observe, summary } from './lib'

export type Sev = 'info' | 'warn' | 'error'
export type Ev = { id: number; t: string; iso: string; tick: number; sev: Sev; cat: string; drone?: string; msg: string }
export type Handoff = { id: number; tick: number; t: string; task: string; from: string; to: string; x: number; y: number }
export type HazardPriority = { priority_level: number; priority_label: string }

const load = (k: string, d: any) => { try { const v = JSON.parse(localStorage.getItem(k) || ''); return v ?? d } catch { return d } }
const persist = (k: string, v: any) => { try { localStorage.setItem(k, JSON.stringify(v)); return true } catch { return false } }
const now = () => new Date().toLocaleTimeString('en-GB')
let uid = 1
const mk = (tick: number, sev: Sev, cat: string, msg: string, drone?: string): Ev => ({ id: uid++, t: now(), iso: new Date().toISOString(), tick, sev, cat, msg, drone })

interface S {
  droneCfg: any | null; failScen: any[]; failId: string; setFailScenario: (id: string) => void
  failureSource: 'none' | 'predefined' | 'custom'; setFailureSource: (source: 'none' | 'predefined' | 'custom') => void
  customPlan: CustomFailureEvent[]; setCustomPlan: (events: CustomFailureEvent[]) => void
  scenarios: any[]; scenarioId: string; mode: CoordinationMode
  run: any | null; archived: boolean; trails: Record<string, [number, number][]>; visited: Set<string>; dist: Record<string, number>; bat: Record<string, number>; lastSeen: Record<string, number>
  events: Ev[]; handoffs: Handoff[]; active: Record<string, 1>; obs: Obs
  hazards: Record<string, HazardPriority>; setHazards: (h: Record<string, HazardPriority>) => void
  covHistory: { tick: number; cov: number; done: number; disc: number; dup: number }[]
  running: boolean; busy: boolean; error: string; health: string; booting: boolean
  speedMs: number; ticksPerStep: number; selected: string; seed: string; basemap: 'satellite' | 'dark'; secPerTick: number
  saved: any[]; comparison: any[]; cmpProgress: string
  boot: () => Promise<void>; setScenario: (id: string) => void; setMode: (m: CoordinationMode) => void
  start: () => Promise<boolean>; step: () => Promise<void>; setRunning: (b: boolean) => void; reset: () => void
  setSpeed: (n: number) => void; setTicksPerStep: (n: number) => void; select: (id: string) => void
  setSeed: (s: string) => void; setBasemap: (b: 'satellite' | 'dark') => void; setSecPerTick: (n: number) => void
  saveRun: () => void; openSaved: (id: string) => Promise<boolean>; deleteSaved: (id: string) => void
  addNote: (cat: string, msg: string, sev?: Sev) => void
  compare: (ticks: number) => Promise<void>; saveComparison: () => void; clearSaved: () => void; wipeLocal: () => void
}

const fresh = () => ({ run: null, archived: false, trails: {}, visited: new Set<string>(), dist: {}, bat: {}, lastSeen: {}, events: [], handoffs: [], active: {}, obs: emptyObs(), covHistory: [] })
const initialFailId = localStorage.getItem('rq_fail') || ''
const storedFailureSource = localStorage.getItem('rq_schedule_source')
const initialFailureSource: S['failureSource'] = storedFailureSource === 'none' || storedFailureSource === 'predefined' || storedFailureSource === 'custom'
  ? storedFailureSource
  : initialFailId ? 'predefined' : 'none'
const loadedCustomPlan = load('rq_custom_plan', [])
const scenarioDroneIds = (scenarioId: string, droneCfg: any) =>
  (droneCfg?.fleets?.find((fleet: any) => fleet.scenario_id === scenarioId)?.drones || [])
    .map((drone: any) => drone.id)

// Compare previous and next backend state -> events, handoffs, conflicts (derived from real data).
// Frontend-generated alerts and "task blocked" warnings were intentionally removed.
function absorb(s: S, next: any) {
  const prev = s.run; const tick = next.tick
  const evs: Ev[] = []; const hands: Handoff[] = []
  const active = { ...s.active }

  if (prev) {
    const pt: any = Object.fromEntries(prev.tasks.map((t: any) => [t.task_id, t]))
    for (const t of next.tasks) {
      const o = pt[t.task_id]; if (!o) continue
      const a0: string[] = o.assigned_to || []; const a1: string[] = t.assigned_to || []
      if (o.status !== t.status && o.status !== 'blocked' && t.status !== 'blocked') evs.push(mk(tick, 'info', 'Task allocation', `Task ${t.task_id} ${o.status} → ${t.status}${a1.length ? ` (${a1.join(', ')})` : ''}`, a1[0]))
      if (a0.length && a1.length && !a1.some((x) => a0.includes(x))) {
        hands.push({ id: uid++, tick, t: now(), task: t.task_id, from: a0[0], to: a1[0], x: t.x, y: t.y })
        evs.push(mk(tick, 'warn', 'Recovery', `Task ${t.task_id} reassigned ${a0.join(',')} → ${a1.join(',')}`, a1[0]))
      }
    }
    const pd: any = Object.fromEntries(prev.drones.map((d: any) => [d.drone_id, d]))
    for (const d of next.drones) {
      const o = pd[d.drone_id]; if (!o) continue
      if (o.status !== d.status) {
        const lost = d.status === 'disconnected'; const back = o.status === 'disconnected'
        evs.push(mk(tick, lost ? 'error' : back ? 'info' : 'info', lost ? 'Disconnection' : back ? 'Reconnection' : 'Drone', `${d.drone_id} ${o.status} → ${d.status}`, d.drone_id))
      }
      if (o.task_id !== d.task_id && d.task_id) evs.push(mk(tick, 'info', 'Task allocation', `${d.drone_id} assigned ${d.task_id}`, d.drone_id))
    }
  }

  const bat = { ...s.bat }
  const prevD: any = Object.fromEntries((prev?.drones || []).map((d: any) => [d.drone_id, d])); const dt = prev ? Math.max(0, tick - prev.tick) : 0
  for (const d of next.drones) { // battery modelled from drone_config.json (initial %, drain %/tick by activity)
    const init = s.droneCfg?.fleets?.find((x: any) => x.scenario_id === next.scenario_id)?.drones?.find((x: any) => x.id === d.drone_id)?.initial_battery_pct
    const dr = s.droneCfg?.drone_types?.[d.type]?.battery?.drain_pct_per_tick; const o = prevD[d.drone_id]
    if (bat[d.drone_id] == null) bat[d.drone_id] = init ?? 100
    else if (dr && o) { const moved = o.x !== d.x || o.y !== d.y; bat[d.drone_id] = Math.max(0, bat[d.drone_id] - dt * (moved ? dr.moving : d.status === 'idle' ? dr.idle : dr.searching)) }
  }
  const dist = { ...s.dist }; const lastSeen = { ...s.lastSeen }; const trails = { ...s.trails }; const visited = new Set(s.visited)
  for (const d of next.drones) {
    const tr = (trails[d.drone_id] = [...(trails[d.drone_id] || [])]); const last = tr[tr.length - 1]
    if (last && (last[0] !== d.x || last[1] !== d.y)) dist[d.drone_id] = (dist[d.drone_id] || 0) + Math.abs(last[0] - d.x) + Math.abs(last[1] - d.y)
    if (!last || last[0] !== d.x || last[1] !== d.y) tr.push([d.x, d.y])
    visited.add(`${d.x},${d.y}`)
    if (d.status !== 'disconnected') lastSeen[d.drone_id] = tick
  }
  
  const obs = observe(s.obs, next)
  return {
    run: next, trails, visited, dist, bat, lastSeen, active, obs,
    events: [...evs.reverse(), ...s.events].slice(0, 600), handoffs: [...hands, ...s.handoffs].slice(0, 50),
    covHistory: [...s.covHistory, { tick, cov: next.coverage?.percentage ?? 0, done: next.completed_tasks?.length ?? 0, disc: obs.discNow, dup: obs.dupNow }].slice(-800),
  }
}

export const useStore = create<S>((set, get) => ({
  droneCfg: null, failScen: [], failId: initialFailId,
  failureSource: initialFailureSource,
  customPlan: Array.isArray(loadedCustomPlan) ? loadedCustomPlan : [],
  scenarios: [], scenarioId: localStorage.getItem('rq_scn') || '', mode: (localStorage.getItem('rq_mode') as CoordinationMode) || 'hybrid',
  ...fresh(), hazards: {}, running: false, busy: false, error: '', health: 'unknown', booting: false,
  speedMs: load('rq_speed', 700), ticksPerStep: load('rq_tps', 1), selected: '', seed: load('rq_seed', ''), basemap: load('rq_base', 'satellite'), secPerTick: load('rq_spt', 2),
  saved: load('rq_saved2', []), comparison: [], cmpProgress: '',

  boot: async () => {
    set({ booting: true })
    // Independent loads (a slow/hanging health check must never block scenarios or datasets).
    const health = api.health().then((h) => set({ health: h.status === 'ok' ? 'ok' : h.api === 'ok' ? 'db-offline' : 'unhealthy' }))
      .catch(() => set({ health: 'timeout' }))
    const scn = api.scenarios().then((sc) => set({ scenarios: sc, error: '', scenarioId: get().scenarioId && sc.some((x: any) => x.scenario_id === get().scenarioId) ? get().scenarioId : sc[0]?.scenario_id || '' }))
      .catch((e: any) => set({ error: `Cannot load scenarios from backend: ${e.message}` }))
    const cfg = api.droneConfig().then((c) => set({ droneCfg: c })).catch((e: any) => set({ error: `Cannot load drone config from backend: ${e.message}` }))
    const fs = api.failureScenarios().then((f) => set({ failScen: f.failure_scenarios || [] })).catch((e: any) => set({ error: `Cannot load failure scenarios from backend: ${e.message}` }))
    await Promise.allSettled([health, scn, cfg, fs])
    // Scenarios loaded but health failed/timed out => the API is up and only the database check is the problem.
    if (get().scenarios.length && !['ok', 'db-offline'].includes(get().health)) set({ health: 'db-offline' })
    set({ booting: false })
  },
  setFailScenario: (id) => {
    localStorage.setItem('rq_fail', id)
    const source = id ? 'predefined' : 'none'
    localStorage.setItem('rq_schedule_source', source)
    set({ failId: id, failureSource: source })
  },
  setFailureSource: (source) => { localStorage.setItem('rq_schedule_source', source); set({ failureSource: source }) },
  setCustomPlan: (events) => { persist('rq_custom_plan', events); set({ customPlan: events }) },
  setScenario: (id) => { localStorage.setItem('rq_scn', id); set({ scenarioId: id }) },
  setMode: (m) => { localStorage.setItem('rq_mode', m); set({ mode: m }) },
  setHazards: (h) => set({ hazards: h }),
  start: async () => {
    const { scenarioId, mode, failId, failureSource, customPlan, droneCfg } = get(); if (!scenarioId) return false
    if (failureSource === 'predefined' && !failId) { set({ error: 'Choose a predefined failure schedule or select no failure schedule.' }); return false }
    if (failureSource === 'custom') {
      const errors = validateCustomFailurePlan(customPlan, scenarioDroneIds(scenarioId, droneCfg))
      if (errors.length) { set({ error: errors.join(' ') }); return false }
    }
    set({ busy: true, running: false })
    try {
      let r = await api.create(scenarioId, mode)
      if (failureSource === 'predefined' && failId) r = await api.installFailureSchedule(r.run_id, failId)
      else if (failureSource === 'custom') r = await api.installCustomFailurePlan(r.run_id, customPlan)
      set({ ...fresh(), error: '', selected: '' })
      set((s) => ({ ...absorb(s, r), events: [mk(0, 'info', 'System', `Run ${r.run_id.slice(0, 8)} created (${scenarioId}, mode: ${mode})`)], busy: false, running: true }))
      return true
    } catch (e: any) { set({ busy: false, running: false, error: e.message }); return false }
  },
  step: async () => {
    const { run, busy, ticksPerStep, archived } = get(); if (!run || busy || archived) return
    set({ busy: true })
    try {
      const r = await api.tick(run.run_id, ticksPerStep); set((s) => ({ ...absorb(s, r), busy: false }))
    } catch (e: any) { set({ busy: false, running: false, error: e.message }) }
  },
  setRunning: (b) => set({ running: b }),
  reset: () => set({ ...fresh(), running: false, selected: '', error: '' }),
  setSpeed: (n) => { persist('rq_speed', n); set({ speedMs: n }) },
  setTicksPerStep: (n) => { persist('rq_tps', n); set({ ticksPerStep: n }) },
  setSeed: (s) => { persist('rq_seed', s); set({ seed: s }) },
  setBasemap: (b) => { persist('rq_base', b); set({ basemap: b }) },
  setSecPerTick: (n) => { persist('rq_spt', n); set({ secPerTick: n }) },
  select: (id) => set({ selected: id }),
  addNote: (cat, msg, sev = 'info') => { const { run } = get(); if (msg.trim()) set((s) => ({ events: [mk(run?.tick ?? 0, sev, cat, msg.trim()), ...s.events] })) },
  saveRun: () => {
    const { run, mode, saved, events, covHistory, handoffs, trails, visited, dist, obs } = get(); if (!run) return
    const rec = { ...summary(run, mode, obs), detail: { run, events: events.slice(0, 300), covHistory: covHistory.slice(-300), handoffs, trails, visited: [...visited], dist, bat: get().bat, obs } }
    let next = [rec, ...saved.filter((x: any) => x.run_id !== run.run_id)].slice(0, 20)
    while (next.length > 1 && !persist('rq_saved2', next)) next = next.slice(0, -1) // quota guard
    set({ saved: next })
  },
  openSaved: async (id) => {
    const rec = get().saved.find((x: any) => x.run_id === id); if (!rec) return false
    let d = rec.detail
    if (!d) { // comparison rows are summaries: pull the live state from the backend if it still has the run
      try { const st = await api.state(id); d = { run: st, events: [], covHistory: [], handoffs: [], trails: {}, visited: [], dist: {}, obs: emptyObs() } }
      catch (e: any) { set({ error: `Cannot reopen ${id.slice(0, 8)} from backend: ${e.message}` }); return false }
    }
    set({ ...fresh(), run: d.run, archived: true, running: false, mode: rec.mode, trails: d.trails || {}, visited: new Set(d.visited || []), dist: d.dist || {}, bat: d.bat || {}, events: d.events || [], covHistory: d.covHistory || [], handoffs: d.handoffs || [], obs: d.obs || emptyObs(), error: '', selected: '' })
    return true
  },
  deleteSaved: (id) => { const next = get().saved.filter((x: any) => x.run_id !== id); persist('rq_saved2', next); set({ saved: next }) },
  clearSaved: () => { localStorage.removeItem('rq_saved2'); set({ saved: [] }) },
  wipeLocal: () => { ['rq_saved2', 'rq_plan', 'rq_fail', 'rq_schedule_source', 'rq_custom_plan', 'rq_anchor', 'rq_seed', 'rq_base', 'rq_spt', 'rq_speed', 'rq_tps'].forEach((k) => localStorage.removeItem(k)); location.reload() },
  // Each compared run receives the same selected schedule before its first tick.
  compare: async (ticks) => {
    const { scenarioId, failId, failureSource, customPlan, droneCfg } = get(); if (!scenarioId) return
    if (failureSource === 'predefined' && !failId) { set({ error: 'Choose a predefined failure schedule or select no failure schedule.' }); return }
    if (failureSource === 'custom') {
      const errors = validateCustomFailurePlan(customPlan, scenarioDroneIds(scenarioId, droneCfg))
      if (errors.length) { set({ error: errors.join(' ') }); return }
    }
    set({ busy: true, comparison: [], error: '', cmpProgress: '' })
    try {
      const rows: any[] = []; const chunk = ticks > 300 ? 5 : 1
      for (const m of ['centralized', 'decentralized', 'hybrid'] as CoordinationMode[]) {
        let r = await api.create(scenarioId, m); const id = r.run_id
        let injection = 'no failure schedule'
        if (failureSource === 'predefined' && failId) {
          r = await api.installFailureSchedule(id, failId)
          injection = `${failId} schedule installed`
        } else if (failureSource === 'custom') {
          r = await api.installCustomFailurePlan(id, customPlan)
          injection = `custom plan (${customPlan.length} events) installed`
        }
        let o = observe(emptyObs(), r)
        let finished: number | null = r.mission_status === 'completed' ? r.tick : null
        let tasksFinished: number | null = r.tasks_completed_tick ?? null
        while (r.tick < ticks && r.mission_status !== 'completed') {
          set({ cmpProgress: `${m}: tick ${r.tick}/${ticks}` })
          r = await api.tick(id, Math.min(chunk, ticks - r.tick)); o = observe(o, r)
          if (tasksFinished == null && r.tasks_completed_tick != null) tasksFinished = r.tasks_completed_tick
          if (r.mission_status === 'completed') finished = r.tick
        }
        rows.push({ ...summary(r, m, o, { injection, finished, tasksFinished }) }); set({ comparison: [...rows] })
      }
      set({ busy: false, cmpProgress: '' })
    } catch (e: any) { set({ busy: false, error: e.message, cmpProgress: '' }) }
  },
  saveComparison: () => {
    const { comparison, saved } = get(); if (!comparison.length) return
    const next = [...comparison.map((c) => ({ ...c })), ...saved.filter((x: any) => !comparison.some((c) => c.run_id === x.run_id))].slice(0, 20)
    persist('rq_saved2', next); set({ saved: next })
  },
}))