// 文本/代码/JSON/Markdown(源码) → Monaco 编辑器（行号、语法高亮、可编辑；截断的大文件只读）。
// Monaco 很重 → 懒加载，不进首屏包。tab 语境下全屏无边框，背景由 CodeEditor 统一成应用底色。
import {Suspense } from 'react'
import { Spin } from 'antd'
import { lazyRetry } from '../../lazy-retry'

const CodeEditor = lazyRetry(() => import('../CodeEditor'))

export function CodeView({ stateKey, value, language, dark, readOnly, tabbed, height, onChange, onSave, revealLine }: {
  /** 视图状态（滚动、光标、选区）按它记：切走再切回来还在原处 */
  stateKey?: string
  value: string
  language: string
  dark: boolean
  readOnly: boolean
  tabbed?: boolean
  height: string
  onChange: (v: string) => void
  onSave: () => void
  revealLine?: { line: number; nonce: number }
}) {
  return (
    <div style={{ height, border: tabbed ? 'none' : '1px solid var(--border-subtle)', borderRadius: tabbed ? 0 : 8, overflow: 'hidden' }}>
      <Suspense fallback={<div style={{ height: '100%', display: 'grid', placeItems: 'center' }}><Spin /></div>}>
        <CodeEditor stateKey={stateKey} value={value} language={language} dark={dark} readOnly={readOnly} onChange={onChange} onSave={onSave} revealLine={revealLine} />
      </Suspense>
    </div>
  )
}
