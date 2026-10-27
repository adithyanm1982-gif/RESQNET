import { create } from 'zustand'

export type Mode = 'dark' | 'light'
const KEY = 'resqnet-theme'

const initial = (): Mode => {
  try { const s = localStorage.getItem(KEY); if (s === 'light' || s === 'dark') return s } catch {}
  return 'dark'
}
const apply = (m: Mode) => document.documentElement.setAttribute('data-theme', m)

const first = initial()
apply(first)

export const useTheme = create<{ mode: Mode; set: (m: Mode) => void; toggle: () => void }>((set, get) => ({
  mode: first,
  set: (m) => { apply(m); try { localStorage.setItem(KEY, m) } catch {} ; set({ mode: m }) },
  toggle: () => get().set(get().mode === 'dark' ? 'light' : 'dark'),
}))

const dark = {
  grid: '#26262c', axis: '#9a9aa5', tipBg: '#141418', tipBorder: '#34343c', tipText: '#ececef', cursor: '#ffffff0d', pieStroke: '#111114',
  accent: '#60a5fa',
  k: { info: '#60a5fa', warn: '#fbbf24', err: '#f87171', cov: '#22d3ee', dup: '#a5b4fc', safe: '#34d399', rec: '#93c5fd' },
  line: { done: '#34d399', disc: '#f87171', conf: '#fbbf24' },
  mg: { bg: '#0c0c0f', border: '#34343c', free: '#1b1b20', blocked: '#52525b', taskStroke: '#ececef', droneOk: '#f4f4f5', droneBad: '#0c0c0f', glow: '#00000066' },
}
const light: typeof dark = {
  grid: '#e1e7f1', axis: '#5a6b8c', tipBg: '#ffffff', tipBorder: '#c9d3e4', tipText: '#0f1b33', cursor: '#2563eb12', pieStroke: '#ffffff',
  accent: '#2563eb',
  k: { info: '#2563eb', warn: '#b45309', err: '#dc2626', cov: '#0891b2', dup: '#4f46e5', safe: '#047857', rec: '#1d4ed8' },
  line: { done: '#059669', disc: '#dc2626', conf: '#d97706' },
  mg: { bg: '#eef3fb', border: '#c9d3e4', free: '#dde6f4', blocked: '#7c8db0', taskStroke: '#0f1b33', droneOk: '#ffffff', droneBad: '#ffffff', glow: '#1e3a8a1a' },
}

export type Pal = typeof dark
export const PAL: Record<Mode, Pal> = { dark, light }
export const usePal = (): Pal => PAL[useTheme((s) => s.mode)]

export const tip = (P: Pal) => ({
  contentStyle: { background: P.tipBg, border: `1px solid ${P.tipBorder}`, borderRadius: 10, color: P.tipText },
  labelStyle: { color: P.axis },
  itemStyle: { color: P.tipText },
  cursor: { fill: P.cursor },
})