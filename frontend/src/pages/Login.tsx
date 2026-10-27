import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { useTheme } from '../theme'

declare global { interface Window { google?: any } }

const GOOGLE_IDENTITY_SCRIPT = 'https://accounts.google.com/gsi/client'

export default function Login() {
  const enabled = useAuth((state) => state.enabled)
  const clientId = useAuth((state) => state.clientId)
  const nonce = useAuth((state) => state.nonce)
  const status = useAuth((state) => state.status)
  const error = useAuth((state) => state.error)
  const clearError = useAuth((state) => state.clearError)
  const init = useAuth((state) => state.init)
  const signIn = useAuth((state) => state.signIn)
  const mode = useTheme((state) => state.mode)
  const location = useLocation()
  const navigate = useNavigate()
  const button = useRef<HTMLDivElement>(null)
  const [ready, setReady] = useState(!!window.google?.accounts)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (enabled === false) return
    if (window.google?.accounts) { setReady(true); return }
    const script = document.createElement('script')
    script.src = GOOGLE_IDENTITY_SCRIPT
    script.async = true
    script.defer = true
    script.onload = () => setReady(true)
    script.onerror = () => setFailed(true)
    document.head.appendChild(script)
    return () => { script.onload = null; script.onerror = null }
  }, [enabled])

  useEffect(() => {
    if (!ready || !clientId || !nonce || status !== 'out' || !button.current || !window.google?.accounts) return
    window.google.accounts.id.initialize({
      client_id: clientId,
      nonce,
      callback: async (result: { credential?: string }) => {
        if (!result?.credential) return
        await signIn(result.credential)
        if (useAuth.getState().status === 'in') {
          const requested = (location.state as any)?.from?.pathname
          const from = typeof requested === 'string' && requested.startsWith('/') && !requested.startsWith('//') ? requested : '/'
          navigate(from, { replace: true })
        }
      },
      auto_select: false,
      cancel_on_tap_outside: true,
    })
    button.current.innerHTML = ''
    window.google.accounts.id.renderButton(button.current, {
      theme: mode === 'dark' ? 'filled_black' : 'outline',
      size: 'large',
      shape: 'pill',
      text: 'signin_with',
      width: 280,
    })
  }, [ready, clientId, nonce, status, mode, signIn, location.state, navigate])

  useEffect(() => {
    if (status === 'in' && enabled) navigate('/', { replace: true })
  }, [status, enabled, navigate])

  return (
    <div className="authwrap">
      <section className="card authcard">
        <img src="/favicon.png" alt="" className="authlogo" />
        <h1>RESQ<b>NET</b></h1>
        <p className="sub">Resilient Swarm Coordination for Disaster Response</p>
        {enabled === false
          ? <><p className="mut">Google sign-in is not configured on this deployment.</p><Link className="btn" to="/">Continue in guest mode</Link></>
          : <>
            <p className="mut">Sign in with Google to continue to the mission workspace.</p>
            {clientId && nonce && status === 'out' && <div ref={button} className="gbtn" />}
            {status === 'loading' && <p className="note" role="status">Checking your RESQNET session…</p>}
            {failed && <p className="err" role="alert">Google Sign-In could not be loaded. Check your connection and refresh.</p>}
            {error && <p className="err" role="alert">{error}</p>}
            {enabled === true && (!clientId || !nonce) && <button onClick={() => { clearError(); void init() }}>Retry authentication service</button>}
          </>}
        <p className="mut auth-foot">Google verifies your identity. RESQNET does not receive or store your Google password.</p>
      </section>
    </div>
  )
}
