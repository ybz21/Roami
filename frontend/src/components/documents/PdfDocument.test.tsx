// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import PdfDocument from './PdfDocument'

const { getDocument } = vi.hoisted(() => ({ getDocument: vi.fn() }))
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => ({ getDocument, GlobalWorkerOptions: {} }))
vi.mock('../../i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))

type PendingRender = { canvas: HTMLCanvasElement; resolve: () => void; cancel: ReturnType<typeof vi.fn> }
let pending: PendingRender[]
let resize: () => void
let width: number
let drawImage: ReturnType<typeof vi.fn>
let getPage: ReturnType<typeof vi.fn>
let destroy: ReturnType<typeof vi.fn>

beforeEach(() => {
  pending = []; width = 600
  drawImage = vi.fn(); destroy = vi.fn().mockResolvedValue(undefined)
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage } as unknown as CanvasRenderingContext2D)
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => width)
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { resize = callback }
    observe() {}
    disconnect() {}
  })
  getPage = vi.fn().mockResolvedValue({
    getViewport: ({ scale }: { scale: number }) => ({ width: 600 * scale, height: 900 * scale }),
    render: ({ canvas }: { canvas: HTMLCanvasElement }) => {
      let resolve!: () => void, reject!: (error: Error) => void
      const promise = new Promise<void>((yes, no) => { resolve = yes; reject = no })
      const cancel = vi.fn(() => reject(new Error('Rendering cancelled')))
      pending.push({ canvas, resolve, cancel })
      return { promise, cancel }
    },
  })
  getDocument.mockReturnValue({ promise: Promise.resolve({ numPages: 2, getPage }), destroy })
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.clearAllMocks() })

it('keeps the completed canvas visible and sized while a replacement renders', async () => {
  render(<PdfDocument src="/sample.pdf" name="Sample" />)
  const canvas = screen.getByRole('img', { hidden: true }) as HTMLCanvasElement
  await waitFor(() => expect(pending).toHaveLength(1))
  expect(pending[0].canvas).not.toBe(canvas)
  await act(async () => pending[0].resolve())
  expect(canvas.hidden).toBe(false)
  expect(canvas.style.height).toBe('900px')
  expect(drawImage).toHaveBeenCalledTimes(1)

  width = 590
  act(() => resize())
  await waitFor(() => expect(pending).toHaveLength(2))
  expect(canvas.hidden).toBe(false)
  expect(canvas.style.height).toBe('900px')
  expect(canvas.style.width).toBe('600px')
  expect(screen.queryByRole('status')).toBeNull()
  expect(drawImage).toHaveBeenCalledTimes(1)

  await act(async () => pending[1].resolve())
  expect(canvas.style.width).toBe('590px')
  expect(canvas.style.height).toBe('885px')
  expect(drawImage).toHaveBeenLastCalledWith(pending[1].canvas, 0, 0)
  act(() => resize())
  expect(pending).toHaveLength(2)
})

it('cancels obsolete resizes without replacing the displayed page or reporting failure', async () => {
  render(<PdfDocument src="/sample.pdf" name="Sample" />)
  await waitFor(() => expect(pending).toHaveLength(1))
  await act(async () => pending[0].resolve())
  width = 580
  act(() => resize())
  await waitFor(() => expect(pending).toHaveLength(2))
  width = 560
  act(() => resize())
  await waitFor(() => expect(pending).toHaveLength(3))
  expect(pending[1].cancel).toHaveBeenCalledOnce()
  expect(screen.getByRole('img').style.width).toBe('600px')
  expect(screen.queryByRole('alert')).toBeNull()
  await act(async () => pending[2].resolve())
  expect(screen.getByRole('img').style.width).toBe('560px')
  expect(drawImage).toHaveBeenCalledTimes(2)
})

it('retains the page during navigation and discards a pending render on source change', async () => {
  const view = render(<PdfDocument src="/sample.pdf" name="Sample" />)
  await waitFor(() => expect(pending).toHaveLength(1))
  await act(async () => pending[0].resolve())
  fireEvent.click(screen.getByRole('button', { name: 'document.nextPage' }))
  await waitFor(() => expect(getPage).toHaveBeenLastCalledWith(2))
  expect(screen.getByRole('img').hasAttribute('hidden')).toBe(false)
  expect(drawImage).toHaveBeenCalledTimes(1)
  view.rerender(<PdfDocument src="/other.pdf" name="Other" />)
  await waitFor(() => expect(pending).toHaveLength(3))
  expect(pending[1].cancel).toHaveBeenCalledOnce()
  expect(destroy).toHaveBeenCalledOnce()
  expect(screen.getByRole('img', { hidden: true }).hasAttribute('hidden')).toBe(true)
  expect(getPage).toHaveBeenLastCalledWith(1)
  await act(async () => pending[2].resolve())
  expect(screen.getByRole('img').hasAttribute('hidden')).toBe(false)
  expect(drawImage).toHaveBeenCalledTimes(2)
  expect(screen.queryByRole('alert')).toBeNull()
})
