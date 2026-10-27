import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../auth'

export default function RequireAuth({ children }: { children: ReactNode }) {
  const enabled = useAuth((state) => state.enabled)
  const status = useAuth((state) => state.status)
  const location = useLocation()

  if (enabled === false) return <>{children}</>
  if (enabled === null || status === 'loading') {
    return <div className="authwrap"><div className="note" role="status">Checking your RESQNET session…</div></div>
  }
  if (status !== 'in') {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  return <>{children}</>
}
