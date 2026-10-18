// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { prepareImageUpload } from './image-upload'

const png = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])
function file(name = 'test.png', size = 20) {
  const value = new File([png], name, { type: 'image/png' })
  Object.defineProperty(value, 'size', { value: size })
  Object.defineProperty(value, 'slice', { value: () => ({ arrayBuffer: async () => png.buffer }) })
  return value
}
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })
function bitmap(width: number, height: number) {
  const close = vi.fn()
  vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width, height, close }))
  return close
}
it('preserves a compliant image byte for byte and releases its bitmap', async () => {
  const source = file(), close = bitmap(40, 30)
  expect(await prepareImageUpload(source)).toBe(source)
  expect(close).toHaveBeenCalledOnce()
})
it('allows an image above the server upload cap to be optimized before upload', async () => {
  const source = file('camera.png', 12 * 1024 * 1024), close = bitmap(4000, 3000)
  const context = { drawImage: vi.fn(), fillRect: vi.fn(), fillStyle: '' }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as any)
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function (this: HTMLCanvasElement, callback, type) {
    expect(this.width).toBe(2000); expect(this.height).toBe(1500)
    callback(new Blob([png], { type }))
  })
  const result = await prepareImageUpload(source)
  expect(result).not.toBe(source); expect(result.type).toBe('image/png'); expect(result.size).toBeLessThan(10 * 1024 * 1024)
  expect(close).toHaveBeenCalledOnce()
})
it('falls back to JPEG with a matching file extension and white background', async () => {
  bitmap(3000, 1000)
  const context = { drawImage: vi.fn(), fillRect: vi.fn(), fillStyle: '' }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as any)
  vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation((callback, type) => {
    const blob = new Blob([png], { type })
    if (type === 'image/png') Object.defineProperty(blob, 'size', { value: 4 * 1024 * 1024 })
    callback(blob)
  })
  const result = await prepareImageUpload(file('screenshot.png'))
  expect(result.type).toBe('image/jpeg'); expect(result.name).toBe('screenshot.jpg')
  expect(context.fillStyle).toBe('white'); expect(context.fillRect).toHaveBeenCalled()
})
it('rejects an unsupported huge pixel count and closes the decoded bitmap', async () => {
  const close = bitmap(10000, 10000)
  await expect(prepareImageUpload(file())).rejects.toThrow('IMAGE_PIXEL_LIMIT')
  expect(close).toHaveBeenCalledOnce()
})
