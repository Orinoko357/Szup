import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // 127.0.0.1 zamiast localhost — Node potrafi rozwiązać localhost na ::1
      // (IPv6), a uvicorn słucha na IPv4 → sporadyczne ECONNREFUSED w dev.
      '/api': 'http://127.0.0.1:8003',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
