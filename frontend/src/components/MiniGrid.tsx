import { rowsOf } from '../lib'
import { usePal } from '../theme'
// Compact SVG view of the backend's grid (blocked / restricted / explored / drones / tasks)
export default function MiniGrid({ run, visited, size = 260 }: { run: any; visited?: Set<string>; size?: number }) {
  const P = usePal()
  if (!run?.grid) return <div className="mut" style={{ height: size, display: 'grid', placeItems: 'center' }}>No active run</div>
  const g = run.grid; const rows = rowsOf(g); const c = size / Math.max(g.width, g.height)
  return (
    <svg width="100%" viewBox={`0 0 ${g.width * c} ${g.height * c}`} style={{ maxWidth: size, background: P.mg.bg, borderRadius: 12, border: `1px solid ${P.mg.border}`, boxShadow: `0 0 28px ${P.mg.glow}` }}>
      <defs>
        <linearGradient id="mgVisited" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#38bdf8" /><stop offset="1" stopColor="#2563eb" /></linearGradient>
        <linearGradient id="mgRestricted" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#fca5a5" /><stop offset="1" stopColor="#dc2626" /></linearGradient>
      </defs>
      {rows.flatMap((r, y) => [...r].map((ch, x) => { const v = visited?.has(`${x},${y}`)
        const f = ch === '#' ? P.mg.blocked : ch === 'X' ? 'url(#mgRestricted)' : v ? 'url(#mgVisited)' : P.mg.free
        return <rect key={`${x},${y}`} x={x * c} y={y * c} width={c - 0.6} height={c - 0.6} rx={1} fill={f} opacity={v && ch !== 'X' && ch !== '#' ? 0.8 : 1} />
      }))}
      {run.tasks.map((t: any) => <circle key={t.task_id} cx={(t.x + 0.5) * c} cy={(t.y + 0.5) * c} r={c * 0.28} fill={t.status === 'completed' ? '#34d399' : t.status === 'blocked' ? '#f87171' : '#fbbf24'} stroke={P.mg.taskStroke} strokeWidth={0.5} />)}
      {run.drones.map((d: any) => <circle key={d.drone_id} cx={(d.x + 0.5) * c} cy={(d.y + 0.5) * c} r={c * 0.45} fill={d.status === 'disconnected' ? P.mg.droneBad : P.mg.droneOk} stroke={d.status === 'disconnected' ? '#f87171' : '#2563eb'} strokeWidth={0.9} strokeDasharray={d.status === 'disconnected' ? '1.5 1' : undefined} />)}
    </svg>)
}