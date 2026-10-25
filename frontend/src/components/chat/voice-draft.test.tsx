// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import VoiceInput from './VoiceInput'
import { matchHotkey } from '../shell/keybindings'
import { api, transcribe } from '../../api'

class TestBlob extends Blob { async arrayBuffer() { return new Uint8Array([1, 2, 3]).buffer } }

const state = vi.hoisted(() => ({ error: vi.fn(), info: vi.fn(), success: vi.fn(), trackStop: vi.fn(), recorders: [] as any[] }))
vi.mock('../../api', () => ({ api: vi.fn(), transcribe: vi.fn() }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../../layout', () => ({ useLayout: () => ({ coarse: false }) }))
vi.mock('../shell/keybindings', () => ({ useKeybindings: () => ({ voice: { key: null, label: 'Ctrl+Shift+S' } }), matchHotkey: vi.fn(() => false), isHotkeyKeyUp: () => false }))
vi.mock('antd', () => ({ App: { useApp: () => ({ message: state }) }, Tooltip: ({ children }: any) => children }))

beforeEach(() => {
  vi.mocked(matchHotkey).mockReturnValue(false)
  vi.spyOn(Date, 'now').mockReturnValue(1000)
  vi.mocked(api).mockResolvedValue({ data: { provider: 'openai', openai: { apiKey: 'configured' } } })
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop: state.trackStop }] }) } })
  vi.stubGlobal('Blob', TestBlob)
  vi.stubGlobal('MediaRecorder', class {
    onstop: any; ondataavailable: any
    constructor() { state.recorders.push(this) }
    start() {}
    stop() { this.ondataavailable?.({ data: new TestBlob(['audio']) }); this.onstop?.() }
  })
  vi.stubGlobal('AudioContext', class { async decodeAudioData() { return { duration: 1 } } close() {} })
  vi.stubGlobal('OfflineAudioContext', class { destination = {}; createBufferSource() { return { connect() {}, start() {}, buffer: null } } async startRendering() { return { getChannelData: () => new Float32Array(16000) } } })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.clearAllMocks(); state.recorders = [] })
const props = { inline: true, scope: 'one', accent: 'var(--accent)', onResult: vi.fn() }
async function record() {
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: 'voice.clickToTalk' }))
  await waitFor(() => expect(screen.getByRole('status')).toBeTruthy())
  await waitFor(() => expect(state.recorders).toHaveLength(1))
  vi.mocked(Date.now).mockReturnValue(1800)
  fireEvent.click(screen.getByRole('button', { name: 'voice.clickToTalk' }))
  await waitFor(() => expect(transcribe).toHaveBeenCalledOnce())
}

it('adds a transcript through the latest draft callback without sending a message', async () => {
  let resolve!: (text: string) => void
  vi.mocked(transcribe).mockImplementation(() => new Promise(r => { resolve = r }))
  const original = vi.fn(), latest = vi.fn(), page = render(<VoiceInput {...props} onResult={original} />)
  await record()
  page.rerender(<VoiceInput {...props} onResult={latest} />)
  await act(async () => { resolve('补充验收步骤') })
  expect(original).not.toHaveBeenCalled()
  expect(latest).toHaveBeenCalledWith('补充验收步骤')
  expect(api).toHaveBeenCalledTimes(1)
})

it('discards a pending transcript after the conversation changes', async () => {
  let resolve!: (text: string) => void
  vi.mocked(transcribe).mockImplementation(() => new Promise(r => { resolve = r }))
  const result = vi.fn(), page = render(<VoiceInput {...props} onResult={result} />)
  await record()
  page.rerender(<VoiceInput {...props} scope="two" onResult={result} />)
  await act(async () => { resolve('旧会话的语音') })
  expect(result).not.toHaveBeenCalled()
  expect(state.success).not.toHaveBeenCalled()
})

it('releases microphone access granted after unmount without recording or appending', async () => {
  let resolve!: (stream: any) => void
  vi.mocked(navigator.mediaDevices.getUserMedia).mockImplementation(() => new Promise(r => { resolve = r }))
  const result = vi.fn(), page = render(<VoiceInput {...props} onResult={result} />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: 'voice.clickToTalk' }))
  page.unmount()
  await act(async () => { resolve({ getTracks: () => [{ stop: state.trackStop }] }) })
  expect(state.trackStop).toHaveBeenCalledOnce()
  expect(state.recorders).toHaveLength(0)
  expect(result).not.toHaveBeenCalled()
})

it('disables recording for a read-only or hidden composer', async () => {
  render(<VoiceInput {...props} disabled hotkey />)
  await act(async () => {})
  fireEvent.click(screen.getByRole('button', { name: 'voice.clickToTalk' }))
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
})

it('routes a shared shortcut to the focused visible composer only', async () => {
  vi.spyOn(HTMLButtonElement.prototype, 'getClientRects').mockReturnValue([{}] as any)
  vi.mocked(matchHotkey).mockImplementation(event => event.key === 's')
  render(<><div className="conversation-composer"><textarea aria-label="First" /><VoiceInput {...props} hotkey /></div><div className="conversation-composer"><textarea aria-label="Second" /><VoiceInput {...props} scope="two" hotkey /></div></>)
  await act(async () => {})
  screen.getByRole('textbox', { name: 'Second' }).focus()
  fireEvent.keyDown(window, { key: 's', ctrlKey: true, shiftKey: true })
  await waitFor(() => expect(state.recorders).toHaveLength(1))
  expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledOnce()
})
