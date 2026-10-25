import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import backendPlugin from './dev-backend.mjs'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), backendPlugin()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: path => path.replace(/^\/api(?=\/|$)/, ''),
        timeout: 180000,
        proxyTimeout: 180000,
      },
    },
  },
})
