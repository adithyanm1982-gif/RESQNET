// In production use VITE_BACKEND_URL; locally keep same-origin requests so Vite's /api proxy applies.
const BACKEND_URL = (import.meta.env.VITE_BACKEND_URL || '').replace(/\/+$/, '')
const apiUrl = (path: string) => `${BACKEND_URL}${path}`

export type CoordinationMode = 'centralized' | 'decentralized' | 'hybrid'
export type CustomFailureType = 'controller_outage' | 'network_partition' | 'drone_unresponsive'
export type CustomFailureReconnection = {
  detect_timeout_ticks: number
  reconnect_delay_ticks: number
  resync_time_ticks: number
}
export type CustomPartitionGroup = {
  group_id: string
  drone_ids: string[]
  has_controller_link: boolean
}
type CustomFailureBase = {
  start_tick: number
  restore_tick: number | null
}
export type CustomFailureEvent = CustomFailureBase & (
  | { type: 'controller_outage'; reconnection: CustomFailureReconnection; groups?: never; drone_id?: never }
  | { type: 'network_partition'; groups: CustomPartitionGroup[]; reconnection: CustomFailureReconnection; drone_id?: never }
  | { type: 'drone_unresponsive'; drone_id: string; groups?: never; reconnection?: never }
)

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

export function validateCustomFailurePlan(
  events: CustomFailureEvent[],
  knownDroneIds: string[],
): string[] {
  const errors: string[] = []
  if (!Array.isArray(events) || events.length < 1 || events.length > 10) {
    return ['A custom plan must contain between 1 and 10 events.']
  }
  const known = new Set(knownDroneIds)
  const intervals: { type: CustomFailureType; target?: string; start: number; end: number }[] = []
  events.forEach((event, index) => {
    const label = `Event ${index + 1}`
    if (!event || !['controller_outage', 'network_partition', 'drone_unresponsive'].includes(event.type)) {
      errors.push(`${label}: unsupported failure type.`)
      return
    }
    if (!Number.isInteger(event.start_tick) || event.start_tick < 1 || event.start_tick > 100_000) {
      errors.push(`${label}: start tick must be an integer from 1 to 100000.`)
      return
    }
    const end = event.restore_tick
    if (end !== null && (!Number.isInteger(end) || end <= event.start_tick || end > 100_000)) {
      errors.push(`${label}: restore tick must be later than its start tick and no greater than 100000.`)
    }
    let target: string | undefined
    if (event.type === 'drone_unresponsive') {
      target = event.drone_id
      if (!target || !known.has(target)) errors.push(`${label}: select a drone in the current scenario.`)
      if (event.groups || event.reconnection) errors.push(`${label}: drone failures do not use partition or reconnection fields.`)
    } else {
      if (end === null) errors.push(`${label}: controller and partition events require a restore tick.`)
      if (event.drone_id) errors.push(`${label}: this event type does not target an individual drone.`)
      const recovery = event.reconnection
      if (!recovery || ['detect_timeout_ticks', 'reconnect_delay_ticks', 'resync_time_ticks'].some((key) => {
        const value = (recovery as any)?.[key]
        return !Number.isInteger(value) || value < 0 || value > 10_000
      })) errors.push(`${label}: enter valid nonnegative reconnection tick counts.`)
      if (event.type === 'controller_outage' && event.groups) errors.push(`${label}: controller outages do not use partition groups.`)
      if (event.type === 'network_partition') {
        const groups = Array.isArray(event.groups) ? event.groups : []
        if (!Array.isArray(event.groups)) errors.push(`${label}: partition groups must be a list.`)
        if (groups.length < 2 || groups.length > 20) errors.push(`${label}: a partition needs 2 to 20 groups.`)
        const seenIds = new Set<string>()
        const seenDrones = new Set<string>()
        for (const group of groups) {
          if (!group || typeof group !== 'object') {
            errors.push(`${label}: each partition group must be an object.`)
            continue
          }
          if (typeof group.group_id !== 'string' || !group.group_id || seenIds.has(group.group_id)) errors.push(`${label}: partition group IDs must be unique.`)
          seenIds.add(group.group_id)
          if (typeof group.has_controller_link !== 'boolean') errors.push(`${label}: specify whether each group can reach the controller.`)
          if (!Array.isArray(group.drone_ids) || !group.drone_ids.length) {
            errors.push(`${label}: every partition group must contain a drone.`)
            continue
          }
          for (const droneId of group.drone_ids) {
            if (!known.has(droneId)) errors.push(`${label}: partition contains a drone outside the current scenario.`)
            if (seenDrones.has(droneId)) errors.push(`${label}: a drone may appear in only one partition group.`)
            seenDrones.add(droneId)
          }
        }
        if (seenDrones.size !== known.size || [...known].some((id) => !seenDrones.has(id))) {
          errors.push(`${label}: partition groups must cover every drone in the current scenario exactly once.`)
        }
      } else if (event.groups) errors.push(`${label}: this event type does not use partition groups.`)
    }
    if (end !== null && Number.isInteger(event.start_tick)) {
      let effectiveEnd = end
      if (event.type !== 'drone_unresponsive' && event.reconnection) {
        effectiveEnd += event.reconnection.reconnect_delay_ticks + event.reconnection.resync_time_ticks
      }
      intervals.push({ type: event.type, target, start: event.start_tick, end: effectiveEnd })
    } else if (event.type === 'drone_unresponsive' && end === null) {
      intervals.push({ type: event.type, target, start: event.start_tick, end: Number.POSITIVE_INFINITY })
    }
  })
  for (let i = 0; i < intervals.length; i++) for (let j = i + 1; j < intervals.length; j++) {
    const a = intervals[i], b = intervals[j]
    if (a.type === b.type && (a.type !== 'drone_unresponsive' || a.target === b.target)
      && Math.max(a.start, b.start) < Math.min(a.end, b.end)) {
      errors.push('Events affecting the same controller, partition, or drone cannot overlap, including recovery time.')
    }
  }
  return [...new Set(errors)]
}

