import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

// Build output feeds the FastAPI static mount (L1 -> L2).
// dashboard-kit（dojocore/dashboard-kit）位于 web/ 之外，需放开 fs.allow 与别名。
const repoRoot = fileURLToPath(new URL('../../../..', import.meta.url))

export default defineConfig({
  base: './',
  plugins: [
    react(),
    // 构建期按实际 hash 文件名注入字体 preload：
    // 字体排在 CSS 解析之后才开始下载会拖慢 FCP；preload 让它与 JS 并行。
    {
      name: 'inject-font-preload',
      enforce: 'post',
      transformIndexHtml(html, ctx) {
        const fonts = Object.keys(ctx.bundle || {}).filter((f) => f.endsWith('.woff2'))
        if (!fonts.length) return html
        const tags = fonts
          .map((f) => `    <link rel="preload" href="./${f}" as="font" type="font/woff2" crossorigin />`)
          .join('\n')
        return html.replace('</head>', `${tags}\n  </head>`)
      },
    },
  ],
  resolve: {
    alias: {
      '@dashboard-kit': fileURLToPath(new URL('../../../../dojocore/dashboard-kit', import.meta.url)),
    },
  },
  build: {
    outDir: '../static/app',
    emptyOutDir: true,
    // 首屏体积门禁（22 号文 §六）：vendor 单独拆包，入口保持精简
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          // 图表与栅格只在特定 tab 用 → 独立 chunk，由 lazy() 按需拉取
          if (id.includes('recharts') || id.includes('/d3-') || id.includes('victory-vendor')) return 'vendor-charts'
          if (id.includes('react-grid-layout') || id.includes('react-resizable')) return 'vendor-grid'
          // React 运行时是首屏必需，单独成 chunk 便于长缓存
          if (id.includes('/react/') || id.includes('/react-dom/') ||
              id.includes('/scheduler/') || id.includes('react/jsx-runtime')) return 'vendor-react'
          // 其余第三方一律归杂项，不与 React 混在一起拖累首屏
          return 'vendor-misc'
        },
      },
    },
  },
  server: {
    fs: { allow: [repoRoot] },
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
})
