import { batClass } from '../batteryColor'
import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useStore } from '../store'
import { cellPoly, center, toLngLat } from '../geo'
import { batteryOf, dname, healthOf, rowsOf } from '../lib'
import { droneSvg } from './Icons'

const EMPTY: any = { type: 'FeatureCollection', features: [] }
const LAYERS: Record<string, string[]> = { grid: ['cl'], trails: ['tr'], tasks: ['tk'], zones: ['cf', 'cx', 'rx', 'cz', 'czl'] }
const TRAIL = ['#38bdf8', '#22d3ee', '#818cf8', '#34d399', '#fbbf24', '#f472b6', '#a78bfa', '#60a5fa']
export default function MapView({ children }: { children?: any }) {
  const el = useRef<HTMLDivElement>(null); const map = useRef<maplibregl.Map | null>(null)
  const ready = useRef(false); const pins = useRef<Record<string, { m: maplibregl.Marker; e: HTMLElement }>>({})
  const cands = useRef<Record<string, maplibregl.Marker>>({}); const extra = useRef<maplibregl.Marker[]>([])
  const { run, trails, visited, selected, select, handoffs, bat, basemap } = useStore()
  const [vis, setVis] = useState<Record<string, boolean>>({ grid: true, trails: true, tasks: true, zones: true })
  const [is3d, setIs3d] = useState(true)
  const [info, setInfo] = useState(false)

  useEffect(() => {
    const m = new maplibregl.Map({
      container: el.current!, center: center(20, 20), zoom: 16.5, pitch: 60, bearing: -18, maxPitch: 80,
      style: { version: 8, sources: {
        sat: { type: 'raster', tileSize: 256, maxzoom: 19, tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'], attribution: 'Imagery © Esri' },
        // Esri Dark Gray canvas: no API key needed, no watermark text
        dark: { type: 'raster', tileSize: 256, maxzoom: 16, tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}'], attribution: 'Tiles © Esri' } },
        layers: [
          { id: 'bg', type: 'background', paint: { 'background-color': '#0b0b0d' } },
          { id: 'sat', type: 'raster', source: 'sat', paint: { 'raster-brightness-max': 1, 'raster-saturation': 0, 'raster-contrast': 0 } },
          { id: 'dark', type: 'raster', source: 'dark', paint: { 'raster-saturation': -0.3 }, layout: { visibility: 'none' } }] } as any,
    })
    m.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left')
    m.on('load', () => {
      for (const s of ['cells', 'trails', 'tasks']) m.addSource(s, { type: 'geojson', data: EMPTY })
      m.addLayer({ id: 'cf', type: 'fill', source: 'cells', paint: { 'fill-color': ['match', ['get', 'k'], 'blocked', '#64748b', 'restricted', '#f87171', 'visited', '#38bdf8', 'caution', '#fbbf24', '#60a5fa'], 'fill-opacity': ['match', ['get', 'k'], 'blocked', 0, 'restricted', 0.4, 'visited', 0.3, 'caution', 0.2, 0.09] } })
      m.addLayer({ id: 'cl', type: 'line', source: 'cells', paint: { 'line-color': '#7dd3fc', 'line-opacity': 0.25, 'line-width': 0.6 } })
      m.addLayer({ id: 'cz', type: 'line', source: 'cells', filter: ['==', ['get', 'k'], 'caution'], paint: { 'line-color': '#fbbf24', 'line-width': 1.4, 'line-opacity': 0.9 } })
      m.addLayer({ id: 'czl', type: 'line', source: 'cells', filter: ['==', ['get', 'k'], 'restricted'], paint: { 'line-color': '#f87171', 'line-width': 1.6 } })
      m.addLayer({ id: 'cx', type: 'fill-extrusion', source: 'cells', filter: ['==', ['get', 'k'], 'blocked'], paint: { 'fill-extrusion-color': '#64748b', 'fill-extrusion-height': 16, 'fill-extrusion-opacity': 0.85 } })
      m.addLayer({ id: 'rx', type: 'fill-extrusion', source: 'cells', filter: ['==', ['get', 'k'], 'restricted'], paint: { 'fill-extrusion-color': '#f87171', 'fill-extrusion-height': 8, 'fill-extrusion-opacity': 0.5 } })
      m.addLayer({ id: 'tr', type: 'line', source: 'trails', paint: { 'line-color': ['get', 'c'], 'line-width': 2.4, 'line-dasharray': [2, 2] } })
      m.addLayer({ id: 'tk', type: 'circle', source: 'tasks', paint: { 'circle-radius': 6, 'circle-color': ['match', ['get', 's'], 'completed', '#34d399', 'blocked', '#f87171', 'pending', '#fbbf24', '#38bdf8'], 'circle-stroke-width': 2, 'circle-stroke-color': '#ffffff' } })
      ready.current = true; draw()
    })
    map.current = m
    return () => { m.remove(); map.current = null; ready.current = false; pins.current = {}; cands.current = {}; extra.current = [] }
  }, [])

  const draw = () => {
    const m = map.current; if (!m || !ready.current || !run) return
    const g = run.grid; const rows = rowsOf(g); const feats: any[] = []
    for (let y = 0; y < g.height; y++) for (let x = 0; x < g.width; x++) {
      const c = rows[y]?.[x]; let k = c === '#' ? 'blocked' : c === 'X' ? 'restricted' : visited.has(`${x},${y}`) ? 'visited' : 'unexplored'
      if (c !== 'X' && c !== '#') { outer: for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) if (rows[y + dy]?.[x + dx] === 'X') { if (k !== 'visited') k = 'caution'; break outer } }
      feats.push({ type: 'Feature', properties: { k }, geometry: { type: 'Polygon', coordinates: [cellPoly(x, y)] } })
    }
    ;(m.getSource('cells') as any).setData({ type: 'FeatureCollection', features: feats })
    const col = (id: string) => TRAIL[run.drones.findIndex((d: any) => d.drone_id === id) % 8] || '#38bdf8'
    ;(m.getSource('trails') as any).setData({ type: 'FeatureCollection', features: Object.entries(trails).filter(([, t]: any) => t.length > 1).map(([id, t]: any) => ({ type: 'Feature', properties: { c: col(id) }, geometry: { type: 'LineString', coordinates: t.map(([x, y]: any) => toLngLat(x + 0.5, y + 0.5)) } })) })
    ;(m.getSource('tasks') as any).setData({ type: 'FeatureCollection', features: run.tasks.map((t: any) => ({ type: 'Feature', properties: { s: t.status }, geometry: { type: 'Point', coordinates: toLngLat(t.x + 0.5, t.y + 0.5) } })) })
    for (const d of run.drones) {
      const ll = toLngLat(d.x + 0.5, d.y + 0.5); let p = pins.current[d.drone_id]
      if (!p) { const e = document.createElement('div'); e.onclick = () => select(d.drone_id); p = { e, m: new maplibregl.Marker({ element: e, anchor: 'left' }).setLngLat(ll).addTo(m) }; pins.current[d.drone_id] = p }
      const b = batteryOf(d, bat); const h = healthOf(d, b.v)
      p.m.setLngLat(ll); p.e.className = `pin ${h} ${selected === d.drone_id ? 'sel' : ''}`
      p.e.innerHTML = `<span class="ic">${droneSvg(17)}</span><span class="lb"><b></b><i></i></span>`
      p.e.querySelector('b')!.textContent = dname(d.drone_id)
      p.e.querySelector('i')!.textContent = d.status === 'disconnected' ? 'NO LINK' : `${d.task_id ?? 'idle'} • ${b.v}%${b.est ? '*' : ''}`
      p.e.querySelector('i')!.className = d.status === 'disconnected' ? '' : batClass(b.v)
    }
    extra.current.forEach((x) => x.remove()); extra.current = []
    for (const h of handoffs.filter((x) => run.tick - x.tick <= 25).slice(0, 3)) {
      const e = document.createElement('div'); e.className = 'hpin'; e.innerHTML = '<div class="c">H</div><div class="t"></div>'; e.querySelector('.t')!.textContent = `${h.task}: ${h.from}→${h.to}`
      extra.current.push(new maplibregl.Marker({ element: e }).setLngLat(toLngLat(h.x + 0.5, h.y + 0.5)).addTo(m))
    }
    for (const c of run.candidate_detections || []) if (!cands.current[c.id]) {
      const e = document.createElement('div'); e.className = 'cand'; e.title = `${c.id}: ${c.verification_status}`
      cands.current[c.id] = new maplibregl.Marker({ element: e }).setLngLat(toLngLat(c.x + 0.5, c.y + 0.5)).addTo(m)
    }
  }
  useEffect(draw, [run, trails, visited, selected, handoffs, bat])
  useEffect(() => { if (!run) { Object.values(pins.current).forEach((p) => p.m.remove()); Object.values(cands.current).forEach((p) => p.remove()); extra.current.forEach((x) => x.remove()); pins.current = {}; cands.current = {}; extra.current = [] } }, [run])
  useEffect(() => { const d = run?.drones.find((x: any) => x.drone_id === selected); if (d) map.current?.easeTo({ center: toLngLat(d.x + 0.5, d.y + 0.5), duration: 600 }) }, [selected])
  useEffect(() => { const m = map.current; if (!m || !ready.current) return
    m.setLayoutProperty('sat', 'visibility', basemap === 'satellite' ? 'visible' : 'none'); m.setLayoutProperty('dark', 'visibility', basemap === 'dark' ? 'visible' : 'none') }, [basemap, run])
  useEffect(() => { const m = map.current; if (!m || !ready.current) return
    for (const [k, ids] of Object.entries(LAYERS)) for (const id of ids) if (m.getLayer(id)) m.setLayoutProperty(id, 'visibility', vis[k] ? 'visible' : 'none') }, [vis, run])

  const m3 = (on: boolean) => { setIs3d(on); map.current?.easeTo({ pitch: on ? 60 : 0, bearing: on ? -18 : 0, duration: 700 }) }
  const tg = (k: string) => setVis((v) => ({ ...v, [k]: !v[k] }))
  const dot = (c: string, t: string) => <span><b style={{ color: c }}>●</b> {t}</span>
  return (
    <div className="mapbox">
      <div className="map" ref={el} />
      <div className="tb-l glass">{[['grid', '▦', 'Search grid'], ['trails', '⤳', 'Flight paths'], ['tasks', '◎', 'Tasks'], ['zones', '⬢', 'Zones & obstacles']].map(([k, i, t]) => <button key={k} title={t} className={vis[k] ? 'on' : ''} onClick={() => tg(k)}>{i}</button>)}</div>
      {children}
      <div className="tb-r glass"><button className={is3d ? 'on' : ''} style={is3d ? { borderColor: 'var(--cy)', color: 'var(--cy)' } : {}} onClick={() => m3(!is3d)}>3D</button><button title="Fit mission area" onClick={() => map.current?.easeTo({ center: center(20, 20), zoom: 16.5, duration: 700 })}>⛶</button></div>
      <div className="zoom glass"><button onClick={() => map.current?.zoomIn()}>＋</button><button onClick={() => map.current?.zoomOut()}>－</button><button title="Reset north" onClick={() => map.current?.easeTo({ bearing: 0, duration: 500 })}>➤</button><button title="Center on selected drone" onClick={() => { const d = run?.drones.find((x: any) => x.drone_id === selected); if (d) map.current?.easeTo({ center: toLngLat(d.x + 0.5, d.y + 0.5), zoom: 18, duration: 600 }) }}>◉</button></div>

      <button className={'infobtn' + (info ? ' on' : '')} title={info ? 'Hide map legend' : 'Show map legend'} aria-label="Toggle map legend" aria-pressed={info} onClick={() => setInfo((v) => !v)}>i</button>
      {info && <div className="legend glass">
        <span><i style={{ background: '#60a5fa22', border: '1px solid #60a5fa' }} />Unexplored</span><span><i style={{ background: '#38bdf8aa' }} />Explored</span>
        <span><i style={{ background: '#64748b' }} />Blocked (obstacle)</span><span><i style={{ background: '#f87171' }} />Restricted zone (RZ)</span>
        <span><i style={{ border: '1px dashed #fbbf24' }} />Caution (next to RZ)</span><span><i className="ln" />Flight path</span>
        {dot('#34d399', 'Task done')}{dot('#38bdf8', 'Task active')}
        {dot('#fbbf24', 'Task pending')}{dot('#f87171', 'Task blocked')}
        <span>H Task handoff</span><span>◯ Drone healthy</span>
        <span>┅ Low battery</span><span>■ Link lost</span>
      </div>}
    </div>
  )
}