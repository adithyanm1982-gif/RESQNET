import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import MapView from '../components/MapView'
import { DroneIcon } from '../components/Icons'
import { useStore } from '../store'
import { label, latlon } from '../geo'
import { batteryOf, connOf, dname, healthOf, mmss } from '../lib'
import { batClass } from '../batteryColor'

const FAIL: [string, string, string][] = [['controller_outage', 'Disable central controller', 'danger'], ['network_partition', 'Inject network partition', 'danger'], ['drone_unresponsive', 'Disconnect drone', 'danger'], ['restore_connectivity', 'Restore connectivity', '']]
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
      <span className="mono mut" style={{ fontSize: 11 }}>{s.mode.toUpperCase()}{run ? ` · ${mmss(run.tick * s.secPerTick)}` : ''}</span>
    </div>)

  if (!run) return (
    <div className="mc" style={{ gridTemplateRows: 'minmax(0,1fr)' }}>
      <div className="col"><div className="card fill"><h3>Active aircraft</h3><p className="mut">Drones appear here once a run is created from the backend.</p></div></div>
      <MapView>{ctl}<div className="overlay"><div className="card" style={{ width: 360 }}>
        <h3>No active run</h3>
        <div style={{ display: 'grid', gap: 10 }}>
          <label className="f">Scenario<select value={s.scenarioId} onChange={(e) => s.setScenario(e.target.value)}>{s.scenarios.map((x: any) => <option key={x.scenario_id} value={x.scenario_id}>{x.name}</option>)}</select></label>
          <label className="f">Mode<select value={s.mode} onChange={(e) => s.setMode(e.target.value)}><option value="centralized">Centralized</option><option value="decentralized">Decentralized</option><option value="hybrid">Hybrid RESQNET</option></select></label>
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
        <div className="card"><h3>Failure injection</h3>
          <div style={{ display: 'grid', gap: 6 }}>
            {FAIL.map(([t, l, c]) => <button key={t} className={c + ' sm'} disabled={s.archived} onClick={() => s.inject(t, t === 'drone_unresponsive' ? { drone_id: s.selected || run.drones[0]?.drone_id } : {})}>{t === 'drone_unresponsive' ? `${l} ${s.selected || run.drones[0]?.drone_id}` : l}</button>)}</div>
          {s.lastInjection && <div className={s.lastInjection.ok ? 'okbox' : 'err'} style={{ marginTop: 8, fontSize: 11 }}><b>{s.lastInjection.type}</b>: {s.lastInjection.ok ? 'backend accepted — ' : 'backend error — '}<span className="mono">{s.lastInjection.text}</span></div>}
          <p className="mut" style={{ fontSize: 10.5, margin: '8px 0 0' }}>Sent to POST /api/simulations/&#1f1f1f;run&#232323;/failures. The backend's real reply or error is shown — including failed recovery. Scripted failure: {s.plan.type === 'none' ? 'none' : `${s.plan.type} @ tick ${s.plan.tick}`}.</p></div>
        <div className="card"><h3>Mission status</h3>
          <div className="mono" style={{ lineHeight: 1.7, fontSize: 12 }}>Elapsed {mmss(run.tick * s.secPerTick)} · Remaining tasks {total - done}<br />Coverage {run.coverage.percentage}% ({run.coverage.visited_cells}/{run.coverage.traversable_cells})</div>
          <div className="meter"><i style={{ width: `${total ? (done / total) * 100 : 0}%`, background: 'var(--cy)' }} /></div>
          <div style={{ marginTop: 6 }}>{topTasks.map((t: any) => { const st = t.status === 'completed' ? '' : t.status === 'blocked' ? 'blocked' : t.status === 'pending' ? 'pending' : 'active'
            return <div className="ms" key={t.task_id}><span className={'ck ' + st}>{st === '' ? '✓' : st === 'blocked' ? '!' : st === 'pending' ? '…' : '▶'}</span><div><small>{t.task_id} · P{t.priority}</small><span className="mut" style={{ fontSize: 11 }}>{t.status} · {(t.assigned_to || []).join(', ') || 'unassigned'}</span></div></div> })}</div>
          {(run.candidate_detections || []).length > 0 && <p className="mut" style={{ fontSize: 11 }}>Unverified candidates: {(run.candidate_detections || []).filter((c: any) => c.verification_status !== 'confirmed').length} (observations, not confirmed rescues)</p>}
        </div>
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