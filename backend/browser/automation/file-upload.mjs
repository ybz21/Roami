import { constants } from 'node:fs'
import { open, realpath, stat, mkdtemp, chmod, rm } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { basename, isAbsolute, join, relative, sep } from 'node:path'
import { tmpdir } from 'node:os'

// Playwright CDP transfers file payloads only below 50 MiB.
export const MAX_FILE_UPLOAD_BYTES = 50 * 1024 * 1024 - 1

const failure = code => Object.assign(new Error(code), { code })
const inside = (root, path) => { const part = relative(root, path); return !!part && part !== '..' && !part.startsWith('..' + sep) && !isAbsolute(part) }

export function uploadArguments(flags, pos) {
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(flags.target || '') || flags.tab != null || flags.url != null || pos.length !== 2 || typeof pos[0] !== 'string' || !pos[0] || pos[0].length > 1000 || typeof pos[1] !== 'string' || !isAbsolute(pos[1]) || pos[1].includes('\0')) throw failure('CHROME_UPLOAD_ARGUMENTS_INVALID')
  if (Object.hasOwn(flags, 'file-root') && (typeof flags['file-root'] !== 'string' || !isAbsolute(flags['file-root']) || flags['file-root'].includes('\0'))) throw failure('CHROME_UPLOAD_ROOT_INVALID')
  if (Object.hasOwn(flags, 'expected-file-sha256') && !/^[a-f0-9]{64}$/.test(flags['expected-file-sha256'])) throw failure('CHROME_UPLOAD_HASH_INVALID')
  if (Object.hasOwn(flags, 'max-file-bytes') && (!/^[1-9][0-9]*$/.test(String(flags['max-file-bytes'])) || !Number.isSafeInteger(Number(flags['max-file-bytes'])))) throw failure('CHROME_UPLOAD_LIMIT_INVALID')
}

export async function withUploadFile(path, options, select) {
  let input, output, directory, selecting = false
  try {
    if (typeof path !== 'string' || !isAbsolute(path) || path.includes('\0')) throw failure('CHROME_UPLOAD_ARGUMENTS_INVALID')
    try { input = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK) } catch { throw failure('CHROME_UPLOAD_FILE_UNAVAILABLE') }
    const before = await input.stat({ bigint: true })
    if (!before.isFile() || before.size <= 0n || (before.mode & 0o444n) === 0n || before.size > BigInt(Number.MAX_SAFE_INTEGER)) throw failure('CHROME_UPLOAD_FILE_INVALID')
    const canonical = await realpath(path), located = await stat(canonical, { bigint: true })
    if (located.dev !== before.dev || located.ino !== before.ino) throw failure('CHROME_UPLOAD_FILE_CHANGED')
    if (options.root && !inside(await realpath(options.root), canonical)) throw failure('CHROME_UPLOAD_OUTSIDE_ROOT')
    const limit = BigInt(Math.min(MAX_FILE_UPLOAD_BYTES, options.maxBytes == null ? MAX_FILE_UPLOAD_BYTES : Number(options.maxBytes)))
    if (before.size > BigInt(MAX_FILE_UPLOAD_BYTES)) throw failure('CHROME_UPLOAD_TRANSPORT_LIMIT_EXCEEDED')
    if (before.size > limit) throw failure('CHROME_UPLOAD_LIMIT_EXCEEDED')
    directory = await mkdtemp(join(tmpdir(), 'roami-upload-'))
    await chmod(directory, 0o700)
    const snapshot = join(directory, basename(path))
    output = await open(snapshot, 'wx', 0o600)
    const hash = createHash('sha256')
    let size = 0
    for await (const chunk of input.createReadStream({ autoClose: false })) {
      size += chunk.length
      if (BigInt(size) > before.size || BigInt(size) > limit) throw failure('CHROME_UPLOAD_FILE_CHANGED')
      hash.update(chunk)
      await output.writeFile(chunk)
    }
    await output.sync()
    await output.close(); output = null
    const after = await input.stat({ bigint: true })
    if (before.size !== after.size || before.mtimeNs !== after.mtimeNs || before.ctimeNs !== after.ctimeNs || BigInt(size) !== before.size) throw failure('CHROME_UPLOAD_FILE_CHANGED')
    const sha256 = hash.digest('hex')
    if (options.sha256 && options.sha256 !== sha256) throw failure('CHROME_UPLOAD_HASH_MISMATCH')
    const file = { name: basename(path), sizeBytes: size, sha256 }
    selecting = true
    return await select(snapshot, file)
  } catch (error) {
    if (!selecting && !/^CHROME_UPLOAD_/.test(error.code || '')) throw failure('CHROME_UPLOAD_FILE_UNAVAILABLE')
    throw error
  } finally {
    await output?.close().catch(() => {})
    await input?.close().catch(() => {})
    if (directory) await rm(directory, { recursive: true, force: true })
  }
}
