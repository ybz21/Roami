const MAX_DIMENSION = 2000, MAX_ENCODED_BYTES = 4.5 * 1024 * 1024, MAX_PIXELS = 64000000
export const IMAGE_SOURCE_BYTES = 64 * 1024 * 1024
export const ATTACHMENT_BYTES = 10 * 1024 * 1024
const encodedSize = (bytes: number) => Math.ceil(bytes / 3) * 4

export function mightBeImage(file: File) {
  return /image\/(png|jpeg|webp)/i.test(file.type) || /\.(png|jpe?g|webp)$/i.test(file.name)
}
async function imageMime(file: File) {
  const bytes = new Uint8Array(await file.slice(0, 12).arrayBuffer())
  if (bytes[0] === 137 && bytes[1] === 80 && bytes[2] === 78 && bytes[3] === 71) return 'image/png'
  if (bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255) return 'image/jpeg'
  const text = String.fromCharCode(...bytes)
  return text.startsWith('RIFF') && text.slice(8) === 'WEBP' ? 'image/webp' : null
}
function encode(canvas: HTMLCanvasElement, mime: string, quality?: number) {
  return new Promise<Blob>((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(Error('IMAGE_ENCODE_FAILED')), mime, quality))
}
function outputFile(source: File, blob: Blob) {
  const extension = blob.type === 'image/png' ? '.png' : '.jpg'
  const stem = source.name.replace(/\.[^.]+$/, '').slice(0, 180 - extension.length)
  return new File([blob], stem + extension, { type: blob.type, lastModified: source.lastModified })
}

export async function prepareImageUpload(file: File): Promise<File> {
  if (file.size > IMAGE_SOURCE_BYTES) throw Error('IMAGE_SOURCE_LIMIT')
  const mime = await imageMime(file)
  if (!mime) {
    if (file.size > ATTACHMENT_BYTES) throw Error('ATTACHMENT_SIZE_LIMIT')
    return file
  }
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
  try {
    if (!bitmap.width || !bitmap.height || bitmap.width * bitmap.height > MAX_PIXELS) throw Error('IMAGE_PIXEL_LIMIT')
    if (bitmap.width <= MAX_DIMENSION && bitmap.height <= MAX_DIMENSION && encodedSize(file.size) <= MAX_ENCODED_BYTES) return file
    const scale = Math.min(1, MAX_DIMENSION / bitmap.width, MAX_DIMENSION / bitmap.height)
    let width = Math.max(1, Math.round(bitmap.width * scale)), height = Math.max(1, Math.round(bitmap.height * scale))
    const canvas = document.createElement('canvas')
    try {
      while (true) {
        canvas.width = width; canvas.height = height
        const context = canvas.getContext('2d')
        if (!context) throw Error('IMAGE_CANVAS_UNAVAILABLE')
        context.drawImage(bitmap, 0, 0, width, height)
        const png = await encode(canvas, 'image/png')
        if (encodedSize(png.size) <= MAX_ENCODED_BYTES) return outputFile(file, png)
        context.fillStyle = 'white'; context.fillRect(0, 0, width, height); context.drawImage(bitmap, 0, 0, width, height)
        for (const quality of [0.8, 0.7, 0.55, 0.4]) {
          const jpeg = await encode(canvas, 'image/jpeg', quality)
          if (encodedSize(jpeg.size) <= MAX_ENCODED_BYTES) return outputFile(file, jpeg)
        }
        if (width === 1 && height === 1) throw Error('IMAGE_ENCODED_LIMIT')
        width = Math.max(1, Math.floor(width * 0.75)); height = Math.max(1, Math.floor(height * 0.75))
      }
    } finally { canvas.width = 0; canvas.height = 0 }
  } finally { bitmap.close() }
}
