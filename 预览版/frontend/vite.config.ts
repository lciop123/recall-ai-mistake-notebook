import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    // 图表包只在懒加载的看板路由下载；600KB 是该独立功能包的明确预算。
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks(id) {
          const path = id.replaceAll('\\', '/')
          if (path.includes('/node_modules/echarts/')) return 'echarts'
          if (path.includes('/node_modules/jspdf/')) return 'jspdf'
          if (path.includes('/node_modules/html2canvas/')) return 'html2canvas'
          if (path.includes('/node_modules/markdown-it/') || path.includes('/node_modules/markdown-it-texmath/') || path.includes('/node_modules/katex/')) return 'markdown'
          return undefined
        },
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/images': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
