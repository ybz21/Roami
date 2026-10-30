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
let width: number, height: number
let drawImage: ReturnType<typeof vi.fn>
let getPage: ReturnType<typeof vi.fn>
let destroy: ReturnType<typeof vi.fn>

beforeEach(() => {
  pending = []; width = 600; height = 900
  drawImage = vi.fn(); destroy = vi.fn().mockResolvedValue(undefined)
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage } as unknown as CanvasRenderingContext2D)
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(() => width)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(() => height)
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


it('fits the complete page to height and refits when only the pane height changes', async () => {
  height = 450
  render(<PdfDocument src="/sample.pdf" name="Sample" />)
  await waitFor(() => expect(pending).toHaveLength(1))
  await act(async () => pending[0].resolve())
  expect(screen.getByRole('img').style.width).toBe('300px')
  expect(screen.getByRole('img').style.height).toBe('450px')
  height = 300
  act(() => resize())
  await waitFor(() => expect(pending).toHaveLength(2))
  await act(async () => pending[1].resolve())
  expect(screen.getByRole('img').style.height).toBe('300px')
  expect(screen.getByRole('img').style.width).toBe('200px')
})

it('supports width fitting and real zoom beyond the pane width', async () => {
  height = 450
  render(<PdfDocument src="/sample.pdf" name="Sample" />)
  await waitFor(() => expect(pending).toHaveLength(1))
  await act(async () => pending[0].resolve())
  fireEvent.mouseDown(screen.getByRole('combobox', { name: 'document.scale' }))
  fireEvent.click(await screen.findByText('document.fitWidth'))
  await waitFor(() => expect(pending).toHaveLength(2))
  await act(async () => pending[1].resolve())
  expect(screen.getByRole('img').style.height).toBe('900px')
  fireEvent.click(screen.getByRole('button', { name: 'file.imgZoomIn' }))
  await waitFor(() => expect(pending).toHaveLength(3))
  await act(async () => pending[2].resolve())
  expect(screen.getByRole('img').style.width).toBe('750px')
  expect(screen.getByRole('img').style.height).toBe('1125px')
})

it('jumps on Enter or blur, clamps page bounds and restores invalid input', async () => {
  render(<PdfDocument src="/sample.pdf" name="Sample" />)
  await waitFor(() => expect(pending).toHaveLength(1))
  await act(async () => pending[0].resolve())
  const input = screen.getByRole('textbox', { name: 'document.jumpToPage' })
  const scroll = screen.getByRole('img').parentElement!
  scroll.scrollTop = 200; scroll.scrollLeft = 100
  fireEvent.change(input, { target: { value: '999' } })
  fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' })
  await waitFor(() => expect(getPage).toHaveBeenLastCalledWith(2))
  expect((input as HTMLInputElement).value).toBe('2')
  expect(scroll.scrollTop).toBe(0)
  expect(scroll.scrollLeft).toBe(0)
  await act(async () => pending[1].resolve())
  fireEvent.change(input, { target: { value: '' } })
  fireEvent.blur(input)
  expect((input as HTMLInputElement).value).toBe('2')
  fireEvent.change(input, { target: { value: '1.5' } })
  fireEvent.blur(input)
  expect((input as HTMLInputElement).value).toBe('2')
  fireEvent.change(input, { target: { value: '0' } })
  fireEvent.blur(input)
  await waitFor(() => expect(getPage).toHaveBeenLastCalledWith(1))
  expect((input as HTMLInputElement).value).toBe('1')
})

it('keeps fitting controls for a single-page PDF without pagination', async () => {
  getDocument.mockReturnValue({ promise: Promise.resolve({ numPages: 1, getPage }), destroy })
  render(<PdfDocument src="/sample.pdf" name="Sample" />)
  await waitFor(() => expect(pending).toHaveLength(1))
  await act(async () => pending[0].resolve())
  expect(screen.getByRole('combobox', { name: 'document.scale' })).toBeTruthy()
  expect(screen.queryByRole('textbox', { name: 'document.jumpToPage' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'document.nextPage' })).toBeNull()
})


it('recalculates fitting for a landscape page after a portrait page', async () => {
  height = 450
  render(<PdfDocument src="/sample.pdf" name="Sample" />)
  await waitFor(() => expect(pending).toHaveLength(1))
  await act(async () => pending[0].resolve())
  const portrait = await getPage.mock.results[0].value
  getPage.mockResolvedValue({ ...portrait, getViewport: ({ scale }: { scale: number }) => ({ width: 900 * scale, height: 600 * scale }) })
  fireEvent.click(screen.getByRole('button', { name: 'document.nextPage' }))
  await waitFor(() => expect(pending).toHaveLength(2))
  await act(async () => pending[1].resolve())
  expect(screen.getByRole('img').style.width).toBe('600px')
  expect(screen.getByRole('img').style.height).toBe('400px')
})
