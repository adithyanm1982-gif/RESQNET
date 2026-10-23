export type BatLevel = 'high' | 'mid' | 'low'

// High: 60-100%   Medium: 30-59%   Low: 0-29%
export const batLevel = (v: number): BatLevel => (v >= 60 ? 'high' : v >= 30 ? 'mid' : 'low')
export const batClass = (v: number) => 'bat-' + batLevel(v)
export const BAT_RANGES = { high: '60–100%', mid: '30–59%', low: '0–29%' }