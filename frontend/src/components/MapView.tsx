import { batClass } from '../batteryColor'
import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useStore } from '../store'
import { cellPoly, center, toLngLat } from '../geo'
import { batteryOf, dname, healthOf } from '../lib'
import { droneSvg } from './Icons'
import { api } from '../api'

const EMPTY: any = {
  type: 'FeatureCollection',
  features: [],
}

const LAYERS: Record<string, string[]> = {
  grid: ['cl'],
  trails: ['tr'],
  tasks: ['tk'],
  zones: ['cf', 'cx', 'rx', 'cz', 'czl'],
}

const TRAIL = [
  '#38bdf8',
  '#22d3ee',
  '#818cf8',
  '#34d399',
  '#fbbf24',
  '#f472b6',
  '#a78bfa',
  '#60a5fa',
]

// Priority legend shown in the "i" panel: [level, meaning, hex]
const PRIORITY_LEGEND: [number, string, string][] = [
  [5, 'Life-threatening', '#ff1744'],
  [4, 'Critical', '#ff6d00'],
  [3, 'High', '#ffea00'],
  [2, 'Moderate', '#00e676'],
  [1, 'Low', '#00e5ff'],
]

// Saved image-analysis results (hover popup + drone priority) use one fixed set.
const TIMEFRAME = 'T1'

type HazardAnalysis = {
  scenario: string
  filename: string
  drone_id: string
  timeframe: string
  visible_hazards: string[]
  priority_level: number
  priority_label: string
  simulated_risk_score: number
  explanation: string
  confidence: number
  limitations: string | string[]
  analysis_source: string
  image_url: string
}

type HazardResultsResponse = {
  scenario: string
  timeframe: string
  count: number
  results: HazardAnalysis[]
}

type DronePin = {
  m: maplibregl.Marker
  e: HTMLElement
}

type Pt = { x: number; y: number }

const BACKEND_URL = (
  import.meta.env.VITE_BACKEND_URL || ''
).replace(/\/+$/, '')

function hazardImageUrl(path: string): string {
  if (!path) return ''

  if (/^https?:\/\//i.test(path)) {
    return path
  }

  return `${BACKEND_URL}${path.startsWith('/') ? path : `/${path}`}`
}

function scenarioForHazards(scenarioId: string): string {
  const value = scenarioId.toLowerCase()

  if (value.includes('cyclone')) return 'cyclone'
  if (value.includes('flood')) return 'flood'
  if (value.includes('earthquake')) return 'earthquake'

  return scenarioId
}

// Small screen-space offsets keep nearby drone icons and labels readable.
// These offsets affect marker presentation only; simulation coordinates and
// flight trails continue to use the real drone positions.
function droneMarkerOffset(droneId: string): [number, number] {
  const offsets: Record<string, [number, number]> = {
    D1: [-18, -16],
    D2: [18, -16],
    D3: [-18, 16],
    D4: [18, 16],
    D5: [0, -24],
    D6: [0, 24],
  }

  const match = droneId.match(/(\d+)$/)
  const key = match ? `D${Number(match[1])}` : droneId
  return offsets[key] ?? [0, 0]
}

// Extent of the projected grid quad along a scan line.
// axis 'y': scan line y = v -> returns [minX, maxX]
// axis 'x': scan line x = v -> returns [minY, maxY]
function quadSpan(q: Pt[], axis: 'x' | 'y', v: number): [number, number] | null {
  const key = axis === 'y' ? 'y' : 'x'
  const other = axis === 'y' ? 'x' : 'y'
  const vals = q.map((p) => p[key])
  const vv = Math.min(Math.max(v, Math.min(...vals)), Math.max(...vals))
  const hits: number[] = []

  for (let i = 0; i < q.length; i++) {
    const a = q[i]
    const b = q[(i + 1) % q.length]
    const a1 = a[key]
    const b1 = b[key]

    if ((a1 <= vv && vv <= b1) || (b1 <= vv && vv <= a1)) {
      if (a1 === b1) {
        hits.push(a[other], b[other])
      } else {
        hits.push(a[other] + ((vv - a1) * (b[other] - a[other])) / (b1 - a1))
      }
    }
  }

  return hits.length ? [Math.min(...hits), Math.max(...hits)] : null
}

