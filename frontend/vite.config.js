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
    rollupOptions: {
      output: {
        // Biblioteki w osobnych paczkach — zmieniają się rzadko, więc
        // przeglądarka trzyma je w cache między wydaniami aplikacji.
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom)[\\/]/.test(id)) return 'react-vendor'
          if (id.includes('lucide-react')) return 'icons'
          return 'vendor'
        },
      },
    },
  },
})
