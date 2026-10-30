import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import MapView from '../components/MapView'
import { DroneIcon } from '../components/Icons'
import { useStore } from '../store'
import { label, latlon } from '../geo'
import { batteryOf, connOf, dname, healthOf, mmss } from '../lib'
import { batClass } from '../batteryColor'
import type { CoordinationMode } from '../api'

// Priority level -> colour (same palette as the map legend)
const PRI_COLOR: Record<number, string> = { 5: '#ff1744', 4: '#ff6d00', 3: '#ffea00', 2: '#00e676', 1: '#00e5ff' }
const priColor = (level: number) => PRI_COLOR[level] ?? '#00e5ff'

export default function Mission() {
  const s = useStore(); const { run } = s
  const [dF, setDF] = useState(''); const [sF, setSF] = useState('all')
  useEffect(() => {
    if (!s.running) return
    const id = setInterval(() => useStore.getState().step(), s.speedMs)
    return () => clearInterval(id)
  }, [s.running, s.speedMs])
  useEffect(() => {
    if (run?.mission_status === 'completed' && !s.archived) {
      if (s.running) s.setRunning(false)
      s.saveRun()
    }
  }, [run?.mission_status])

  const ctl = (
    <div className="tb-c glass">
      {!run ? <button className="primary sm" disabled={!s.scenarioId || s.busy} onClick={s.start}>▶ Start</button> : <>
        {run.mission_status === 'completed'
          ? <button className="primary sm" disabled>✓ Mission complete</button>
          : <button className="primary sm" disabled={s.archived} onClick={() => s.setRunning(!s.running)}>{s.running ? '❚❚ Pause' : '▶ Resume'}</button>}
        <button className="sm" disabled={s.running || s.busy || s.archived || run.mission_status === 'completed'} onClick={() => s.step()}>Step</button>
        <button className="sm" disabled={s.busy} onClick={s.start}>↻ Restart</button>
        <button className="sm danger" onClick={s.reset}>■ Reset</button></>}
      <span className="mono mut" style={{ fontSize: 11 }}>{(run?.coordination_mode ?? s.mode).toUpperCase()}{run ? ` · ${mmss(run.tick * s.secPerTick)}` : ''}</span>
    </div>)

  if (!run) return (
    <div className="mc" style={{ gridTemplateRows: 'minmax(0,1fr)' }}>
      <div className="col"><div className="card fill"><h3>Active aircraft</h3><p className="mut">Drones appear here once a run is created from the backend.</p></div></div>
      <MapView>{ctl}<div className="overlay"><div className="card" style={{ width: 360 }}>
        <h3>No active mission</h3>
        <p className="mut" style={{ margin: '0 0 12px' }}>Choose a scenario and coordination mode, then select Start mission to begin a simulation.</p>
        <div style={{ display: 'grid', gap: 10 }}>
          <label className="f">Scenario<select value={s.scenarioId} onChange={(e) => s.setScenario(e.target.value)}>{s.scenarios.map((x: any) => <option key={x.scenario_id} value={x.scenario_id}>{x.name}</option>)}</select></label>
          <label className="f">Mode<select value={s.mode} onChange={(e) => s.setMode(e.target.value as CoordinationMode)}><option value="centralized">Centralized</option><option value="decentralized">Decentralized</option><option value="hybrid">Hybrid RESQNET</option></select></label>
          {s.error && <div className="err">{s.error}</div>}
          <button className="primary" disabled={!s.scenarioId || s.busy} onClick={s.start}>{s.busy ? 'Creating run…' : '▶ Start mission'}</button>
          <Link className="btn" to="/scenarios">Choose layout & failure condition</Link></div></div></div></MapView>
      <div className="col"><div className="card fill"><h3>Drone priority & flight paths</h3><p className="mut">Priority levels and flight-path coordinates appear here once a mission is running.</p></div></div>
    </div>)

  const done = run.completed_tasks.length; const total = run.tasks.length
  const discN = run.drones.filter((d: any) => !connOf(d)).length
  const sysCls = discN ? 'bad' : s.obs.dupNow ? 'warn' : ''
  const evs = s.events.filter((e) => (sF === 'all' || e.sev === sF) && (!dF || e.drone === dF))
  const topTasks = [...run.tasks].sort((a: any, b: any) => (b.priority ?? 0) - (a.priority ?? 0)).slice(0, 7)
  const isDecentralized = run.coordination_mode === 'decentralized'
  const isHybrid = run.coordination_mode === 'hybrid'
  const showClaims = isDecentralized || isHybrid
  const claimCounts = showClaims ? run.tasks.reduce((counts: Record<string, number>, task: any) => {
    counts[task.claim_status] = (counts[task.claim_status] || 0) + 1
    return counts
  }, {}) : {}
  const releasedClaimCount = showClaims ? run.tasks.reduce((total: number, task: any) => total + (task.released_claims?.length || 0), 0) : 0
  const reconciliationHistory = isHybrid && Array.isArray(run.reconciliation_history) ? run.reconciliation_history : []
  const strategyLabels: Record<string, string> = {
    centralized_allocation: 'Centralized allocation',
    decentralized_fallback: 'Decentralized fallback',
    reconciliation: 'Reconciliation',
  }
  const inProg = run.tasks.filter((t: any) => t.status !== 'completed' && t.status !== 'pending' && t.status !== 'blocked').length
  const exploring = run.drones.some((d: any) => d.status === 'exploring')
  const missionLabel = run.mission_status === 'completed'
    ? run.mission_completion_reason === 'mission_duration_reached'
      ? 'Mission duration limit reached'
      : run.mission_completion_reason === 'no_reachable_unvisited_cells'
        ? 'Mission complete · no safe reachable exploration'
        : 'Mission complete · coverage objective reached'
    : run.coverage.percentage >= (run.coverage_target_percentage ?? 90)
      ? 'Coverage objective reached · resolving remaining work'
      : done === total && total > 0
        ? 'Area exploration in progress'
        : exploring
          ? 'Tasks and area exploration in progress'
          : 'Task execution in progress'
  const coverageProgress = Math.min(
    100,
    run.coverage.percentage / (run.coverage_target_percentage || 90) * 100,
  )

  return (
    <div className="mc">
      <div className="col">
        <div className="card fill"><h3>Active aircraft ({run.drones.length})</h3>
          {run.drones.map((d: any) => { const b = batteryOf(d, s.bat); const sel = s.selected === d.drone_id; const ls = s.lastSeen[d.drone_id]
            const owned = run.tasks.filter((t: any) => (t.assigned_to || []).includes(d.drone_id)).map((t: any) => t.task_id)
            return (
              <div key={d.drone_id} className={'dc ' + (sel ? 'sel' : '')} onClick={() => s.select(d.drone_id)}>
                <div className="h"><span className="dico"><DroneIcon /></span><span>{dname(d.drone_id)}</span><span className="grow" /><span className={'pill ' + d.status}>{d.status.toUpperCase()}</span></div>
                <div className="bat"><span>Battery{b.est ? '*' : ''}</span><div className="meter"><i className={batClass(b.v)} style={{ width: `${b.v}%` }} /></div><b className={batClass(b.v)}>{b.v}%</b></div>
                <div className="co mono">({d.x}, {d.y}) · {label(d.x, d.y)}<br />{latlon(d.x, d.y)}<br />Task: {d.task_id ?? '—'}</div>
                {sel && <div className="ext">
                  <span>Type: <b>{d.type ?? '—'}</b></span><span>Task ownership: <b className="mono">{owned.join(', ') || 'none'}</b></span>
                  <span>Connectivity: <b className={connOf(d) ? 'c-g' : 'c-r'}>{connOf(d) ? 'CONNECTED' : 'DISCONNECTED'}</b></span>
                  <span>Last update: <b className="mono">tick {ls ?? '—'}{ls != null && run.tick - ls > 0 ? ` (${run.tick - ls} ago)` : ''}</b></span>
                  <span>Distance flown: <b className="mono">{s.dist[d.drone_id] || 0} cells</b></span>
                  {(() => { const t = s.droneCfg?.drone_types?.[d.type]; const fl = s.droneCfg?.fleets?.find((x: any) => x.scenario_id === run.scenario_id)?.drones?.find((x: any) => x.id === d.drone_id)
                    return t ? <><span>Speed / comm range: <b className="mono">{t.speed_cells_per_tick} cells/tick · {t.comm_range_cells} cells</b></span><span>Return / critical: <b className="mono">{t.battery.return_threshold_pct}% / {t.battery.critical_pct}%</b></span>{fl && <span>Home base: <b className="mono">({fl.home_base.x},{fl.home_base.y}){fl.can_relay ? ' · relay' : ''}</b></span>}</> : null })()}</div>}
              </div>) })}
          <div className="mut" style={{ fontSize: 10.5 }}>* battery modelled from drone_config.json drain rates (the backend state has no battery field).</div>
        </div>
      </div>

      <MapView>{ctl}
        {s.archived && <div className="arch glass">VIEWING SAVED RUN · READ-ONLY</div>}
        <div className="runinfo glass mono">TICK {run.tick} · {mmss(run.tick * s.secPerTick)} · COVERAGE {run.coverage.percentage}%</div>
      </MapView>

      <div className="col scroll">
        <div className="card"><h3><span className="grow">Drone priority & flight paths</span><span className="badge">{run.drones.length} drones</span></h3>
          <div className="pathlist">
            {run.drones.map((d: any) => {
              const hz = s.hazards[d.drone_id]
              const path: [number, number][] = s.trails[d.drone_id] || []
              return (
                <div key={d.drone_id} className="pathbox" style={hz ? ({ '--pc': priColor(hz.priority_level) } as any) : undefined} onClick={() => s.select(d.drone_id)}>
                  <div className="ph">
                    <b>{dname(d.drone_id)}</b>
                    {hz ? <span className="pchip">P{hz.priority_level} · {hz.priority_label}</span> : <span className="mut">No priority data</span>}
                    <span className="grow" /><span className="mut mono">{path.length} pts</span>
                  </div>
                  {path.length
                    ? <ol className="plist mono">{path.map(([x, y], i) => <li key={i}>({x}, {y}) · {label(x, y)}</li>)}</ol>
                    : <span className="mut" style={{ fontSize: 11 }}>No path recorded yet.</span>}
                </div>)
            })}
          </div></div>
        <div className="card"><h3>Mission status</h3>
          <div className="mono" style={{ lineHeight: 1.7, fontSize: 12 }}>
            {missionLabel}<br />
            Elapsed {mmss(run.tick * s.secPerTick)} · Tick {run.tick}/{run.mission_duration_ticks ?? '—'} · Tasks complete {done}/{total}<br />
            Coverage {run.coverage.percentage}% / {run.coverage_target_percentage ?? 90}% target ({run.coverage.visited_cells}/{run.coverage.traversable_cells} cells)<br />
            Reachable unexplored cells {run.remaining_reachable_unvisited_cells ?? '—'}
          </div>
          <div className="meter"><i style={{ width: `${total ? (done / total) * 100 : 0}%`, background: 'var(--cy)' }} /></div>
          <div className="mut mono" style={{ fontSize: 10, marginTop: 4 }}>TASK COMPLETION</div>
          <div className="meter"><i style={{ width: `${coverageProgress}%`, background: 'var(--teal)' }} /></div>
          <div className="mut mono" style={{ fontSize: 10, marginTop: 4 }}>AREA COVERAGE</div>
          <div style={{ marginTop: 6 }}>{topTasks.map((t: any) => { const st = t.status === 'completed' ? '' : t.status === 'blocked' ? 'blocked' : t.status === 'pending' ? 'pending' : 'active'
            return <div className="ms" key={t.task_id}><span className={'ck ' + st}>{st === '' ? '✓' : st === 'blocked' ? '!' : st === 'pending' ? '…' : '▶'}</span><div><small>{t.task_id} · P{t.priority}</small><span className="mut" style={{ fontSize: 11 }}>{t.status} · {(t.assigned_to || []).join(', ') || 'unassigned'}</span></div></div> })}</div>
          {(run.candidate_detections || []).length > 0 && <p className="mut" style={{ fontSize: 11 }}>Unverified candidates: {(run.candidate_detections || []).filter((c: any) => c.verification_status !== 'confirmed').length} (observations, not confirmed rescues)</p>}
        </div>
        {isHybrid && <div className="card"><h3>Hybrid coordination</h3>
          <div className="hybrid-strategy"><span className="mut">Operational strategy</span><b className="badge">{strategyLabels[run.operational_strategy] || run.operational_strategy || 'Unavailable'}</b></div>
          <div className="hybrid-links">
            <span>Controller service <b className={run.controller_available ? 'c-g' : 'c-r'}>{run.controller_available == null ? 'unknown' : run.controller_available ? 'available' : 'unavailable'}</b></span>
            <span>Controller reachable <b className={run.controller_reachable ? 'c-g' : 'c-r'}>{run.controller_reachable == null ? 'unknown' : run.controller_reachable ? 'yes' : 'no'}</b></span>
          </div>
          {run.operational_strategy === 'decentralized_fallback' && <p className="mut hybrid-note">{!run.controller_available ? 'Fallback is active because the controller is unavailable.' : run.partition_state?.length ? 'Fallback is active for drones outside the controller linked partition group.' : 'Local coordination is active while connectivity recovers.'}</p>}
          {!!run.partition_state?.length && <div className="partition-groups"><b>Active network partition</b>{run.partition_state.flatMap((partition: any) => partition.groups.map((group: any) => <div className="partition-group" key={`${partition.event_id}-${group.group_id}`}><span>Group {group.group_id}</span><span>{group.has_controller_link ? 'Controller linked' : 'Local coordination'}</span><span className="mono">{group.drone_ids.join(', ')}</span></div>))}</div>}
          <div className="hybrid-history"><b>Recovery and reconciliation</b>
            {reconciliationHistory.length
              ? reconciliationHistory.slice(-6).reverse().map((action: any, index: number) => <div className="mut claim-detail" key={`${action.event_id}-${action.task_id}-${action.drone_id || action.action}-${index}`}>
                Tick {action.tick} · {action.task_id} · {action.action.split('_').join(' ')}{action.drone_id ? ` · ${action.drone_id}` : ''}{action.reason ? ` · ${action.reason}` : ''}
              </div>)
              : <p className="mut claim-empty">No reconciliation has occurred in this run.</p>}
          </div>
          {run.operational_strategy === 'centralized_allocation' && reconciliationHistory.length > 0 && <p className="mut hybrid-note">Centralized allocation is active again after reconciliation.</p>}
        </div>}
        {showClaims && <div className="card"><h3><span className="grow">{isHybrid ? 'Hybrid task ownership' : 'Decentralized task claims'}</span><span className="badge">{run.tasks.length} tasks</span></h3>
          <div className="claim-summary">
            <span>Claimed <b>{claimCounts.claimed || 0}</b></span><span>Unclaimed <b>{claimCounts.unclaimed || 0}</b></span><span>Completed <b>{claimCounts.completed || 0}</b></span>
          </div>
          <div className="claim-list">
            {run.tasks.map((task: any) => {
              const claims = Array.isArray(task.claims) ? task.claims : []
              const released = Array.isArray(task.released_claims) ? task.released_claims : []
              const completed = task.claim_status === 'completed'
              return <article className="claim-task" key={task.task_id}>
                <div className="claim-heading"><b>{task.task_id}</b><span className={'claim-state ' + (completed ? 'complete' : task.claim_status)}>{task.claim_status}</span></div>
                <div className="mut claim-detail">Task status: {task.status} · {completed ? `team size ${claims.length}/${task.required_drones}` : `owners ${claims.length}/${task.required_drones}`}</div>
                {claims.length > 0
                  ? <div className="claim-owners">{completed ? 'Recorded claims' : 'Current owners'}: {claims.map((claim: any) => `${claim.drone_id} (tick ${claim.claim_tick ?? 'unavailable'}${claim.group_id ? ` · ${claim.group_id}` : ''})`).join(', ')}</div>
                  : <div className="mut claim-detail">{completed ? 'No claim records returned.' : 'No active owners.'}</div>}
                {released.length > 0 && <details className="claim-history"><summary>Released claims ({released.length})</summary>
                  {released.map((claim: any, index: number) => <div className="mut claim-detail" key={`${claim.drone_id}-${claim.released_tick}-${index}`}>
                    {claim.drone_id} · claim tick {claim.claim_tick ?? 'unavailable'} · released tick {claim.released_tick ?? 'unavailable'} · {claim.reason}
                  </div>)}
                </details>}
              </article>
            })}
          </div>
          {releasedClaimCount === 0 && <p className="mut claim-empty">No claim releases have been recorded for this run.</p>}
        </div>}
      </div>

      <div className="bottom">
        <div className="card"><h3><span className="grow">Flight log (live)</span>
          <select className="sm" value={sF} onChange={(e) => setSF(e.target.value)}><option value="all">All severity</option><option value="info">Info</option><option value="warn">Warning</option><option value="error">Error</option></select>
          <select className="sm" value={dF} onChange={(e) => setDF(e.target.value)}><option value="">All drones</option>{run.drones.map((d: any) => <option key={d.drone_id} value={d.drone_id}>{d.drone_id}</option>)}</select></h3>
          <div className="log mono">{evs.slice(0, 80).map((e) => <div key={e.id} className={'e ' + e.sev}><span className="mut">{e.t}</span>{e.drone ? <span className="d">{dname(e.drone)}</span> : <span className="d mut">{e.cat}</span>}<span>{e.msg}</span></div>)}{!evs.length && <span className="mut">No events match.</span>}</div></div>
        <div className="card"><h3>Failure schedule</h3>
          {run.failure_schedule_type || run.failure_scenario_id
            ? <><p className="mut">{run.failure_schedule_type === 'custom' ? 'Custom user-authored plan' : run.failure_scenario_id} · scheduled relative to mission start</p>
              {!!run.failure_events?.length && <table><thead><tr><th>Event</th><th>Type</th><th>Start</th><th>End</th><th>Status</th></tr></thead><tbody>
                {run.failure_events.map((event: any) => <tr key={event.id}><td className="mono">{event.id}</td><td>{event.type}</td><td className="mono">{event.start_s}s</td><td className="mono">{event.end_s == null ? 'never' : `${event.end_s}s`}</td><td>{event.status}</td></tr>)}
              </tbody></table>}
            </>
            : <p className="mut">No failure schedule is installed for this run.</p>}
          <p className="mut" style={{ fontSize: 10.5, margin: '8px 0 0' }}>An unresponsive drone is marked disconnected. Other event types show their lifecycle only; controller, partition, packet-loss, delay, battery, and no-fly effects are not simulated.</p></div>
        <div className="card sys"><h3>System status</h3>
          <div className="sys-grid">
            <div className="r">Coordination mode<b className="badge">{run.coordination_mode ?? s.mode}</b></div>
            <div className="r">◇ Total aircraft<b>{run.drones.length}</b></div>
            <div className="r">◉ Active missions<b>{inProg}</b></div>
            <div className="r">⇄ Ownership conflicts<b className={s.obs.dupNow ? 'c-r' : ''}>{s.obs.dupNow}</b></div>
          </div>
          <div className={'sysok ' + sysCls}>● {discN ? `${discN} DRONE(S) DISCONNECTED` : s.obs.dupNow ? 'CONFLICTS UNRESOLVED' : 'All systems normal'}</div>
          {s.obs.firstDisc != null && <div className="mono" style={{ fontSize: 11, marginTop: 6 }}>{s.obs.recovered != null ? <span className="c-g">Converged: recovered in {s.obs.recovered} ticks</span> : <span className="c-r">Not converged — still disconnected</span>}</div>}
        </div>
      </div>
    </div>
  )
}