function priorityColor(level: number): string {
  switch (level) {
    case 5:
      return '#ff1744'
    case 4:
      return '#ff6d00'
    case 3:
      return '#ffea00'
    case 2:
      return '#00e676'
    default:
      return '#00e5ff'
  }
}

function readableList(items: string[]): string {
  return items?.length ? items.join(', ') : 'No hazards listed'
}

function createHazardPopupContent(
  hazard: HazardAnalysis,
  maxHeight: number,
  coordinates: [number, number],
): HTMLElement {
  const root = document.createElement('div')

  root.style.cssText = [
    'width:280px',
    'max-width:280px',
    `max-height:${maxHeight}px`,
    'overflow:auto',
    'padding:8px',
    'box-sizing:border-box',
    'font-family:Arial,sans-serif',
    'color:#e5e7eb',
    'background:#111827',
    'font-size:12px',
    'line-height:1.5',
  ].join(';')

  const title = document.createElement('div')
  title.textContent = hazard.drone_id
  title.style.cssText =
    'font-size:15px;font-weight:700;margin-bottom:8px;color:#f9fafb'
  root.appendChild(title)

  const imageUrl = hazardImageUrl(hazard.image_url)

  if (imageUrl) {
    const image = document.createElement('img')

    image.src = imageUrl
    image.alt = `Observed area for ${hazard.drone_id}`
    image.loading = 'eager'
    image.style.cssText =
      'display:block;width:100%;max-height:160px;min-height:70px;' +
      'object-fit:contain;background:#030712;border-radius:6px;' +
      'margin-bottom:9px'

    image.onerror = () => {
      image.style.display = 'none'

      // Do not hide the entire popup if the image fails.
      if (!root.querySelector('.hazard-image-error')) {
        const message = document.createElement('div')
        message.className = 'hazard-image-error'
        message.textContent =
          `Image could not load. Check the image URL: ${imageUrl}`

        message.style.cssText =
          'padding:8px;background:#7f1d1d;color:#fecaca;' +
          'border-radius:5px;margin-bottom:8px;overflow-wrap:anywhere;'

        image.insertAdjacentElement('afterend', message)
      }
    }

    root.appendChild(image)
  } else {
    const message = document.createElement('div')
    message.textContent = 'No image URL was returned by the backend.'
    message.style.cssText =
      'padding:8px;background:#374151;border-radius:5px;margin-bottom:8px'
    root.appendChild(message)
  }

  const priority = document.createElement('div')
  priority.textContent =
    `Priority ${hazard.priority_level}: ${hazard.priority_label}`
  priority.style.cssText =
    `font-weight:700;color:${priorityColor(hazard.priority_level)};margin-bottom:5px`
  root.appendChild(priority)

  const coordinateLabel = document.createElement('div')
  coordinateLabel.textContent = `Coordinates: ${coordinates[1].toFixed(6)}, ${coordinates[0].toFixed(6)}`
  coordinateLabel.style.marginBottom = '5px'
  root.appendChild(coordinateLabel)

  const risk = document.createElement('div')
  risk.textContent = `Risk score: ${hazard.simulated_risk_score}`
  risk.style.marginBottom = '5px'
  root.appendChild(risk)

  const confidence = document.createElement('div')
  confidence.textContent =
    `Confidence: ${(hazard.confidence * 100).toFixed(1)}%`
  confidence.style.marginBottom = '5px'
  root.appendChild(confidence)

  const hazardsTitle = document.createElement('div')
  hazardsTitle.textContent = 'Visible hazards'
  hazardsTitle.style.cssText = 'font-weight:700;margin-top:7px'
  root.appendChild(hazardsTitle)

  const hazardsText = document.createElement('div')
  hazardsText.textContent = readableList(hazard.visible_hazards || [])
  root.appendChild(hazardsText)

  const explanationTitle = document.createElement('div')
  explanationTitle.textContent = 'Analysis'
  explanationTitle.style.cssText = 'font-weight:700;margin-top:7px'
  root.appendChild(explanationTitle)

  const explanation = document.createElement('div')
  explanation.textContent =
    hazard.explanation || 'No explanation available.'
  root.appendChild(explanation)

  const limitationsText = Array.isArray(hazard.limitations)
    ? hazard.limitations.join('; ')
    : hazard.limitations || ''

  if (limitationsText) {
    const limitationsTitle = document.createElement('div')
    limitationsTitle.textContent = 'Limitations'
    limitationsTitle.style.cssText = 'font-weight:700;margin-top:7px'
    root.appendChild(limitationsTitle)

    const limitations = document.createElement('div')
    limitations.textContent = limitationsText
    root.appendChild(limitations)
  }

  return root
}

