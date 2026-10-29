import { batClass } from '../batteryColor'
import { useEffect, useRef, useState } from 'react'
import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useStore } from '../store'
import { cellPoly, center, toLngLat } from '../geo'
import { batteryOf, dname, dronePriority, healthOf, PRIORITY_SCALE } from '../lib'
import { droneSvg } from './Icons'

const EMPTY: any = {
  type: 'FeatureCollection',
  features: [],
}

const LAYERS: Record<string, string[]> = {
  grid: ['cl'],
  trails: ['tr'],
  tasks: ['tk'],
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

type DronePin = {
  m: maplibregl.Marker
  e: HTMLElement
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

export default function MapView({
  children,
}: {
  children?: any
}) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const ready = useRef(false)

  const pins = useRef<Record<string, DronePin>>({})
  const extra = useRef<maplibregl.Marker[]>([])

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
  })

  const [is3d, setIs3d] = useState(true)
  const [info, setInfo] = useState(false)

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

      // Every cell of the 20x20 grid is drawn as a plain blue cell
      // (slightly brighter once a drone has explored it).
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

      // Pending (yellow) task dots are not drawn.
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
      m.remove()
      map.current = null
      ready.current = false

      pins.current = {}
      extra.current = []
    }
  }, [])

  const draw = () => {
    const m = map.current

    if (!m || !ready.current || !run) return

    const g = run.grid
    const feats: any[] = []

    for (let y = 0; y < g.height; y++) {
      for (let x = 0; x < g.width; x++) {
        feats.push({
          type: 'Feature',
          properties: { k: visited.has(`${x},${y}`) ? 'visited' : 'unexplored' },
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

      // Drone icon is outlined in its priority colour, taken from the
      // simulation's task data (same rule as the side-panel box).
      const pr = dronePriority(run, d)
      const icon = p.e.querySelector('.ic') as HTMLElement | null

      if (pr) {
        if (icon) {
          icon.style.borderRadius = '7px'
          icon.style.border = `2px solid ${pr.color}`
          icon.style.boxShadow = `0 0 0 2px ${pr.color}55, 0 0 10px ${pr.color}99`
        }

        p.e.title =
          `${d.drone_id}: ${pr.label} priority (task ${pr.task}, P${pr.level})`
      } else {
        p.e.title = `${d.drone_id}: no task priority yet`
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
  }

  useEffect(draw, [
    run,
    trails,
    visited,
    selected,
    handoffs,
    bat,
  ])

  useEffect(() => {
    if (run) return

    Object.values(pins.current).forEach((p) => p.m.remove())
    extra.current.forEach((x) => x.remove())

    pins.current = {}
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

      <div className="tb-l glass">
        {[
          ['grid', '▦', 'Search grid'],
          ['trails', '⤳', 'Flight paths'],
          ['tasks', '◎', 'Tasks'],
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
            {[5, 4, 3, 2, 1].map((level) => {
              const { label, color } = PRIORITY_SCALE[level]

              return (
                <span key={level}>
                  <i
                    style={{
                      background: color,
                      border: `1px solid ${color}`,
                      width: 12,
                      height: 12,
                      borderRadius: 3,
                    }}
                  />
                  <b>{level}</b> · {label}
                  <span
                    className="mono"
                    style={{ marginLeft: 'auto', opacity: 0.75 }}
                  >
                    {color}
                  </span>
                </span>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}