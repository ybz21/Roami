import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const pdfResources = ['cmaps', 'standard_fonts'].flatMap(directory => {
  const root = new URL(`./node_modules/pdfjs-dist/${directory}/`, import.meta.url)
  return readdirSync(root).map(name => ({ path: `pdfjs/${directory}/${name}`, source: fileURLToPath(new URL(name, root)) }))
})

// 开发期把 /api（含 WebSocket）代理到后端 Gin（:13579）
export default defineConfig({
  plugins: [react(), {
    name: 'pdf-document-resources',
    generateBundle() {
      for (const resource of pdfResources) this.emitFile({ type: 'asset', fileName: resource.path, source: readFileSync(resource.source) })
    },
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const resource = pdfResources.find(item => '/' + item.path === request.url?.split('?')[0])
        if (!resource) return next()
        response.setHeader('Content-Type', 'application/octet-stream')
        response.end(readFileSync(resource.source))
      })
    },
  }],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // antd 是全站基座，单独成块就有 ~800kB+ 属正常，调高阈值避免对合理的 vendor 块误报。
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        // 把第三方库按用途拆成独立 vendor 块：避免挤成一个 ~3MB 巨块，
        // 各块可被浏览器分别缓存（改业务代码不致使整包失效），按需并行加载。
        manualChunks(id) {
          // Vite 动态 import 的 preload 辅助模块被所有含懒加载的 chunk 共享。不显式指定时
          // rollup 可能把它塞进某个懒加载重块（曾落入 monaco 块 → index 静态依赖 monaco，
          // 4.3MB JS + 146KB 阻塞 CSS 全进首屏，懒加载失效）。固定进 vendor（入口本就依赖）。
          if (id.includes('vite/preload-helper')) return 'vendor'
          if (!id.includes('node_modules')) return
          if (id.includes('pdfjs-dist')) return 'pdf'
          // Office 预览（docx/xlsx/pptx）很重，仅看 Office 文件时才用 → 独立块（配合 FileBrowser 懒加载按需取）
          // jszip 是 docx-preview / pptx-to-html 的专属依赖，一并归入，别落进首屏 vendor。
          if (/docx-preview|xlsx|pptx|jvmr|jszip/.test(id)) return 'office'
          // Monaco 编辑器（VSCode 内核）很重，仅编辑/查看文本文件才用 → 独立块（配合 CodeEditor 懒加载按需取，不进首屏）
          // state-local 是 @monaco-editor/loader 的专属依赖。
          if (/monaco-editor|state-local/.test(id)) return 'monaco'
          // Mermaid 图渲染（含 d3 / cytoscape / katex 等专属重依赖）很重，仅渲染含 ```mermaid 的 Markdown 才用
          // → 独立块（Mermaid 组件动态 import 按需取，不进首屏）。共享依赖(dayjs/stylis 等)仍留 vendor。
          // lodash-es / es-toolkit 此仓库里只有 mermaid（经 dagre-d3-es）在用，一并归入。
          if (/[\\/]node_modules[\\/](mermaid|@mermaid-js|cytoscape[^\\/]*|d3[^\\/]*|dagre-d3-es|katex|khroma|roughjs|@braintree[\\/]sanitize-url|@upsetjs[^\\/]*|internmap|delaunator|robust-predicates|layout-base|cose-base|@iconify[\\/]utils|lodash-es|es-toolkit)[\\/]/.test(id)) return 'mermaid'
          // Markdown 渲染链（react-markdown + unified/micromark/hast 生态 + highlight.js 语法高亮）
          // 只有渲染对话文本 / .md 预览才用 → 独立块，配合 Markdown 组件懒加载不进首屏。
          // （此前并入 vendor 是因 Markdown 组件被静态引用，拆块会与 vendor 互相循环；现已懒加载，依赖树独立。）
          if (/[\\/]node_modules[\\/](react-markdown|remark-[^\\/]+|rehype-[^\\/]+|micromark[^\\/]*|mdast-[^\\/]+|hast-[^\\/]+|unist-[^\\/]+|unified|vfile[^\\/]*|lowlight|highlight\.js|property-information|space-separated-tokens|comma-separated-tokens|character-entities[^\\/]*|decode-named-character-reference|html-url-attributes|trim-lines|bail|trough|zwitch|longest-streak|markdown-table|ccount|devlop|is-plain-obj|escape-string-regexp|style-to-js|style-to-object|inline-style-parser|estree-util-is-identifier-name|@ungap[\\/]structured-clone)[\\/]/.test(id)) return 'markdown'
          if (id.includes('@xterm')) return 'xterm'
          // react-redux/redux 等是 @hello-pangea/dnd 的专属依赖，跟着 dnd 走。
          if (/hello-pangea|react-redux|hoist-non-react-statics|[\\/]redux[\\/]|css-box-model|raf-schd|use-memo-one|memoize-one/.test(id)) return 'dnd'
          if (/[\\/]node_modules[\\/](echarts|zrender)[\\/]/.test(id)) return 'usage-charts'
          if (/antd|@ant-design|rc-/.test(id)) return 'antd'
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return 'react'
          return 'vendor'
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      // 后端默认开自签 HTTPS（start.sh 里 TLS 默认 on，手机用麦克风/剪贴板需要安全上下文），
      // 所以这里也得走 https + secure:false 收自签证书；写死 http 会让 dev 模式下
      // /api 一律 400/502。要指到别的实例就设 ROAM_DEV_API。
      '/api': {
        target: process.env.ROAM_DEV_API || 'https://127.0.0.1:13579',
        changeOrigin: true, ws: true, secure: false,
      },
    },
  },
})
