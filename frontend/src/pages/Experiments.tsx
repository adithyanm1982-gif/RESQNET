import { useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import PlanEditor from '../components/PlanEditor'
import { useStore } from '../store'
import { dl, toCsv } from '../lib'
import { tip, usePal } from '../theme'
const NAME: any = { centralized: 'Centralized-only', decentralized: 'Decentralized-only', hybrid: 'Hybrid RESQNET' }
const v = (x: any) => (x == null ? '—' : String(x))
// gradient definitions: returned as a plain <defs> element so Recharts renders it inside the chart
const grads = (p: string) => <defs>
  <linearGradient id={p + 'Blue'} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#60a5fa" /><stop offset="1" stopColor="#2563eb" /></linearGradient>
  <linearGradient id={p + 'Teal'} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#5eead4" /><stop offset="1" stopColor="#0d9488" /></linearGradient>
  <linearGradient id={p + 'Indigo'} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#a5b4fc" /><stop offset="1" stopColor="#4f46e5" /></linearGradient>
  <linearGradient id={p + 'Green'} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#6ee7b7" /><stop offset="1" stopColor="#059669" /></linearGradient>
  <linearGradient id={p + 'Red'} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#fca5a5" /><stop offset="1" stopColor="#dc2626" /></linearGradient>
</defs>
export default function Experiments() {
  const P = usePal(); const TT = tip(P)
  const legend = <Legend formatter={(val: any) => <span style={{ color: P.axis }}>{val}</span>} />
  const { scenarioId, scenarios, comparison, compare, saveComparison, busy, error, cmpProgress, plan } = useStore()
  const [ticks, setTicks] = useState(200)
  const sc = scenarios.find((x: any) => x.scenario_id === scenarioId)
  const best = (k: string, hi: boolean) => { const vals = comparison.map((r: any) => r[k]).filter((x: any) => typeof x === 'number'); return vals.length ? (hi ? Math.max(...vals) : Math.min(...vals)) : null }
  const cls = (r: any, k: string, hi: boolean) => (best(k, hi) != null && r[k] === best(k, hi) ? 'best-c' : '')
  const rowsCsv = () => toCsv([['mode', 'run_id', 'coverage', 'completed', 'total_tasks', 'blocked', 'recovery', 'duplicates', 'comm_overhead', 'safety_violations', 'finished_tick', 'injection'], ...comparison.map((r: any) => [r.mode, r.run_id, r.coverage, r.completed, r.total_tasks, r.blocked, r.recovery, r.duplicates, r.comm, r.safety, r.finished, r.injection])])
  return (
    <div className="page">
      <div><h1>Compare <b>strategies</b></h1><p className="sub">Centralized-only vs decentralized-only vs Hybrid RESQNET — same scenario, tick budget and failure condition.</p></div>
      <div className="card"><div className="row" style={{ alignItems: 'flex-end' }}>
        <label className="f">Scenario<b style={{ color: 'var(--cy)', fontSize: 14 }}>{sc?.name ?? scenarioId ?? '—'}</b></label>
        <label className="f">Ticks per run<input type="number" min={1} max={1000} value={ticks} onChange={(e) => setTicks(+e.target.value)} style={{ width: 100 }} /></label>
        <PlanEditor />
        <button className="primary" disabled={busy || !scenarioId} onClick={() => compare(ticks)}>{busy ? 'Running…' : '▶ Run all three modes'}</button></div>
        {busy && <p className="mono c-c">{cmpProgress || 'starting…'}</p>}</div>
      {error && <div className="err">{error}</div>}
      {!!comparison.length && <>
        <div className="grid3">{comparison.map((r: any) => <div key={r.mode} className={'card cmpcard ' + (r.mode === 'hybrid' ? 'best' : '')}>
          <h3>{NAME[r.mode]}<span className="grow" />{r.finished != null && <span className="badge">finished @ {r.finished}</span>}</h3>
          <div className="kpis" style={{ gridTemplateColumns: 'repeat(2,1fr)' }}>
            <div className="kpi"><span className="v c-c">{r.coverage}%</span><span className="l">Coverage</span></div><div className="kpi"><span className="v c-g">{r.completed}/{r.total_tasks}</span><span className="l">Tasks</span></div>
            <div className="kpi"><span className={'v ' + (r.recovery === 'NOT RECOVERED' ? 'c-r' : '')} style={{ fontSize: 17 }}>{r.recovery}</span><span className="l">Recovery</span></div><div className="kpi"><span className="v c-a">{v(r.duplicates)}</span><span className="l">Duplicates</span></div></div>
          <p className={'mono ' + (/FAILED/.test(r.injection) ? 'c-r' : 'mut')} style={{ fontSize: 11 }}>Failure: {r.injection}</p></div>)}</div>
        <div className="card"><div className="row"><h3 style={{ margin: 0, flex: 1 }}>Metrics (underlined = best per metric)</h3>
          <button className="sm" onClick={saveComparison}>Save to run history</button><button className="sm" onClick={() => dl('resqnet_comparison.csv', rowsCsv(), 'text/csv')}>Export CSV</button><button className="sm" onClick={() => dl('resqnet_comparison.json', JSON.stringify(comparison, null, 2), 'application/json')}>Export JSON</button></div>
          <table><thead><tr><th>Mode</th><th>Coverage %</th><th>Tasks done</th><th>Blocked</th><th>Recovery time</th><th>Duplicate assign.</th><th>Comm. overhead</th><th>Safety violations</th></tr></thead>
            <tbody>{comparison.map((r: any) => <tr key={r.mode}><td><b>{NAME[r.mode]}</b></td><td className={'mono ' + cls(r, 'coverage', true)}>{r.coverage}</td><td className={'mono ' + cls(r, 'completed', true)}>{r.completed}/{r.total_tasks}</td><td className="mono">{r.blocked}</td>
              <td className={'mono ' + (r.recovery === 'NOT RECOVERED' ? 'c-r' : '')}>{r.recovery}</td><td className={'mono ' + cls(r, 'duplicates', false)}>{v(r.duplicates)}</td><td className="mono">{v(r.comm)}</td><td className={'mono ' + cls(r, 'safety', false)}>{v(r.safety)}</td></tr>)}</tbody></table>
          <p className="mut">"—" = the backend did not return it and it cannot be observed. Duplicates, safety violations (drone inside a restricted/blocked cell) and recovery time are taken from the backend's metrics when present, otherwise observed from the real tick states. Results are shown as returned, including cases where hybrid is not best. Failure: {plan.type === 'none' ? 'none' : `${plan.type} @ tick ${plan.tick}`}.</p></div>
        <div className="grid2">
          <div className="card" style={{ height: 300 }}><h3>Coverage & task completion</h3><ResponsiveContainer width="100%" height="88%"><BarChart data={comparison}>{grads('c1')}<CartesianGrid stroke={P.grid} strokeDasharray="3 3" /><XAxis dataKey="mode" stroke={P.axis} /><YAxis stroke={P.axis} /><Tooltip {...TT} />{legend}<Bar dataKey="coverage" name="Coverage %" fill="url(#c1Blue)" radius={[6, 6, 0, 0]} /><Bar dataKey="completed" name="Tasks done" fill="url(#c1Teal)" radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer></div>
          <div className="card" style={{ height: 300 }}><h3>Conflicts & safety</h3><ResponsiveContainer width="100%" height="88%"><BarChart data={comparison}>{grads('c2')}<CartesianGrid stroke={P.grid} strokeDasharray="3 3" /><XAxis dataKey="mode" stroke={P.axis} /><YAxis stroke={P.axis} allowDecimals={false} /><Tooltip {...TT} />{legend}<Bar dataKey="duplicates" name="Duplicate assignments" fill="url(#c2Indigo)" radius={[6, 6, 0, 0]} /><Bar dataKey="safety" name="Safety violations" fill="url(#c2Green)" radius={[6, 6, 0, 0]} /><Bar dataKey="blocked" name="Blocked tasks" fill="url(#c2Red)" radius={[6, 6, 0, 0]} /></BarChart></ResponsiveContainer></div></div></>}
    </div>)
}