import { create } from 'zustand'
import { api, ApiError } from './api'

export type User = { sub: string; email: string; name: string; picture?: string | null }
type AuthStatus = 'loading' | 'in' | 'out'

type AuthState = {
  enabled: boolean | null
  clientId: string | null
  nonce: string | null
  status: AuthStatus
  user: User | null
  error: string
  init: () => Promise<void>
  signIn: (credential: string) => Promise<void>
  signOut: () => Promise<void>
  clearError: () => void
}

let initialization: Promise<void> | null = null

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return 'Google could not verify this sign-in. Please try again.'
  if (error instanceof ApiError && error.status === 503) return error.message.replace(/^\d+\s*/, '')
  if (error instanceof ApiError && error.status === 403) return 'This website origin is not allowed to sign in.'
  return 'Could not reach the authentication service. Check the backend connection and try again.'
}

export const useAuth = create<AuthState>((set, get) => ({
  enabled: null,
  clientId: null,
  nonce: null,
  status: 'loading',
  user: null,
  error: '',

  init: async () => {
    if (initialization) return initialization
    initialization = (async () => {
      set({ status: 'loading', error: '' })
      try {
        const config = await api.authConfig()
        if (!config.enabled || !config.client_id) {
          set({ enabled: false, clientId: null, nonce: null, status: 'in', user: null, error: '' })
          return
        }
        set({ enabled: true, clientId: config.client_id })
        try {
          const current = await api.authMe()
          set({ status: 'in', user: current.user, nonce: null, error: '' })
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 401) throw error
          const challenge = await api.authNonce()
          set({ status: 'out', user: null, nonce: challenge.nonce, error: '' })
        }
      } catch (error) {
        // Fail closed: an unavailable config endpoint must not silently disable route protection.
        const enabled = get().enabled
        set({ enabled: enabled ?? true, status: 'out', user: null, error: error instanceof ApiError && error.status === 401 ? '' : errorMessage(error) })
      }
    })()
    try { await initialization } finally { initialization = null }
  },

  signIn: async (credential) => {
    set({ status: 'loading', error: '' })
    try {
      const result = await api.authGoogle(credential)
      set({ enabled: true, status: 'in', user: result.user, nonce: null, error: '' })
    } catch (error) {
      let nonce: string | null = null
      try { nonce = (await api.authNonce()).nonce } catch { /* keep the sign-in failure visible */ }
      set({ status: 'out', user: null, nonce, error: errorMessage(error) })
    }
  },

  signOut: async () => {
    try {
      await api.authLogout()
      set({ status: 'out', user: null, nonce: null, error: '' })
    } catch (error) {
      set({ status: 'out', user: null, nonce: null, error: `Signed out in this browser, but the server session could not be revoked. ${errorMessage(error)}` })
    }
    ;(window as any).google?.accounts?.id?.disableAutoSelect?.()
  },

  clearError: () => set({ error: '' }),
}))