async function req(path: string, init?: RequestInit) {
  const r = await fetch(apiUrl(path), { ...init, headers: { 'Content-Type': 'application/json' } })
  let body: any = null
  try { body = await r.json() } catch { /* empty */ }
  if (!r.ok) throw new ApiError(`${r.status} ${typeof body?.detail === 'string' ? body.detail : r.statusText}`, r.status)
  return body
}
export const api = {
  // /api/health answers 503 when PostgreSQL is down but the API itself is fine: report that instead of throwing.
  // /api/health also pings PostgreSQL and can answer 503 (DB down) or hang. Never let that block the app: 5 s timeout.
  health: async () => {
    const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 5000)
    try { const r = await fetch(apiUrl('/api/health'), { signal: ctl.signal }); try { return await r.json() } catch { return { status: 'unhealthy' } } }
    finally { clearTimeout(t) }
  },
  scenarios: () => req('/api/simulations/scenarios'),
  create: (scenario_id: string, mode: CoordinationMode = 'centralized') => req('/api/simulations', { method: 'POST', body: JSON.stringify({ scenario_id, mode }) }),
  tick: (id: string, ticks = 1) => req(`/api/simulations/${id}/ticks`, { method: 'POST', body: JSON.stringify({ ticks }) }),
  state: (id: string) => req(`/api/simulations/${id}`),
  droneConfig: () => req('/api/datasets/drone-config'),
  failureScenarios: () => req('/api/datasets/failure-scenarios'),
  installFailureSchedule: (id: string, failure_scenario_id: string) => req(
    `/api/simulations/${id}/failures`,
    { method: 'POST', body: JSON.stringify({ failure_scenario_id }) },
  ),
  installCustomFailurePlan: (id: string, events: CustomFailureEvent[]) => req(
    `/api/simulations/${id}/failures`,
    { method: 'POST', body: JSON.stringify({ custom_plan: { events } }) },
  ),
  authConfig: () => req('/api/auth/config', { credentials: 'include' }),
  authNonce: () => req('/api/auth/nonce', { credentials: 'include' }),
  authMe: () => req('/api/auth/me', { credentials: 'include' }),
  authGoogle: (credential: string) => req('/api/auth/google', {
    method: 'POST',
    credentials: 'include',
    body: JSON.stringify({ credential }),
  }),
  authLogout: () => req('/api/auth/logout', {
    method: 'POST',
    credentials: 'include',
  }),
}
