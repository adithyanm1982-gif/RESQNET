import { useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import { useStore } from './store'
import ThemeToggle from './components/ThemeToggle'
import Home from './pages/Home'
import Scenarios from './pages/Scenarios'
import Mission from './pages/Mission'
import Experiments from './pages/Experiments'
import Analytics from './pages/Analytics'
import Settings from './pages/Settings'

const tabs = [['/', 'HOME'], ['/mission', 'MISSION CONTROL'], ['/scenarios', 'SCENARIOS'], ['/experiments', 'EXPERIMENTS'], ['/analytics', 'ANALYTICS'], ['/settings', 'SETTINGS']]
export default function App() {
  const boot = useStore((s) => s.boot); const health = useStore((s) => s.health); const run = useStore((s) => s.run)
  const [now, setNow] = useState(new Date())
  useEffect(() => { boot() }, [])
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t) }, [])
  const ok = health === 'ok' || health === 'db-offline'
  return (
    <div className="app">
      <header className="top">
        <div className="brand">RESQ<b>NET</b><small>MISSION CONTROL</small></div><div className="sep" />
        <nav>{tabs.map(([to, l]) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => (isActive ? 'on' : '')}>{l}</NavLink>)}</nav>
        <div className="top-r">
          <span className="mono mut">{run ? `TICK ${run.tick}` : 'NO RUN'}</span>
          <span className="clock mono">{now.toLocaleTimeString('en-GB')}</span>
          <span><span className={'dot ' + (ok ? 'g' : 'r')} /><span className="mono">{health === 'ok' ? 'CONNECTED' : health === 'db-offline' ? 'API ONLINE · DB OFFLINE' : health.toUpperCase()}</span></span>
          <ThemeToggle />
          <NavLink className="gear" to="/settings" title="Settings">⚙</NavLink>
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Home />} /><Route path="/scenarios" element={<Scenarios />} />
          <Route path="/mission" element={<Mission />} /><Route path="/experiments" element={<Experiments />} />
          <Route path="/analytics" element={<Analytics />} /><Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  )
}