export default function MapView({
  children,
}: {
  children?: any
}) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const ready = useRef(false)

  const pins = useRef<Record<string, DronePin>>({})
  const cands = useRef<Record<string, maplibregl.Marker>>({})
  const extra = useRef<maplibregl.Marker[]>([])

  const hazardsRef = useRef<HazardAnalysis[]>([])
  const popupRef = useRef<maplibregl.Popup | null>(null)
  const fitRef = useRef<() => void>(() => {})

  const {
    run,
    trails,
    visited,
    selected,
    select,
    handoffs,
    bat,
    basemap,
  } = useStore()

  const [vis, setVis] = useState<Record<string, boolean>>({
    grid: true,
    trails: true,
    tasks: true,
    zones: true,
  })

  const [is3d, setIs3d] = useState(true)
  const [info, setInfo] = useState(false)

  const [hazardResults, setHazardResults] = useState<HazardAnalysis[]>([])

  const scenarioId = run?.scenario_id
    ? scenarioForHazards(String(run.scenario_id))
    : ''

  // Load saved image-analysis results only. This does not call Gemini again.
  useEffect(() => {
    let cancelled = false

    hazardsRef.current = []
    setHazardResults([])
    useStore.getState().setHazards({})

    // Close a previous scenario's popup when changing scenarios.
    popupRef.current?.remove()
    popupRef.current = null

    if (!scenarioId) return

    api
      .hazardResults(scenarioId, TIMEFRAME)
      .then((response: HazardResultsResponse) => {
        if (cancelled) return

        const results = Array.isArray(response.results)
          ? response.results
          : []

        hazardsRef.current = results
        setHazardResults(results)

        // Share per-drone priority with the Mission Control side panel.
        useStore.getState().setHazards(
          Object.fromEntries(
            results.map((item) => [
              item.drone_id,
              {
                priority_level: item.priority_level,
                priority_label: item.priority_label,
              },
            ]),
          ),
        )
      })
      .catch(() => {
        if (cancelled) return

        hazardsRef.current = []
        setHazardResults([])
        useStore.getState().setHazards({})
      })

    return () => {
      cancelled = true
    }
  }, [scenarioId])

  useEffect(() => {
    if (!el.current) return

    const m = new maplibregl.Map({
      container: el.current,
      center: center(20, 20),
      zoom: 16.5,
      pitch: 60,
      bearing: -18,
      maxPitch: 80,
      style: {
        version: 8,
        sources: {
          sat: {
            type: 'raster',
            tileSize: 256,
            maxzoom: 19,
            tiles: [
              'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
            ],
            attribution: 'Imagery © Esri',
          },
          dark: {
            type: 'raster',
            tileSize: 256,
            maxzoom: 16,
            tiles: [
              'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
            ],
            attribution: 'Tiles © Esri',
          },
        },
        layers: [
          {
            id: 'bg',
            type: 'background',
            paint: { 'background-color': '#0b0b0d' },
          },
          {
            id: 'sat',
            type: 'raster',
            source: 'sat',
            paint: {
              'raster-brightness-max': 1,
              'raster-saturation': 0,
              'raster-contrast': 0,
            },
          },
          {
            id: 'dark',
            type: 'raster',
            source: 'dark',
            paint: { 'raster-saturation': -0.3 },
            layout: { visibility: 'none' },
          },
        ],
      } as any,
    })

    m.addControl(
      new maplibregl.ScaleControl({ unit: 'metric' }),
      'bottom-left',
    )

    // Keep drone labels inside the 20x20 grid while zooming / panning / tilting.
    m.on('move', () => fitRef.current())
    m.on('resize', () => fitRef.current())

    m.on('load', () => {
      for (const source of ['cells', 'trails', 'tasks']) {
        m.addSource(source, {
          type: 'geojson',
          data: EMPTY,
        })
      }

      // Every cell is drawn as a normal blue grid cell (unexplored / visited).
      m.addLayer({
        id: 'cf',
        type: 'fill',
        source: 'cells',
        paint: {
          'fill-color': [
            'match',
            ['get', 'k'],
            'visited',
            '#38bdf8',
            '#60a5fa',
          ],
          'fill-opacity': [
            'match',
            ['get', 'k'],
            'visited',
            0.3,
            0.09,
          ],
        },
      })

      m.addLayer({
        id: 'cl',
        type: 'line',
        source: 'cells',
        paint: {
          'line-color': '#7dd3fc',
          'line-opacity': 0.25,
          'line-width': 0.6,
        },
      })

      m.addLayer({
        id: 'tr',
        type: 'line',
        source: 'trails',
        paint: {
          'line-color': ['get', 'c'],
          'line-width': 2.4,
          'line-dasharray': [2, 2],
        },
      })

      // Pending (yellow) task dots are hidden; other task dots stay.
      m.addLayer({
        id: 'tk',
        type: 'circle',
        source: 'tasks',
        filter: ['!=', ['get', 's'], 'pending'],
        paint: {
          'circle-radius': 6,
          'circle-color': [
            'match',
            ['get', 's'],
            'completed',
            '#34d399',
            'blocked',
            '#f87171',
            '#38bdf8',
          ],
          'circle-stroke-width': 2,
          'circle-stroke-color': '#ffffff',
        },
      })

      ready.current = true
      draw()
    })

    map.current = m

    return () => {
      popupRef.current?.remove()
      popupRef.current = null

      m.remove()
      map.current = null
      ready.current = false

      pins.current = {}
      cands.current = {}
      extra.current = []
    }
  }, [])

  // Shift each drone marker (icon + label) so it stays fully inside the
  // projected 20x20 grid. Presentation only: simulation coordinates and
  // trails are untouched.
  const fitPins = () => {
    const m = map.current

    if (!m || !ready.current || !run) return

    const g = run.grid

    const quad: Pt[] = [
      toLngLat(0, 0),
      toLngLat(g.width, 0),
      toLngLat(g.width, g.height),
      toLngLat(0, g.height),
    ].map((ll: any) => m.project(ll))

    const PAD = 2

    for (const d of run.drones) {
      const p = pins.current[d.drone_id]

      if (!p) continue

      const base = droneMarkerOffset(d.drone_id)
      const c = m.project(toLngLat(d.x + 0.5, d.y + 0.5) as any)
      const ic = p.e.querySelector('.ic') as HTMLElement | null
      const lb = p.e.querySelector('.lb') as HTMLElement | null
      const w = ic && lb ? ic.offsetWidth + lb.offsetWidth - 6 : 120
      const h = ic && lb ? Math.max(ic.offsetHeight, lb.offsetHeight) : 34

      // Marker anchor is 'left': the pin's left edge sits at point + offset.x,
      // vertically centred on point + offset.y.
      let left = c.x + base[0]
      let top = c.y + base[1] - h / 2

      for (let pass = 0; pass < 2; pass++) {
        const r1 = quadSpan(quad, 'y', top)
        const r2 = quadSpan(quad, 'y', top + h)

        if (r1 && r2) {
          const lo = Math.max(r1[0], r2[0]) + PAD
          const hi = Math.min(r1[1], r2[1]) - PAD

          if (hi - lo >= w) left = Math.min(Math.max(left, lo), hi - w)
        }

        const c1 = quadSpan(quad, 'x', left)
        const c2 = quadSpan(quad, 'x', left + w)

        if (c1 && c2) {
          const lo = Math.max(c1[0], c2[0]) + PAD
          const hi = Math.min(c1[1], c2[1]) - PAD

          if (hi - lo >= h) top = Math.min(Math.max(top, lo), hi - h)
        }
      }

      p.m.setOffset([left - c.x, top + h / 2 - c.y])
    }
  }

  fitRef.current = fitPins

  const draw = () => {
    const m = map.current

    if (!m || !ready.current || !run) return

    const g = run.grid
    const feats: any[] = []

    for (let y = 0; y < g.height; y++) {
      for (let x = 0; x < g.width; x++) {
        // Restricted / blocked / caution cells are shown as normal blue grid.
        const k = visited.has(`${x},${y}`) ? 'visited' : 'unexplored'

        feats.push({
          type: 'Feature',
          properties: { k },
          geometry: {
            type: 'Polygon',
            coordinates: [cellPoly(x, y)],
          },
        })
      }
    }

    const cellsSource = m.getSource('cells') as
      | maplibregl.GeoJSONSource
      | undefined

    cellsSource?.setData({
      type: 'FeatureCollection',
      features: feats,
    })

    const col = (id: string) =>
      TRAIL[
        Math.max(
          0,
          run.drones.findIndex((d: any) => d.drone_id === id),
        ) % TRAIL.length
      ] || '#38bdf8'

    const trailsSource = m.getSource('trails') as
      | maplibregl.GeoJSONSource
      | undefined

    trailsSource?.setData({
      type: 'FeatureCollection',
      features: Object.entries(trails)
        .filter(([, t]: any) => t.length > 1)
        .map(([id, t]: any) => ({
          type: 'Feature',
          properties: { c: col(id) },
          geometry: {
            type: 'LineString',
            coordinates: t.map(([x, y]: any) =>
              toLngLat(x + 0.5, y + 0.5),
            ),
          },
        })),
    })

    const tasksSource = m.getSource('tasks') as
      | maplibregl.GeoJSONSource
      | undefined

    tasksSource?.setData({
      type: 'FeatureCollection',
      features: run.tasks.map((t: any) => ({
        type: 'Feature',
        properties: { s: t.status },
        geometry: {
          type: 'Point',
          coordinates: toLngLat(t.x + 0.5, t.y + 0.5),
        },
      })),
    })

    for (const d of run.drones) {
      const ll = toLngLat(d.x + 0.5, d.y + 0.5)
      let p = pins.current[d.drone_id]

      if (!p) {
        const e = document.createElement('div')

        e.onclick = () => select(d.drone_id)

        // Keep the popup open while the pointer moves from the drone
        // into the popup. Close it after leaving both areas.
        let popupCloseTimer: ReturnType<typeof setTimeout> | undefined
        let activePopup: maplibregl.Popup | null = null

        const cancelPopupClose = () => {
          if (popupCloseTimer) {
            clearTimeout(popupCloseTimer)
            popupCloseTimer = undefined
          }
        }

        const schedulePopupClose = () => {
          cancelPopupClose()
          popupCloseTimer = setTimeout(() => {
            if (activePopup && popupRef.current === activePopup) {
              activePopup.remove()
              popupRef.current = null
            }
            activePopup = null
          }, 250)
        }

        e.addEventListener('mouseenter', () => {
          cancelPopupClose()

          const hazard = hazardsRef.current.find(
            (item) => item.drone_id === d.drone_id,
          )

          if (!hazard || !map.current) return

          if (activePopup) activePopup.remove()
          if (popupRef.current) popupRef.current.remove()
          popupRef.current = null

          // Place the popup on the side of the drone with more room and cap
          // its height so it always stays inside the map window.
          const mm = map.current
          const pt = mm.project(toLngLat(d.x + 0.5, d.y + 0.5) as any)
          const box = mm.getContainer()
          const W = box.clientWidth
          const H = box.clientHeight
          const margin = 8
          const popW = 310

          const above = pt.y - margin
          const below = H - pt.y - margin
          const vert = above > below ? 'bottom' : 'top'
          const space = Math.max(above, below)
          const maxH = Math.max(110, Math.min(380, space - 56))

          const horiz =
            pt.x < popW / 2 + margin
              ? '-left'
              : pt.x > W - popW / 2 - margin
                ? '-right'
                : ''

          const popup = new maplibregl.Popup({
            closeButton: true,
            closeOnClick: false,
            closeOnMove: false,
            maxWidth: '320px',
            offset: 18,
            anchor: (vert + horiz) as any,
          })
            .setLngLat(toLngLat(d.x + 0.5, d.y + 0.5))
            .setDOMContent(
              createHazardPopupContent(
                hazard,
                maxH,
                toLngLat(d.x + 0.5, d.y + 0.5),
              ),
            )
            .addTo(mm)

          activePopup = popup
          popupRef.current = popup

          const popupElement = popup.getElement()
          popupElement.addEventListener('mouseenter', cancelPopupClose)
          popupElement.addEventListener('mouseleave', schedulePopupClose)

          popup.on('close', () => {
            cancelPopupClose()
            if (popupRef.current === popup) popupRef.current = null
            if (activePopup === popup) activePopup = null
          })
        })

        e.addEventListener('mouseleave', schedulePopupClose)

        p = {
          e,
          m: new maplibregl.Marker({
            element: e,
            anchor: 'left',
            offset: droneMarkerOffset(d.drone_id),
          })
            .setLngLat(ll)
            .addTo(m),
        }

        pins.current[d.drone_id] = p
      }

      const b = batteryOf(d, bat)
      const h = healthOf(d, b.v)

      p.m.setLngLat(ll)

      // Keep maplibre's own marker classes (position:absolute); only swap state classes.
      p.e.classList.add('maplibregl-marker', 'pin')
      p.e.classList.remove('ok', 'warn', 'bad', 'sel')
      p.e.classList.add(h)
      if (selected === d.drone_id) p.e.classList.add('sel')

      p.e.innerHTML =
        `<span class="ic">${droneSvg(17)}</span>` +
        `<span class="lb"><b></b><i></i></span>`

      const name = p.e.querySelector('b')!
      const status = p.e.querySelector('i')!

      name.textContent = dname(d.drone_id)

      status.textContent =
        d.status === 'disconnected'
          ? 'NO LINK'
          : `${d.task_id ?? 'idle'} • ${b.v}%${b.est ? '*' : ''}`

      status.className =
        d.status === 'disconnected'
          ? ''
          : batClass(b.v)

      const hazard = hazardsRef.current.find(
        (item) => item.drone_id === d.drone_id,
      )

      // Priority colour is drawn as a small square on the drone icon only.
      p.e.style.outline = ''
      p.e.style.outlineOffset = ''
      p.e.style.borderRadius = ''
      const icon = p.e.querySelector('.ic') as HTMLElement | null

      if (hazard) {
        const color = priorityColor(hazard.priority_level)

        if (icon) {
          icon.style.borderRadius = '7px'
          icon.style.border = `2px solid ${color}`
          icon.style.boxShadow = `0 0 0 2px ${color}55, 0 0 10px ${color}99`
        }

        p.e.title =
          `${d.drone_id}: ${hazard.priority_label} priority · ` +
          `Risk ${hazard.simulated_risk_score} · Hover for details`
      } else {
        p.e.title = `${d.drone_id}: no saved priority data`
      }
    }

    // Keep every drone marker + label inside the grid.
    fitPins()

    extra.current.forEach((x) => x.remove())
    extra.current = []

    for (
      const h of handoffs
        .filter((x) => run.tick - x.tick <= 25)
        .slice(0, 3)
    ) {
      const e = document.createElement('div')

      e.className = 'hpin'
      e.innerHTML = '<div class="c">H</div><div class="t"></div>'

      e.querySelector('.t')!.textContent =
        `${h.task}: ${h.from}→${h.to}`

      extra.current.push(
        new maplibregl.Marker({ element: e })
          .setLngLat(toLngLat(h.x + 0.5, h.y + 0.5))
          .addTo(m),
      )
    }

    // Candidate-detection (yellow) markers are intentionally not drawn.
  }

  useEffect(draw, [
    run,
    trails,
    visited,
    selected,
    handoffs,
    bat,
    hazardResults,
  ])

  useEffect(() => {
    if (run) return

    popupRef.current?.remove()
    popupRef.current = null

    Object.values(pins.current).forEach((p) => p.m.remove())
    Object.values(cands.current).forEach((p) => p.remove())
    extra.current.forEach((x) => x.remove())

    pins.current = {}
    cands.current = {}
    extra.current = []
  }, [run])

  useEffect(() => {
    const d = run?.drones.find(
      (x: any) => x.drone_id === selected,
    )

    if (d) {
      map.current?.easeTo({
        center: toLngLat(d.x + 0.5, d.y + 0.5),
        zoom: 18,
        duration: 600,
      })
    }
  }, [selected])

  useEffect(() => {
    const m = map.current

    if (!m || !ready.current) return

    m.setLayoutProperty(
      'sat',
      'visibility',
      basemap === 'satellite' ? 'visible' : 'none',
    )

    m.setLayoutProperty(
      'dark',
      'visibility',
      basemap === 'dark' ? 'visible' : 'none',
    )
  }, [basemap, run])

  useEffect(() => {
    const m = map.current

    if (!m || !ready.current) return

    for (const [k, ids] of Object.entries(LAYERS)) {
      for (const id of ids) {
        if (m.getLayer(id)) {
          m.setLayoutProperty(
            id,
            'visibility',
            vis[k] ? 'visible' : 'none',
          )
        }
      }
    }
  }, [vis, run])

  const m3 = (on: boolean) => {
    setIs3d(on)

    map.current?.easeTo({
      pitch: on ? 60 : 0,
      bearing: on ? -18 : 0,
      duration: 700,
    })
  }

  const tg = (k: string) =>
    setVis((v) => ({ ...v, [k]: !v[k] }))

  const dot = (c: string, t: string) => (
    <span>
      <b style={{ color: c }}>●</b> {t}
    </span>
  )

  return (
    <div className="mapbox">
      <div className="map" ref={el} />

      <div className="tb-l glass">
        {[
          ['grid', '▦', 'Search grid'],
          ['trails', '⤳', 'Flight paths'],
          ['tasks', '◎', 'Tasks'],
          ['zones', '⬢', 'Zones & obstacles'],
        ].map(([k, i, t]) => (
          <button
            key={k}
            title={t}
            className={vis[k] ? 'on' : ''}
            onClick={() => tg(k)}
          >
            {i}
          </button>
        ))}
      </div>

      {children}

      <div className="tb-r glass">
        <button
          className={is3d ? 'on' : ''}
          style={
            is3d
              ? { borderColor: 'var(--cy)', color: 'var(--cy)' }
              : {}
          }
          onClick={() => m3(!is3d)}
        >
          3D
        </button>

        <button
          title="Fit mission area"
          onClick={() =>
            map.current?.easeTo({
              center: center(20, 20),
              zoom: 16.5,
              duration: 700,
            })
          }
        >
          ⛶
        </button>
      </div>

      <div className="zoom glass">
        <button onClick={() => map.current?.zoomIn()}>＋</button>
        <button onClick={() => map.current?.zoomOut()}>－</button>

        <button
          title="Reset north"
          onClick={() =>
            map.current?.easeTo({
              bearing: 0,
              duration: 500,
            })
          }
        >
          ➤
        </button>

        <button
          title="Center on selected drone"
          onClick={() => {
            const d = run?.drones.find(
              (x: any) => x.drone_id === selected,
            )

            if (d) {
              map.current?.easeTo({
                center: toLngLat(d.x + 0.5, d.y + 0.5),
                zoom: 18,
                duration: 600,
              })
            }
          }}
        >
          ◉
        </button>
      </div>

      <button
        className={'infobtn' + (info ? ' on' : '')}
        title={info ? 'Hide map legend' : 'Show map legend'}
        aria-label="Toggle map legend"
        aria-pressed={info}
        onClick={() => setInfo((v) => !v)}
      >
        i
      </button>

      {info && (
        <div className="legend glass">
          <span>
            <i
              style={{
                background: '#60a5fa22',
                border: '1px solid #60a5fa',
              }}
            />
            Unexplored
          </span>

          <span>
            <i style={{ background: '#38b8d8aa' }} />
            Explored
          </span>

          <span>
            <i className="ln" />
            Flight path
          </span>

          {dot('#34d399', 'Task done')}
          {dot('#38bdf8', 'Task active')}
          {dot('#f87171', 'Task blocked')}

          <span>┅ Low battery</span>
          <span>■ Link lost</span>

          <hr style={{ gridColumn: '1 / -1', width: '100%', margin: '2px 0' }} />

          <div style={{ gridColumn: '1 / -1', display: 'grid', gap: 4 }}>
            <strong>Drone priority level</strong>
            {PRIORITY_LEGEND.map(([level, meaning, hex]) => (
              <span key={level}>
                <i
                  style={{
                    background: hex,
                    border: `1px solid ${hex}`,
                    width: 12,
                    height: 12,
                    borderRadius: 3,
                  }}
                />
                <b>{level}</b> · {meaning}
                <span
                  className="mono"
                  style={{ marginLeft: 'auto', opacity: 0.75 }}
                >
                  {hex}
                </span>
              </span>
            ))}
          </div>

          <span>Hover over a drone to view saved analysis.</span>
          <span>Use the popup close button to dismiss the analysis.</span>
        </div>
      )}
    </div>
  )
}