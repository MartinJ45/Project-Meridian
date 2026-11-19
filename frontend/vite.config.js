import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, the Vite server proxies API and file requests to the FastAPI backend.
export default defineConfig({
  plugins: [react()],
  // The repo-level assets/ folder (logo etc.) is served at the site root: assets/x.png -> /x.png
  publicDir: '../assets',
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/files': 'http://127.0.0.1:8000',
    },
  },
})
