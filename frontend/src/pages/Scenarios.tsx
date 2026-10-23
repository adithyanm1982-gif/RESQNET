import { useNavigate } from 'react-router-dom'
import PlanEditor from '../components/PlanEditor'
import { useStore } from '../store'
const MODES: [string, string, string][] = [['centralized', 'Centralized', 'A single controller assigns every task. Efficient, but a controller outage stalls the fleet.'], ['decentralized', 'Decentralized', 'Drones coordinate locally. Resilient, but risks duplicate work and conflicts.'], ['hybrid', 'Hybrid RESQNET', 'Central planning with local fallback when the network fails, then state reconciliation.']]
const icon = (t: string) => /flood|water/i.test(t) ? '🌊' : /earth|quake|collapse/i.test(t) ? '🏚' : /fire/i.test(t) ? '🔥' : '⚠'
export default function Scenarios() {
  const { scenarios, scenarioId, setScenario, mode, setMode, start, error, busy, failScen, failId, setFailScenario } = useStore()
  const fs = failScen.find((x: any) => x.failure_scenario_id === failId)
  const nav = useNavigate(); const go = async () => { await start(); nav('/mission') }
  return (
    <div className="page">
      <div><h1>Select <b>scenario</b></h1><p className="sub">Disaster layouts, obstacles and failure conditions. Grid, blocked cells and drones come from the backend.</p></div>
      {error && <div className="err">{error}</div>}
      <div className="grid3">
        {scenarios.map((s: any) => (
          <div key={s.scenario_id} className={'card scn ' + (s.scenario_id === scenarioId ? 'on' : '')} onClick={() => setScenario(s.scenario_id)}>
            <h3><span style={{ fontSize: 20 }}>{icon(s.disaster_type + ' ' + s.name)}</span>{s.name}</h3>
            <div className="mut">Type: {s.disaster_type}</div>
            <div className="kpis" style={{ marginTop: 10, gridTemplateColumns: 'repeat(2,1fr)' }}>
              {[['Grid', `${s.width}×${s.height}`], ['Drones', s.drone_count], ['Tasks', s.task_count], ['Candidates', s.candidate_detection_count]].map(([l, v]) => <div className="kpi" key={l as string}><span className="v" style={{ fontSize: 18 }}>{v}</span><span className="l">{l}</span></div>)}</div>
          </div>))}
        {!scenarios.length && !error && <div className="mut">Loading scenarios from backend…</div>}
      </div>
      <div className="card"><h3>Coordination mode</h3>
        <div className="grid3">{MODES.map(([v, l, d]) => <div key={v} className={'card scn ' + (mode === v ? 'on' : '')} onClick={() => setMode(v)}><b>{l}</b><p className="mut" style={{ margin: '6px 0 0' }}>{d}</p></div>)}</div></div>
      <div className="card"><h3>Failure condition</h3>
        <label className="f" style={{ marginBottom: 10 }}>Failure scenario (from failure_scenarios.json)
          <select value={failId} onChange={(e) => setFailScenario(e.target.value)}><option value="">— custom (set below) —</option>{failScen.map((x: any) => <option key={x.failure_scenario_id} value={x.failure_scenario_id}>{x.title}</option>)}</select></label>
        {fs && <div style={{ marginBottom: 12 }}><p style={{ margin: '0 0 6px' }}>{fs.description} <span className="mut">Tests: {fs.tests}.</span></p>
          {!!fs.events.length && <table><thead><tr><th>Event</th><th>Type</th><th>Start (s)</th><th>End (s)</th><th>Detail</th></tr></thead><tbody>{fs.events.map((e: any) => <tr key={e.id}><td className="mono">{e.id}</td><td>{e.type}</td><td className="mono">{e.start_s}</td><td className="mono">{e.end_s ?? 'never'}</td><td className="mut">{e.drone_id ? `drone ${e.drone_id}` : e.groups ? e.groups.map((g: any) => `${g.group_id}: ${g.drone_ids.join('/')}${g.has_controller_link ? ' (controller)' : ''}`).join(' · ') : e.scope ?? ''}</td></tr>)}</tbody></table>}
          <p className="mut" style={{ margin: '6px 0 0' }}>Expected checks: {fs.expected_checks.join(' · ')}. The first controller / partition / drone event below is loaded into the editor (1 tick = {useStore.getState().droneCfg?.meta?.units?.tick_s ?? 2} s); other event types (packet loss, delay, battery, no-fly) are shown for reference — the backend simulation does not apply them.</p></div>}
        <PlanEditor />
        <p className="mut">Mission Control injects this automatically when the tick is reached (and restores connectivity if set); Experiments applies the identical condition to all three modes. Requests go to the backend's failures endpoint — its real reply or error is displayed.</p></div>
      <div className="row"><button className="primary" disabled={!scenarioId || busy} onClick={go}>{busy ? 'Creating run…' : '▶ Analyze & Start Mission'}</button></div>
    </div>)
}
