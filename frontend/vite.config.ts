import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_BACKEND_URL || 'http://127.0.0.1:8000'
  // Dev proxy: browser calls /api/... on the Vite origin, so no CORS setup is needed locally.
  return { plugins: [react()], server: { port: 5173, proxy: { '/api': { target, changeOrigin: true } } } }
})
