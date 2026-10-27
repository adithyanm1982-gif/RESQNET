import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import MapView from '../components/MapView'
import { DroneIcon } from '../components/Icons'
import { useStore } from '../store'
import { label, latlon } from '../geo'
import { batteryOf, connOf, dname, healthOf, mmss } from '../lib'
import { batClass } from '../batteryColor'
import type { CoordinationMode } from '../api'

export default function Mission() {
  const s = useStore(); const { run } = s
  const [dF, setDF] = useState(''); const [sF, setSF] = useState('all')
  useEffect(() => {
    if (!s.running) return
    const id = setInterval(() => useStore.getState().step(), s.speedMs)
    return () => clearInterval(id)
  }, [s.running, s.speedMs])
  useEffect(() => { if (run && !s.archived && run.tasks.length && run.tasks.every((t: any) => t.status === 'completed') && s.running) { s.setRunning(false); s.saveRun() } }, [run])

  const ctl = (
    <div className="tb-c glass">
      {!run ? <button className="primary sm" disabled={!s.scenarioId || s.busy} onClick={s.start}>▶ Start</button> : <>
        <button className="primary sm" disabled={s.archived} onClick={() => s.setRunning(!s.running)}>{s.running ? '❚❚ Pause' : '▶ Resume'}</button>
        <button className="sm" disabled={s.running || s.busy || s.archived} onClick={() => s.step()}>Step</button>
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
      <div className="col"><div className="card fill"><h3>Alerts</h3><p className="mut">No alerts.</p></div></div>
    </div>)

  const done = run.completed_tasks.length; const total = run.tasks.length
  const unack = s.alerts.filter((a) => !a.ack).length; const discN = run.drones.filter((d: any) => !connOf(d)).length
  const sysCls = discN ? 'bad' : s.obs.dupNow || unack ? 'warn' : ''
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
  const last3 = s.handoffs.slice(0, 3).reverse()

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
        <div className="card sys"><h3>System status</h3>
          <div className="r">Coordination mode<b className="badge">{run.coordination_mode ?? s.mode}</b></div>
          <div className="r">◇ Total aircraft<b>{run.drones.length}</b></div><div className="r">◉ Active missions<b>{inProg}</b></div>
          <div className="r c-a">▲ Alerts<b>{unack}</b></div><div className="r">⇄ Ownership conflicts<b className={s.obs.dupNow ? 'c-r' : ''}>{s.obs.dupNow}</b></div>
          <div className={'sysok ' + sysCls}>● {discN ? `${discN} DRONE(S) DISCONNECTED` : s.obs.dupNow ? 'CONFLICTS UNRESOLVED' : 'All systems normal'}</div>
          {s.obs.firstDisc != null && <div className="mono" style={{ fontSize: 11, marginTop: 6 }}>{s.obs.recovered != null ? <span className="c-g">Converged: recovered in {s.obs.recovered} ticks</span> : <span className="c-r">Not converged — still disconnected</span>}</div>}
        </div>
      </div>

      <MapView>{ctl}
        {s.archived && <div className="arch glass">VIEWING SAVED RUN · READ-ONLY</div>}
        <div className="runinfo glass mono">TICK {run.tick} · {mmss(run.tick * s.secPerTick)} · COVERAGE {run.coverage.percentage}%</div>
      </MapView>

      <div className="col scroll">
        <div className="card"><h3><span className="grow">Alerts ({unack})</span></h3>
          <div className="alist" style={{ maxHeight: 190, overflow: 'auto' }}>
            {s.alerts.slice(0, 20).map((a) => <div key={a.id} className={'al ' + (a.ack ? 'ack' : '')} onClick={() => { s.ack(a.id); if (a.drone) s.select(a.drone) }} style={{ cursor: 'pointer' }}>
              <span className={'ai ' + a.sev}>{a.sev === 'error' ? '!' : a.sev === 'warn' ? '▲' : 'i'}</span><div><b>{a.title}</b><span>{a.detail}</span><br /><small>{a.t} · tick {a.tick}</small></div></div>)}
            {!s.alerts.length && <span className="mut">No alerts.</span>}</div>
          <button style={{ width: '100%', marginTop: 8 }} disabled={!unack} onClick={s.ackAll}>Acknowledge All</button></div>
        <div className="card"><h3>Failure schedule</h3>
          {run.failure_schedule_type || run.failure_scenario_id
            ? <><p className="mut">{run.failure_schedule_type === 'custom' ? 'Custom user-authored plan' : run.failure_scenario_id} · scheduled relative to mission start</p>
              {!!run.failure_events?.length && <table><thead><tr><th>Event</th><th>Type</th><th>Start</th><th>End</th><th>Status</th></tr></thead><tbody>
                {run.failure_events.map((event: any) => <tr key={event.id}><td className="mono">{event.id}</td><td>{event.type}</td><td className="mono">{event.start_s}s</td><td className="mono">{event.end_s == null ? 'never' : `${event.end_s}s`}</td><td>{event.status}</td></tr>)}
              </tbody></table>}
            </>
            : <p className="mut">No failure schedule is installed for this run.</p>}
          <p className="mut" style={{ fontSize: 10.5, margin: '8px 0 0' }}>An unresponsive drone is marked disconnected. Other event types show their lifecycle only; controller, partition, packet-loss, delay, battery, and no-fly effects are not simulated.</p></div>
        <div className="card"><h3>Mission status</h3>
          <div className="mono" style={{ lineHeight: 1.7, fontSize: 12 }}>Elapsed {mmss(run.tick * s.secPerTick)} · Remaining tasks {total - done}<br />Coverage {run.coverage.percentage}% ({run.coverage.visited_cells}/{run.coverage.traversable_cells})</div>
          <div className="meter"><i style={{ width: `${total ? (done / total) * 100 : 0}%`, background: 'var(--cy)' }} /></div>
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
        <div className="card"><h3><span className="grow">Battery status</span>
          <span className="mono" style={{ fontSize: 10, letterSpacing: 0.4, fontWeight: 600, textTransform: 'none', display: 'flex', gap: 10 }}>
            <span className="bat-high">● 60–100%</span><span className="bat-mid">● 30–59%</span><span className="bat-low">● 0–29%</span></span></h3>
          <div className="btiles">{run.drones.map((d: any) => { const b = batteryOf(d, s.bat); return <div className="bt" key={d.drone_id}><small>{dname(d.drone_id)}</small><b className={batClass(b.v)}>{b.v}%{b.est ? '*' : ''}</b><div className="meter"><i className={batClass(b.v)} style={{ width: `${b.v}%` }} /></div></div> })}</div></div>
        <div className="card"><h3>Mission handoffs</h3>
          {last3.length ? <div className="hchain">{last3.map((h, i) => <span key={h.id} className="row" style={{ flexWrap: 'nowrap', gap: 8 }}>
            <span className="hn"><span className="c f"><DroneIcon size={18} /></span>{dname(h.from)}<span className="mut">hands off {h.task}</span></span><span className="harrow">──▶</span>
            <span className="hn"><span className="c"><DroneIcon size={18} /></span>{dname(h.to)}<span className="mut">tick {h.tick}</span></span>{i < last3.length - 1 && <span className="mut">│</span>}</span>)}</div>
            : <p className="mut">No task reassignments observed yet. Handoffs appear when the backend moves task ownership between drones (e.g. during recovery).</p>}</div>
      </div>
    </div>
  )
}
