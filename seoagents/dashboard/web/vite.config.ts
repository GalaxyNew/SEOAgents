import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build output feeds the FastAPI static mount (L1 -> L2).
export default defineConfig({
  base: './',
  plugins: [react()],
  build: { outDir: '../static/app', emptyOutDir: true },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
})

