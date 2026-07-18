import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev-only proxy — тот же приём, что в ../buyer-web/vite.config.ts: браузер
// обращается к /api/*, Vite перенаправляет на localhost:8000, backend не
// трогаем (без CORS).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
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
