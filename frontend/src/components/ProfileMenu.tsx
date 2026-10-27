import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../auth'

export default function ProfileMenu() {
  const enabled = useAuth((state) => state.enabled)
  const status = useAuth((state) => state.status)
  const user = useAuth((state) => state.user)
  const signOut = useAuth((state) => state.signOut)
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const signedIn = enabled === true && status === 'in' && !!user
  return (
    <div className="profile" ref={ref}>
      <button className="pbtn" onClick={() => setOpen((value) => !value)} aria-haspopup="menu" aria-expanded={open} title="Profile">
        {user?.picture
          ? <img className="pav" src={user.picture} alt="" referrerPolicy="no-referrer" />
          : <span className="pav">{signedIn && user ? user.name.charAt(0).toUpperCase() : '👤'}</span>}
        <span className="pname">{signedIn && user ? user.name : enabled === false ? 'Guest' : 'Profile'}</span>
        <span className="caret" aria-hidden="true">▾</span>
      </button>
      {open && <div className="pmenu" role="menu">
        {signedIn && user
          ? <><div className="phead"><b>{user.name}</b><span className="mut">{user.email}</span></div>
            <button className="pitem" role="menuitem" onClick={() => { setOpen(false); void signOut() }}>Sign out</button></>
          : <div className="pnote">{enabled === false ? 'Guest mode. Google sign-in is not configured on this deployment.' : 'Sign-in is required to use the mission workspace.'}</div>}
      </div>}
    </div>
  )
}
