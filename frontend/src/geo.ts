// Anchor of grid cell (0,0). Editable in Settings (stored locally); .env gives the default.
const anchor = () => { try { const a = JSON.parse(localStorage.getItem('rq_anchor') || ''); if (a && isFinite(a.lat) && isFinite(a.lng)) return a } catch { /* default */ }
  return { lat: parseFloat(import.meta.env.VITE_MAP_LAT || '-37.8140'), lng: parseFloat(import.meta.env.VITE_MAP_LNG || '145.1230') } }
export const CELL_M = 25
export const toLngLat = (x: number, y: number): [number, number] => {
  const a = anchor(); return [a.lng + (x * CELL_M) / (111320 * Math.cos((a.lat * Math.PI) / 180)), a.lat - (y * CELL_M) / 111320] }
export const cellPoly = (x: number, y: number) => [toLngLat(x, y), toLngLat(x + 1, y), toLngLat(x + 1, y + 1), toLngLat(x, y + 1), toLngLat(x, y)]
export const center = (w: number, h: number) => toLngLat(w / 2, h / 2)
export const label = (x: number, y: number) => String.fromCharCode(65 + x) + (y + 1)
export const latlon = (x: number, y: number) => { const [lng, lat] = toLngLat(x + 0.5, y + 0.5); return `${lat.toFixed(6)}, ${lng.toFixed(6)}` }
