

import { batClass } from '../batteryColor'

import { useEffect, useRef, useState } from 'react'

import maplibregl from 'maplibre-gl'

import 'maplibre-gl/dist/maplibre-gl.css'

import { useStore } from '../store'

import { cellPoly, center, toLngLat } from '../geo'

import { batteryOf, dname, healthOf, rowsOf } from '../lib'

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

): HTMLElement {

  const root = document.createElement('div')



  root.style.cssText = [

    'width:280px',

    'max-width:280px',

    'max-height:380px',

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

  title.textContent = `${hazard.drone_id} · ${hazard.timeframe}`

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

  const source = document.createElement('div')

  source.textContent =

    `Source: ${hazard.analysis_source || 'Saved analysis'}`

  source.style.cssText =

    'margin-top:8px;color:#9ca3af;font-size:10px'

  root.appendChild(source)



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



  const [timeframe, setTimeframe] = useState('T1')

  const [hazardResults, setHazardResults] = useState<HazardAnalysis[]>([])

  const [hazardLoading, setHazardLoading] = useState(false)

  const [hazardError, setHazardError] = useState('')



  const scenarioId = run?.scenario_id

    ? scenarioForHazards(String(run.scenario_id))

    : ''



  // Load saved results only. This does not call Gemini again.

  useEffect(() => {

    let cancelled = false



    hazardsRef.current = []

    setHazardResults([])

    setHazardError('')



    // Close a previous scenario's popup when changing scenarios.

    popupRef.current?.remove()

    popupRef.current = null



    if (!scenarioId) {

      setHazardLoading(false)

      return

    }



    setHazardLoading(true)



    api

      .hazardResults(scenarioId, timeframe)

      .then((response: HazardResultsResponse) => {

        if (cancelled) return



        const results = Array.isArray(response.results)

          ? response.results

          : []



        hazardsRef.current = results

        setHazardResults(results)

      })

      .catch((error: unknown) => {

        if (cancelled) return



        hazardsRef.current = []

        setHazardResults([])



        setHazardError(

          error instanceof Error

            ? error.message

            : 'Could not load saved hazard results.',

        )

      })

      .finally(() => {

        if (!cancelled) setHazardLoading(false)

      })



    return () => {

      cancelled = true

    }

  }, [scenarioId, timeframe])



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



    m.on('load', () => {

      for (const source of ['cells', 'trails', 'tasks']) {

        m.addSource(source, {

          type: 'geojson',

          data: EMPTY,

        })

      }



      m.addLayer({

        id: 'cf',

        type: 'fill',

        source: 'cells',

        paint: {

          'fill-color': [

            'match',

            ['get', 'k'],

            'blocked',

            '#64748b',

            'restricted',

            '#f87171',

            'visited',

            '#38bdf8',

            'caution',

            '#fbbf24',

            '#60a5fa',

          ],

          'fill-opacity': [

            'match',

            ['get', 'k'],

            'blocked',

            0,

            'restricted',

            0.4,

            'visited',

            0.3,

            'caution',

            0.2,

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

        id: 'cz',

        type: 'line',

        source: 'cells',

        filter: ['==', ['get', 'k'], 'caution'],

        paint: {

          'line-color': '#fbbf24',

          'line-width': 1.4,

          'line-opacity': 0.9,

        },

      })



      m.addLayer({

        id: 'czl',

        type: 'line',

        source: 'cells',

        filter: ['==', ['get', 'k'], 'restricted'],

        paint: {

          'line-color': '#f87171',

          'line-width': 1.6,

        },

      })



      m.addLayer({

        id: 'cx',

        type: 'fill-extrusion',

        source: 'cells',

        filter: ['==', ['get', 'k'], 'blocked'],

        paint: {

          'fill-extrusion-color': '#64748b',

          'fill-extrusion-height': 16,

          'fill-extrusion-opacity': 0.85,

        },

      })



      m.addLayer({

        id: 'rx',

        type: 'fill-extrusion',

        source: 'cells',

        filter: ['==', ['get', 'k'], 'restricted'],

        paint: {

          'fill-extrusion-color': '#f87171',

          'fill-extrusion-height': 8,

          'fill-extrusion-opacity': 0.5,

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



      m.addLayer({

        id: 'tk',

        type: 'circle',

        source: 'tasks',

        paint: {

          'circle-radius': 6,

          'circle-color': [

            'match',

            ['get', 's'],

            'completed',

            '#34d399',

            'blocked',

            '#f87171',

            'pending',

            '#fbbf24',

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



  const draw = () => {

    const m = map.current



    if (!m || !ready.current || !run) return



    const g = run.grid

    const rows = rowsOf(g)

    const feats: any[] = []



    for (let y = 0; y < g.height; y++) {

      for (let x = 0; x < g.width; x++) {

        const c = rows[y]?.[x]



        let k =

          c === '#'

            ? 'blocked'

            : c === 'X'

              ? 'restricted'

              : visited.has(`${x},${y}`)

                ? 'visited'

                : 'unexplored'



        if (c !== 'X' && c !== '#') {

          outer: for (let dy = -1; dy <= 1; dy++) {

            for (let dx = -1; dx <= 1; dx++) {

              if (rows[y + dy]?.[x + dx] === 'X') {

                if (k !== 'visited') k = 'caution'

                break outer

              }

            }

          }

        }



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

          const popup = new maplibregl.Popup({
            closeButton: true,
            closeOnClick: false,
            closeOnMove: false,
            maxWidth: '320px',
            offset: 18,
          })
            .setLngLat(toLngLat(d.x + 0.5, d.y + 0.5))
            .setDOMContent(createHazardPopupContent(hazard))
            .addTo(map.current)

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



      p.e.className =

        `pin ${h} ${selected === d.drone_id ? 'sel' : ''}`



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



      if (hazard) {

        const color = priorityColor(hazard.priority_level)



        p.e.style.outline = `2px solid ${color}`

        p.e.style.outlineOffset = '2px'

        p.e.style.borderRadius = '6px'



        p.e.title =

          `${d.drone_id}: ${hazard.priority_label} priority · ` +

          `Risk ${hazard.simulated_risk_score} · Hover for details`

      } else {

        p.e.style.outline = ''

        p.e.style.outlineOffset = ''

        p.e.title =

          `${d.drone_id}: no saved hazard result for ${timeframe}`

      }

    }



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



    for (const c of run.candidate_detections || []) {

      if (!cands.current[c.id]) {

        const e = document.createElement('div')

        e.className = 'cand'

        e.title = `${c.id}: ${c.verification_status}`



        cands.current[c.id] = new maplibregl.Marker({

          element: e,

        })

          .setLngLat(toLngLat(c.x + 0.5, c.y + 0.5))

          .addTo(m)

      }

    }

  }



  useEffect(draw, [

    run,

    trails,

    visited,

    selected,

    handoffs,

    bat,

    hazardResults,

    timeframe,

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



      {/* Saved hazard timeframe selector */}

      <div

        className="glass"

        style={{

          position: 'absolute',

          top: 12,

          left: 12,

          zIndex: 5,

          padding: '8px 10px',

          display: 'flex',

          alignItems: 'center',

          gap: 8,

          color: '#e5e7eb',

          fontSize: 12,

        }}

      >

        <label htmlFor="hazard-timeframe">Hazard analysis</label>



        <select

          id="hazard-timeframe"

          value={timeframe}

          onChange={(event) => setTimeframe(event.target.value)}

          style={{

            background: '#111827',

            color: '#f9fafb',

            border: '1px solid #475569',

            borderRadius: 5,

            padding: '5px 7px',

          }}

        >

          <option value="T1">T1</option>

          <option value="T2">T2</option>

          <option value="T3">T3</option>

        </select>



        <span>

          {hazardLoading

            ? 'Loading…'

            : `${hazardResults.length} results`}

        </span>

      </div>



      {hazardError && (

        <div

          className="glass"

          role="status"

          style={{

            position: 'absolute',

            top: 58,

            left: 12,

            zIndex: 5,

            maxWidth: 300,

            padding: 8,

            color: '#fca5a5',

            fontSize: 11,

            overflowWrap: 'anywhere',

          }}

        >

          Could not load saved hazards: {hazardError}

        </div>

      )}



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

            <i style={{ background: '#64748b' }} />

            Blocked (obstacle)

          </span>



          <span>

            <i style={{ background: '#f87171' }} />

            Restricted zone (RZ)

          </span>



          <span>

            <i style={{ border: '1px dashed #fbbf24' }} />

            Caution (next to RZ)

          </span>



          <span>

            <i className="ln" />

            Flight path

          </span>



          {dot('#34d399', 'Task done')}

          {dot('#38bdf8', 'Task active')}

          {dot('#fbbf24', 'Task pending')}

          {dot('#f87171', 'Task blocked')}



          <span>H Task handoff</span>

          <span>◯ Drone healthy</span>

          <span>┅ Low battery</span>

          <span>■ Link lost</span>



          <hr />



          <strong>Hazard priority outlines</strong>

          {dot('#34d399', 'Low priority')}

          {dot('#fbbf24', 'Medium priority')}

          {dot('#fb923c', 'High priority')}

          {dot('#f87171', 'Critical priority')}



          <span>Hover over a drone to view saved analysis.</span>

          <span>Use the popup close button to dismiss the analysis.</span>

        </div>

      )}

    </div>

  )

}
