import { Link } from 'react-router-dom'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import MiniGrid from '../components/MiniGrid'
import { useStore } from '../store'
import { connOf } from '../lib'
import { tip, usePal } from '../theme'
export default function Home() {
  const P = usePal(); const TT = tip(P)
  const s = useStore(); const { run, saved, health, scenarios, alerts, comparison, events } = s
  const ok = health === 'ok' || health === 'db-offline'
  const steps: [string, boolean, string][] = [
    ['1 · Choose a scenario', !!s.scenarioId && !!scenarios.length, '/scenarios'], ['2 · Start the mission', !!run, '/mission'],
    ['3 · Inject a failure', events.some((e) => e.cat === 'Failure'), '/mission'], ['4 · Observe recovery & task ownership changes', s.handoffs.length > 0 || s.obs.recovered != null, '/mission'],
    ['5 · Reconnect & reconcile', s.obs.recovered != null && s.obs.dupNow === 0, '/mission'], ['6 · Compare against baselines', comparison.length === 3, '/experiments']]
  return (
    <div className="page">
      <div className="card" style={{ padding: 22, display: 'flex', gap: 24, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ flex: 1, minWidth: 280 }}>
          <h1>RESQ<b>NET</b></h1><p style={{ fontSize: 15, margin: '6px 0' }}>Resilient Swarm Coordination for Disaster Response</p>
          <p className="mut" style={{ maxWidth: 640 }}>Six drones search a 20 × 20 disaster grid under centralized, decentralized and hybrid coordination. Scenarios, drones and tasks are loaded live from the RESQNET backend. All values are simulation parameters, not real flight specifications.</p>
          <div className="row" style={{ marginTop: 14 }}><Link className="btn primary" to="/scenarios">Launch Simulation</Link><Link className="btn" to="/mission">Mission Control</Link><Link className="btn" to="/analytics">Previous experiments ({saved.length})</Link></div>
          {!ok && <div className="err" style={{ marginTop: 14 }}>Backend status: {health}. Start the backend (python -m uvicorn app.main:app --reload in the backend folder) and check VITE_BACKEND_URL in .env.</div>}
        </div>
        <MiniGrid run={run} visited={s.visited} size={230} />
      </div>
      <div className="kpis">
        {([['Backend', ok ? 'ONLINE' : health.toUpperCase(), ok ? 'c-g' : 'c-r'], ['Scenarios', scenarios.length, ''], ['Coverage', run ? `${run.coverage.percentage}%` : '—', 'c-c'],
          ['Tasks done', run ? `${run.completed_tasks.length}/${run.tasks.length}` : '—', 'c-g'], ['Fleet linked', run ? `${run.drones.filter(connOf).length}/${run.drones.length}` : '—', run && run.drones.some((d: any) => !connOf(d)) ? 'c-r' : 'c-g'],
          ['Open alerts', alerts.filter((a) => !a.ack).length, 'c-a'], ['Saved runs', saved.length, '']] as any[]).map(([l, v, c]) => <div className="card kpi" key={l}><span className={'v ' + c}>{v}</span><span className="l">{l}</span></div>)}
      </div>
      <div className="grid2">
        <div className="card"><h3>Demo flow (tracks real progress)</h3>
          {steps.map(([l, d, to]) => <Link key={l} to={to} className="ms" style={{ color: 'inherit', textDecoration: 'none' }}><span className={'ck ' + (d ? '' : 'pending')}>{d ? '✓' : '○'}</span><span>{l}</span></Link>)}</div>
        <div className="card"><h3>Recent alerts</h3><div className="alist">
          {alerts.slice(0, 5).map((a) => <div key={a.id} className={'al ' + (a.ack ? 'ack' : '')}><span className={'ai ' + a.sev}>{a.sev === 'error' ? '!' : a.sev === 'warn' ? '▲' : 'i'}</span><div><b>{a.title}</b><span>{a.detail}</span><br /><small>{a.t}</small></div></div>)}
          {!alerts.length && <span className="mut">No alerts. Start a mission to see live alerts.</span>}</div></div>
      </div>
      <div className="grid2">
        <div className="card" style={{ height: 270 }}><h3>Coverage over time (current run)</h3>
          {s.covHistory.length ? <ResponsiveContainer width="100%" height="85%"><AreaChart data={s.covHistory}><defs>
            <linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#38bdf8" stopOpacity={.55} /><stop offset="1" stopColor="#2563eb" stopOpacity={0} /></linearGradient>
            <linearGradient id="gStroke" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="#22d3ee" /><stop offset="1" stopColor="#3b82f6" /></linearGradient></defs>
            <CartesianGrid stroke={P.grid} strokeDasharray="3 3" /><XAxis dataKey="tick" stroke={P.axis} /><YAxis stroke={P.axis} /><Tooltip {...TT} /><Area dataKey="cov" name="Coverage %" stroke="url(#gStroke)" strokeWidth={2.5} fill="url(#g)" /></AreaChart></ResponsiveContainer> : <p className="mut">Start a mission to see live metrics.</p>}</div>
        <div className="card"><h3>Recent runs</h3><table><thead><tr><th>Run</th><th>Mode</th><th>Coverage</th><th>Tasks</th></tr></thead><tbody>
          {saved.slice(0, 5).map((r: any) => <tr key={r.run_id}><td className="mono">{r.run_id.slice(0, 8)}</td><td>{r.mode}</td><td className="mono">{r.coverage}%</td><td className="mono">{r.completed}/{r.total_tasks}</td></tr>)}</tbody></table>
          {!saved.length && <p className="mut">No saved runs yet.</p>}</div>
      </div>
    </div>)
}