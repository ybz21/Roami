// @vitest-environment jsdom
import { cleanup, render } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import CodeEditor from './CodeEditor'
const state = vi.hoisted(() => ({ props: null as any, dispose: vi.fn(), view: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('@monaco-editor/react', () => ({ loader: { config: vi.fn() }, default: (props: any) => { state.props = props; return null } }))
vi.mock('monaco-editor', () => ({}))
afterEach(cleanup)
it('disposes the save action on every editor unmount and calls the latest save handler', () => {
  const first = vi.fn(), latest = vi.fn()
  const rendered = render(<CodeEditor value="one" language="text" dark onChange={() => {}} onSave={first} />)
  let action: any
  state.props.onMount({ addAction: (descriptor: any) => { action = descriptor; return { dispose: state.dispose } }, saveViewState: state.view }, { KeyMod: { CtrlCmd: 1 }, KeyCode: { KeyS: 2 } })
  action.run(); expect(first).toHaveBeenCalledOnce()
  rendered.rerender(<CodeEditor value="two" language="text" dark onChange={() => {}} onSave={latest} />)
  action.run(); expect(latest).toHaveBeenCalledOnce()
  rendered.unmount(); expect(state.dispose).toHaveBeenCalledOnce()
})
