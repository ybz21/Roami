// Monaco 代码编辑器（VSCode 同款内核）：行号、语法高亮、编辑、查找、Ctrl+S 保存。
// 依赖较重，仅由 FileBrowser 的 Viewer 懒加载引入，不进首屏包。
// 用本地打包的 monaco（loader.config），不依赖 CDN，离线/局域网也能用。
import { useEffect, useRef } from 'react'
import { recallEditorView, rememberEditorView } from './fileview/view-state-memory'
import Editor, { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import JsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import CssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker'
import HtmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker'
import TsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker'

// Vite 用 ?worker 把各语言 worker 单独打包，用到才取（编辑时才加载）。
;(self as any).MonacoEnvironment = {
  getWorker(_: unknown, label: string) {
    if (label === 'json') return new JsonWorker()
    if (label === 'css' || label === 'scss' || label === 'less') return new CssWorker()
    if (label === 'html' || label === 'handlebars' || label === 'razor') return new HtmlWorker()
    if (label === 'typescript' || label === 'javascript') return new TsWorker()
    return new EditorWorker()
  },
}
loader.config({ monaco })

export default function CodeEditor({
  value, language, dark, readOnly, onChange, onSave, revealLine, stateKey,
}: {
  /** 给了就在卸载时存下视图状态（滚动、光标、选区），下次挂上对回去 */
  stateKey?: string
  value: string
  language: string
  dark: boolean
  readOnly?: boolean
  onChange: (v: string) => void
  onSave: () => void
  // 从对话页点「Grep 命中 path:line」跳过来时定位到那一行。
  // 每次跳都换一个 nonce —— 同一文件已经开着时 value/language 都没变，
  // 没有 nonce 就不会触发重新定位（第二次点同一处会毫无反应）。
  revealLine?: { line: number; nonce: number }
}) {
  const edRef = useRef<monaco.editor.IStandaloneCodeEditor | null>(null)
  // 卸载（标签切走）时存视图状态。ref 取最新的 key：同一个编辑器实例不会换文件，但保险起见
  const keyRef = useRef(stateKey); keyRef.current = stateKey
  useEffect(() => () => { if (keyRef.current && edRef.current) rememberEditorView(keyRef.current, edRef.current.saveViewState()) }, [])
  useEffect(() => {
    const ed = edRef.current
    if (!ed || !revealLine?.line) return
    ed.revealLineInCenter(revealLine.line)
    ed.setPosition({ lineNumber: revealLine.line, column: 1 })
    ed.focus()
  }, [revealLine?.line, revealLine?.nonce, value])
  // 让编辑器背景/装订线/缩略图跟应用统一（用 --bg-base，避免 Monaco 默认灰底跟四周不一致）。
  const appBg = (typeof getComputedStyle !== 'undefined'
    ? getComputedStyle(document.documentElement).getPropertyValue('--bg-base').trim()
    : '') || (dark ? '#0d1117' : '#ffffff')
  return (
    <Editor
      height="100%"
      value={value}
      language={language}
      theme={dark ? 'roam-dark' : 'roam-light'}
      beforeMount={(m) => {
        const colors = { 'editor.background': appBg, 'editorGutter.background': appBg, 'minimap.background': appBg, 'editorStickyScroll.background': appBg }
        m.editor.defineTheme('roam-dark', { base: 'vs-dark', inherit: true, rules: [], colors })
        m.editor.defineTheme('roam-light', { base: 'vs', inherit: true, rules: [], colors })
      }}
      onChange={(v) => onChange(v ?? '')}
      onMount={(editor, m) => {
        edRef.current = editor
        // Ctrl/Cmd+S 保存（onSave 读最新 draft，见 Viewer）
        editor.addCommand(m.KeyMod.CtrlCmd | m.KeyCode.KeyS, () => onSave())
        if (revealLine?.line) { editor.revealLineInCenter(revealLine.line); editor.setPosition({ lineNumber: revealLine.line, column: 1 }) }
        else if (stateKey) { const st = recallEditorView(stateKey) as monaco.editor.ICodeEditorViewState | undefined; if (st) editor.restoreViewState(st) }
      }}
      options={{
        readOnly,
        fontSize: 13,
        // Monaco 默认会拦截拖到编辑器上的 drop（dropIntoEditor：插入文件/文本）并阻止其冒泡，
        // 导致把文件 tab 拖到编辑器区想「分栏」时，drop 被 Monaco 吃掉、外层 FileWorkspace 收不到。
        // 关掉它，让 drop 冒泡到外层做分栏。（编辑器内选中文本拖动 dragAndDrop 保留不动。）
        dropIntoEditor: { enabled: false },
        minimap: { enabled: true }, // 右侧代码缩略图：显示整段代码长度与当前所在位置（VSCode 同款）
        lineNumbers: 'on',
        // 行号装订线：关掉字形边距/折叠栏（那才是之前的大缝隙），保留 VSCode 同款行号↔代码间距
        glyphMargin: false,
        folding: false,
        lineNumbersMinChars: 3,
        lineDecorationsWidth: 10,
        scrollBeyondLastLine: false,
        automaticLayout: true,
        tabSize: 2,
        renderWhitespace: 'selection',
        smoothScrolling: true,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
      }}
    />
  )
}
