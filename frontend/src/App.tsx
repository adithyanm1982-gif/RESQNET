import { useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { useStore } from './store'
import { useAuth } from './auth'
import RequireAuth from './components/RequireAuth'
import ProfileMenu from './components/ProfileMenu'
import ThemeToggle from './components/ThemeToggle'
import Login from './pages/Login'
import Home from './pages/Home'
import Scenarios from './pages/Scenarios'
import Mission from './pages/Mission'
import Experiments from './pages/Experiments'
import Analytics from './pages/Analytics'
import Settings from './pages/Settings'

const tabs = [['/', 'HOME'], ['/mission', 'MISSION CONTROL'], ['/scenarios', 'SCENARIOS'], ['/experiments', 'EXPERIMENTS'], ['/analytics', 'ANALYTICS'], ['/settings', 'SETTINGS']]

export default function App() {
  const boot = useStore((state) => state.boot)
  const health = useStore((state) => state.health)
  const booting = useStore((state) => state.booting)
  const run = useStore((state) => state.run)
  const initAuth = useAuth((state) => state.init)
  const authEnabled = useAuth((state) => state.enabled)
  const authStatus = useAuth((state) => state.status)
  const [now, setNow] = useState(new Date())

  useEffect(() => { void initAuth() }, [initAuth])
  useEffect(() => { if (authStatus === 'in') void boot() }, [authStatus, boot])
  useEffect(() => { const timer = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(timer) }, [])

  const appVisible = authEnabled === false || authStatus === 'in'
  const apiOnline = health === 'ok' || health === 'db-offline'
  const apiLabel = health === 'ok' ? 'API ONLINE' : health === 'db-offline' ? 'API ONLINE · DATABASE OFFLINE' : health.toUpperCase()
  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <img src="/favicon.png" alt="RESQNET logo" className="brand-logo" />
          <span className="brand-name">RESQ<b>NET</b></span>
          <small>MISSION CONTROL</small>
        </div><div className="sep" />
        {appVisible && <nav>{tabs.map(([path, label]) => <NavLink key={path} to={path} end={path === '/'} className={({ isActive }) => (isActive ? 'on' : '')}>{label}</NavLink>)}</nav>}
        <div className="top-r">
          {appVisible && <><span className="mono mut">{run ? `TICK ${run.tick}` : 'NO RUN'}</span><span className="clock mono">{now.toLocaleTimeString('en-GB')}</span></>}
          {appVisible && <span className="api-indicator" title="Backend API status"><span className={'dot ' + (apiOnline ? 'g' : 'r')} /><span className="mono">{apiLabel}</span></span>}
          <ThemeToggle />
          <ProfileMenu />
        </div>
      </header>
      {appVisible && booting && <div className="note" role="status">Loading scenarios, fleet settings, and failure schedules…</div>}
      <main>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<RequireAuth><Home /></RequireAuth>} />
          <Route path="/scenarios" element={<RequireAuth><Scenarios /></RequireAuth>} />
          <Route path="/mission" element={<RequireAuth><Mission /></RequireAuth>} />
          <Route path="/experiments" element={<RequireAuth><Experiments /></RequireAuth>} />
          <Route path="/analytics" element={<RequireAuth><Analytics /></RequireAuth>} />
          <Route path="/settings" element={<RequireAuth><Settings /></RequireAuth>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
