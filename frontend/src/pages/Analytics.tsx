import { batClass } from '../batteryColor'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Area, AreaChart, CartesianGrid, Cell, Legend, Line, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useStore } from '../store'
import { batteryOf, dl, dname, healthOf, toCsv } from '../lib'
import { tip, usePal } from '../theme'
const PAGE = 10
// gradient pairs [top, bottom] for each task status
const PG: Record<string, [string, string]> = { completed: ['#38bdf8', '#2563eb'], pending: ['#a5b4fc', '#6366f1'], blocked: ['#fca5a5', '#dc2626'], 'in progress': ['#5eead4', '#0d9488'] }
export default function Analytics() {
  const P = usePal(); const TT = tip(P)
  const legend = <Legend formatter={(val: any) => <span style={{ color: P.axis }}>{val}</span>} />
  const s = useStore(); const { run, covHistory, saved, events } = s; const nav = useNavigate()
  const [sev, setSev] = useState<Record<string, boolean>>({ info: true, warn: true, error: true })
  const [cat, setCat] = useState(''); const [drone, setDrone] = useState(''); const [q, setQ] = useState(''); const [pg, setPg] = useState(0)
  const [nCat, setNCat] = useState('Note'); const [nTxt, setNTxt] = useState('')
  const cats = useMemo(() => [...new Set(events.map((e) => e.cat))], [events])
  const f = events.filter((e) => sev[e.sev] && (!cat || e.cat === cat) && (!drone || e.drone === drone) && (!q || (e.msg + e.cat).toLowerCase().includes(q.toLowerCase())))
  const pages = Math.max(1, Math.ceil(f.length / PAGE)); const cur = Math.min(pg, pages - 1)
  const cnt = (k: string) => events.filter((e) => e.sev === k).length
  const taskPie = run ? ['completed', 'pending', 'blocked'].map((k) => ({ name: k, value: run.tasks.filter((t: any) => t.status === k).length })).concat([{ name: 'in progress', value: run.tasks.filter((t: any) => !['completed', 'pending', 'blocked'].includes(t.status)).length }]).filter((x) => x.value) : []
  const evCsv = () => dl('resqnet_events.csv', toCsv([['time', 'tick', 'severity', 'category', 'drone', 'message'], ...f.map((e) => [e.iso, e.tick, e.sev, e.cat, e.drone, e.msg])]), 'text/csv')
  const runsCsv = () => dl('resqnet_runs.csv', toCsv([['run_id', 'scenario', 'mode', 'tick', 'coverage', 'completed', 'total_tasks', 'blocked', 'recovery', 'duplicates', 'safety', 'saved_at'], ...saved.map((r: any) => [r.run_id, r.scenario_id, r.mode, r.tick, r.coverage, r.completed, r.total_tasks, r.blocked, r.recovery, r.duplicates, r.safety, r.saved_at])]), 'text/csv')
  const strip = (r: any) => { const { detail, ...x } = r; return x }
  const open = async (id: string) => { if (await s.openSaved(id)) nav('/mission') }
  return (
    <div className="page">
      <div className="row"><div style={{ flex: 1 }}><h1><b>Analytics</b> & event reports</h1><p className="sub">Metrics, event timeline and saved runs — all from backend state.</p></div>
        <button disabled={!run} onClick={s.saveRun}>Save current run</button>
        <button disabled={!run} onClick={() => run && dl(`run_${run.run_id.slice(0, 8)}_summary.json`, JSON.stringify({ summary: strip({ run_id: run.run_id, scenario_id: run.scenario_id, mode: s.mode, tick: run.tick, coverage: run.coverage, observed: s.obs }), events: s.events }, null, 2), 'application/json')}>Export run summary (JSON)</button></div>
      <div className="kpis">
        {[['Info', cnt('info'), P.k.info], ['Warnings', cnt('warn'), P.k.warn], ['Errors', cnt('error'), P.k.err], ['Coverage', run ? `${run.coverage.percentage}%` : '—', P.k.cov], ['Duplicates seen', s.obs.dup, P.k.dup], ['Safety violations', s.obs.safety, P.k.safe], ['Recovery', s.obs.recovered != null ? `${s.obs.recovered}t` : s.obs.firstDisc != null ? 'FAILED' : '—', P.k.rec]].map(([l, v, c]) => <div className="card kpi" key={l as string}><span className="v" style={{ color: c as string }}>{v}</span><span className="l">{l}</span></div>)}</div>
      <div className="grid2" style={{ gridTemplateColumns: '2fr 1fr' }}>
        <div className="card" style={{ height: 320 }}><h3>Coverage, tasks & connectivity over time</h3>
          {covHistory.length ? <ResponsiveContainer width="100%" height="88%"><AreaChart data={covHistory}>
            <defs>
              <linearGradient id="a" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#38bdf8" stopOpacity={.55} /><stop offset="1" stopColor="#2563eb" stopOpacity={0} /></linearGradient>
              <linearGradient id="aStroke" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stopColor="#22d3ee" /><stop offset="1" stopColor="#3b82f6" /></linearGradient>
            </defs>
            <CartesianGrid stroke={P.grid} strokeDasharray="3 3" /><XAxis dataKey="tick" stroke={P.axis} /><YAxis stroke={P.axis} /><Tooltip {...TT} />{legend}
            <Area dataKey="cov" name="Coverage %" stroke="url(#aStroke)" strokeWidth={2.5} fill="url(#a)" /><Line dataKey="done" name="Tasks done" stroke={P.line.done} strokeWidth={2} dot={false} /><Line dataKey="disc" name="Disconnected drones" stroke={P.line.disc} strokeWidth={2} strokeDasharray="5 3" dot={false} /><Line dataKey="dup" name="Conflicts" stroke={P.line.conf} strokeWidth={2} strokeDasharray="1 3" dot={false} /></AreaChart></ResponsiveContainer> : <p className="mut">Start a mission to see live metrics.</p>}</div>
        <div className="card" style={{ height: 320 }}><h3>Task status</h3>
          {run ? <ResponsiveContainer width="100%" height="88%"><PieChart>
            <defs>{Object.entries(PG).map(([k, [a, b]]) => <linearGradient key={k} id={'pg-' + k.replace(' ', '-')} x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor={a} /><stop offset="1" stopColor={b} /></linearGradient>)}</defs>
            <Pie data={taskPie} dataKey="value" innerRadius={55} outerRadius={85} paddingAngle={3} cornerRadius={5} label={{ fill: P.tipText, fontSize: 11 }}>{taskPie.map((d) => <Cell key={d.name} fill={`url(#pg-${d.name.replace(' ', '-')})`} stroke={P.pieStroke} strokeWidth={2} />)}</Pie><Tooltip {...TT} />{legend}</PieChart></ResponsiveContainer> : <p className="mut">No run.</p>}</div>
      </div>
      <div className="card"><h3>Fleet health</h3>
        {run ? <div className="grid3">{run.drones.map((d: any) => { const b = batteryOf(d, s.bat); const h = healthOf(d, b.v); return <div key={d.drone_id}><div className="row"><b>{dname(d.drone_id)}</b><span className="grow" /><span className={'pill ' + h}>{d.status}</span><span className={'mono ' + batClass(b.v)}>{b.v}%{b.est ? '*' : ''}</span></div><div className="meter"><i className={batClass(b.v)} style={{ width: `${b.v}%` }} /></div></div> })}</div> : <p className="mut">No run.</p>}</div>

      <div className="card"><div className="row"><h3 style={{ margin: 0, flex: 1 }}>Event timeline ({f.length}/{events.length})</h3><button className="sm" disabled={!f.length} onClick={evCsv}>Export CSV</button><button className="sm" disabled={!f.length} onClick={() => dl('resqnet_events.json', JSON.stringify(f, null, 2), 'application/json')}>Export JSON</button></div>
        <div className="row" style={{ margin: '10px 0' }}>
          {(['info', 'warn', 'error'] as const).map((k) => <span key={k} className={`chip ${k} ${sev[k] ? 'on' : ''}`} onClick={() => { setSev({ ...sev, [k]: !sev[k] }); setPg(0) }}>{k.toUpperCase()}</span>)}
          <select value={cat} onChange={(e) => { setCat(e.target.value); setPg(0) }}><option value="">All categories</option>{cats.map((c) => <option key={c}>{c}</option>)}</select>
          <select value={drone} onChange={(e) => { setDrone(e.target.value); setPg(0) }}><option value="">All drones</option>{(run?.drones || []).map((d: any) => <option key={d.drone_id} value={d.drone_id}>{d.drone_id}</option>)}</select>
          <input placeholder="Search events…" value={q} onChange={(e) => { setQ(e.target.value); setPg(0) }} /></div>
        <div style={{ overflow: 'auto' }}><table><thead><tr><th>Severity</th><th>Time</th><th>Tick</th><th>Category</th><th>Drone</th><th>Event</th></tr></thead><tbody>
          {f.slice(cur * PAGE, cur * PAGE + PAGE).map((e) => <tr key={e.id} className={'sevrow ' + e.sev}><td>{e.sev.toUpperCase()}</td><td className="mono">{e.t}</td><td className="mono">{e.tick}</td><td>{e.cat}</td><td className="mono">{e.drone ?? '—'}</td><td>{e.msg}</td></tr>)}</tbody></table></div>
        {!f.length && <p className="mut">No events match the filters.</p>}
        <div className="row" style={{ justifyContent: 'flex-end', marginTop: 8 }}><button className="sm" disabled={cur === 0} onClick={() => setPg(cur - 1)}>‹</button><span className="mono mut">{cur + 1} / {pages}</span><button className="sm" disabled={cur >= pages - 1} onClick={() => setPg(cur + 1)}>›</button></div>
        <div className="row" style={{ marginTop: 10, borderTop: '1px solid var(--line)', paddingTop: 10 }}>
          <input style={{ flex: 1, minWidth: 200 }} placeholder="Log an operator note…" value={nTxt} onChange={(e) => setNTxt(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { s.addNote(nCat, nTxt); setNTxt('') } }} />
          <select value={nCat} onChange={(e) => setNCat(e.target.value)}>{['Note', 'Command', 'Incident', 'Recovery'].map((c) => <option key={c}>{c}</option>)}</select>
          <button className="primary" onClick={() => { s.addNote(nCat, nTxt); setNTxt('') }}>Log</button></div></div>

      <div className="card"><div className="row"><h3 style={{ margin: 0, flex: 1 }}>Saved runs ({saved.length})</h3>
        <button className="sm" disabled={!saved.length} onClick={runsCsv}>Export CSV</button><button className="sm" disabled={!saved.length} onClick={() => dl('resqnet_runs.json', JSON.stringify(saved.map(strip), null, 2), 'application/json')}>Export JSON</button><button className="sm danger" disabled={!saved.length} onClick={s.clearSaved}>Clear</button></div>
        <div style={{ overflow: 'auto' }}><table><thead><tr><th>Run</th><th>Scenario</th><th>Mode</th><th>Tick</th><th>Coverage</th><th>Tasks</th><th>Recovery</th><th>Dup.</th><th>Safety</th><th>Saved</th><th /></tr></thead><tbody>
          {saved.map((r: any) => <tr key={r.run_id}><td className="mono">{r.run_id.slice(0, 8)}</td><td>{r.scenario_id}</td><td>{r.mode}</td><td className="mono">{r.tick}</td><td className="mono">{r.coverage}%</td><td className="mono">{r.completed}/{r.total_tasks}</td><td className="mono">{r.recovery ?? '—'}</td><td className="mono">{r.duplicates ?? '—'}</td><td className="mono">{r.safety ?? '—'}</td><td className="mut">{new Date(r.saved_at).toLocaleString()}</td>
            <td><div className="row" style={{ flexWrap: 'nowrap' }}><button className="sm" onClick={() => open(r.run_id)}>Reopen</button><button className="sm" onClick={() => dl(`run_${r.run_id.slice(0, 8)}.json`, JSON.stringify(r, null, 2), 'application/json')}>JSON</button><button className="sm danger" onClick={() => s.deleteSaved(r.run_id)}>✕</button></div></td></tr>)}</tbody></table></div>
        {!saved.length && <p className="mut">No saved runs yet. Completed missions are saved automatically; you can also save manually.</p>}</div>
    </div>)
}