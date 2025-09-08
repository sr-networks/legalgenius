import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  // Load env file based on `mode` in the current directory and all parent directories
  const env = loadEnv(mode, process.cwd(), '')
  
  return {
    plugins: [react()],
    define: {
      'process.env': env
    },
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, '')
        },
        '/stream': 'http://127.0.0.1:8000',
        '/ask': 'http://127.0.0.1:8000',
        '/health': 'http://127.0.0.1:8000',
        '/test': 'http://127.0.0.1:8000'
      }
    }
  }
})