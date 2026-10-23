import { useState } from 'react'
import { useStore } from '../store'
export default function Settings() {
  const s = useStore()
  const a = (() => { try { return JSON.parse(localStorage.getItem('rq_anchor') || '') } catch { return null } })()
  const [lat, setLat] = useState(String(a?.lat ?? import.meta.env.VITE_MAP_LAT ?? '-37.8140')); const [lng, setLng] = useState(String(a?.lng ?? import.meta.env.VITE_MAP_LNG ?? '145.1230'))
  return (
    <div className="page">
      <div><h1><b>Settings</b></h1><p className="sub">Simulation speed, seed and configuration.</p></div>
      <div className="grid2">
        <div className="card" style={{ display: 'grid', gap: 12 }}><h3>Simulation</h3>
          <label className="f">Step interval (ms)<input type="number" min={100} step={100} value={s.speedMs} onChange={(e) => s.setSpeed(Math.max(100, +e.target.value))} /></label>
          <label className="f">Ticks advanced per step<input type="number" min={1} max={50} value={s.ticksPerStep} onChange={(e) => s.setTicksPerStep(Math.min(50, Math.max(1, +e.target.value)))} /></label>
          <label className="f">Seconds shown per tick (elapsed-time display)<input type="number" min={1} value={s.secPerTick} onChange={(e) => s.setSecPerTick(Math.max(1, +e.target.value))} /></label></div>
        <div className="card" style={{ display: 'grid', gap: 12, alignContent: 'start' }}><h3>Map</h3>
          <div className="seg" style={{ width: 'fit-content' }}>{(['satellite', 'dark'] as const).map((b) => <button key={b} className={s.basemap === b ? 'on' : ''} onClick={() => s.setBasemap(b)}>{b === 'satellite' ? '3D Satellite' : 'Dark map'}</button>)}</div>
          <div className="row"><label className="f">Cell (0,0) latitude<input value={lat} onChange={(e) => setLat(e.target.value)} /></label><label className="f">longitude<input value={lng} onChange={(e) => setLng(e.target.value)} /></label></div>
          <button style={{ width: 'fit-content' }} onClick={() => { localStorage.setItem('rq_anchor', JSON.stringify({ lat: +lat, lng: +lng })); location.reload() }}>Apply & reload</button></div>
      </div>
    </div>)
}