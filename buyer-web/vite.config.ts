import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev-only proxy: браузер обращается к /api/*, Vite перенаправляет на локальный
// backend (localhost:8000) — бэкенду не нужен CORS, прототип не трогает ни
// одного файла backend/.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // Временно, для демо через ngrok/cloudflare-туннель — иначе Vite отклоняет
    // запросы с чужим Host-заголовком ("This host is not allowed").
    allowedHosts: ['.ngrok-free.app', '.ngrok.app', '.ngrok.io', '.trycloudflare.com'],
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
