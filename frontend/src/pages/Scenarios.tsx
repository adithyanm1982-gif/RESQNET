import { useNavigate } from 'react-router-dom'
import PlanEditor from '../components/PlanEditor'
import { useStore } from '../store'
import type { CoordinationMode } from '../api'
const MODES: [CoordinationMode, string, string][] = [['centralized', 'Centralized', 'A single controller assigns every task. Efficient, but a controller outage stalls the fleet.'], ['decentralized', 'Decentralized', 'Drones coordinate locally. Resilient, but risks duplicate work and conflicts.'], ['hybrid', 'Hybrid RESQNET', 'Central planning with local fallback when the network fails, then state reconciliation.']]
const icon = (t: string) => /flood|water/i.test(t) ? '🌊' : /earth|quake|collapse/i.test(t) ? '🏚' : /fire/i.test(t) ? '🔥' : '⚠'
export default function Scenarios() {
  const { scenarios, scenarioId, setScenario, mode, setMode, start, error, busy } = useStore()
  const nav = useNavigate(); const go = async () => { if (await start()) nav('/mission') }
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
      <div className="card"><h3>Failure plan</h3>
        <PlanEditor />
        <p className="mut">The selected predefined schedule or validated custom plan is installed after run creation and before the first tick. Experiment comparisons apply the same plan to each mode.</p></div>
      <div className="row"><button className="primary" disabled={!scenarioId || busy} onClick={go}>{busy ? 'Creating run…' : '▶ Analyze & Start Mission'}</button></div>
    </div>)
}
