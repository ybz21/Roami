import { constants } from 'node:fs'
import { open, mkdir, lstat, rename, unlink } from 'node:fs/promises'
import { createHash, randomUUID } from 'node:crypto'
import { isAbsolute, join } from 'node:path'

const states = new Set(['accepted', 'running', 'succeeded', 'failed', 'cancelled', 'unknown'])
const receiptError = code => Object.assign(new Error(code), { code })

export const operationFailureCode = message => message === 'BROWSER_TAB_BUDGET_EXCEEDED' || /^CHROME_(TARGET_(INVALID|NOT_FOUND|SELECTION_CONFLICT|IN_USE)|SCENE_CHANGED|BROWSER_CHANGED|NAVIGATION_(NAME_NOT_RESOLVED|CONNECTION_TIMED_OUT|CONNECTION_REFUSED|CONNECTION_RESET|CONNECTION_CLOSED|ADDRESS_UNREACHABLE|INTERNET_DISCONNECTED|NETWORK_CHANGED|PROXY_CONNECTION_FAILED|TUNNEL_CONNECTION_FAILED|EMPTY_RESPONSE|SSL_PROTOCOL_ERROR|CERT_AUTHORITY_INVALID|CERT_DATE_INVALID))$/.test(message)
        ? message : 'CHROME_OPERATION_OUTCOME_UNKNOWN'

export class OperationReceipts {
  static hash(payload) {
    return createHash('sha256').update(JSON.stringify(payload)).digest('hex')
  }
  constructor(root) {
    if (typeof root !== 'string' || !isAbsolute(root)) throw receiptError('CHROME_RECEIPT_ROOT_INVALID')
    this.root = root
  }
  path(id, suffix = '.json') {
    if (typeof id !== 'string' || !/^[a-f0-9]{32}$/.test(id)) throw receiptError('CHROME_OPERATION_ID_INVALID')
    return join(this.root, id + suffix)
  }
  async directory() {
    await mkdir(this.root, { recursive: true, mode: 0o700 })
    const info = await lstat(this.root)
    if (!info.isDirectory() || (info.mode & 0o077) || (process.getuid && info.uid !== process.getuid())) {
      throw receiptError('CHROME_RECEIPT_ROOT_INVALID')
    }
  }
  async sync() {
    const directory = await open(this.root, constants.O_RDONLY)
    try { await directory.sync() } finally { await directory.close() }
  }
  async read(id) {
    await this.directory()
    let file
    try {
      file = await open(this.path(id), constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK)
      const info = await file.stat()
      if (!info.isFile() || info.size > 256_000 || (info.mode & 0o077)) throw new Error('invalid receipt file')
      const record = JSON.parse(await file.readFile('utf8'))
      if (record.version !== 1 || record.id !== id || !/^[a-f0-9]{64}$/.test(record.payloadHash) || !states.has(record.state)
        || typeof record.outcomeKnown !== 'boolean' || typeof record.inputStopped !== 'boolean'
        || !Number.isFinite(record.createdMs) || !Number.isFinite(record.updatedMs)
        || (['accepted', 'running'].includes(record.state) && (record.outcomeKnown || record.inputStopped))
        || (['succeeded', 'failed', 'cancelled'].includes(record.state) && (!record.outcomeKnown || !record.inputStopped))) {
        throw new Error('invalid receipt')
      }
      return record
    } catch (error) {
      if (error.code === 'ENOENT') throw receiptError('CHROME_OPERATION_NOT_FOUND')
      throw receiptError('CHROME_RECEIPT_UNAVAILABLE')
    } finally { await file?.close() }
  }
  async save(record) {
    const temporary = this.path(record.id, '.' + randomUUID() + '.tmp')
    const file = await open(temporary, 'wx', 0o600)
    try {
      await file.writeFile(JSON.stringify(record))
      await file.sync()
      await file.close()
      await rename(temporary, this.path(record.id))
      await this.sync()
    } finally {
      await file.close().catch(() => {})
      await unlink(temporary).catch(() => {})
    }
    return record
  }
  async begin(id, payload) {
    await this.directory()
    const payloadHash = OperationReceipts.hash(payload)
    let file
    try { file = await open(this.path(id), 'wx', 0o600) } catch (error) {
      if (error.code !== 'EEXIST') throw receiptError('CHROME_RECEIPT_UNAVAILABLE')
      const prior = await this.read(id)
      if (prior.payloadHash !== payloadHash) throw receiptError('CHROME_OPERATION_CONFLICT')
      return { record: prior, dispatch: false }
    }
    const record = { version: 1, id, payloadHash, state: 'accepted', outcomeKnown: false,
      inputStopped: false, createdMs: Date.now(), updatedMs: Date.now() }
    try {
      await file.writeFile(JSON.stringify(record))
      await file.sync()
    } finally { await file.close() }
    await this.sync()
    return { record, dispatch: true }
  }
  async cancellationRequested(id) {
    try { await lstat(this.path(id, '.cancel')); return true } catch (error) {
      if (error.code === 'ENOENT') return false
      throw receiptError('CHROME_RECEIPT_UNAVAILABLE')
    }
  }
  async cancel(id) {
    await this.directory()
    let file
    try {
      file = await open(this.path(id, '.cancel'), 'wx', 0o600)
      await file.sync()
    } catch (error) { if (error.code !== 'EEXIST') throw receiptError('CHROME_RECEIPT_UNAVAILABLE') }
    finally { await file?.close() }
    await this.sync()
    let record
    try { record = await this.read(id) } catch (error) {
      if (error.code !== 'CHROME_OPERATION_NOT_FOUND') throw error
      let claimed = true
      try { await lstat(this.path(id, '.lock')) } catch (missing) {
        if (missing.code !== 'ENOENT') throw receiptError('CHROME_RECEIPT_UNAVAILABLE')
        claimed = false
      }
      return { version: 1, id, state: claimed ? 'unknown' : 'cancelled',
        outcomeKnown: !claimed, inputStopped: !claimed, receiptExists: false, cancelRequested: true }
    }
    if (record.state === 'accepted') {
      try { await lstat(this.path(id, '.lock')) } catch (error) {
        if (error.code !== 'ENOENT') throw receiptError('CHROME_RECEIPT_UNAVAILABLE')
        return this.save({ ...record, state: 'cancelled', outcomeKnown: true, inputStopped: true, updatedMs: Date.now() })
      }
    }
    return record
  }
  async execute(id, payloadHash, operation) {
    const initial = await this.read(id)
    if (initial.payloadHash !== payloadHash) throw receiptError('CHROME_OPERATION_CONFLICT')
    if (initial.state !== 'accepted') return initial
    let lock
    try { lock = await open(this.path(id, '.lock'), 'wx', 0o600) } catch (error) {
      if (error.code === 'EEXIST') return this.read(id)
      throw receiptError('CHROME_RECEIPT_UNAVAILABLE')
    }
    try { await lock.writeFile(String(process.pid)); await lock.sync() } finally { await lock.close() }
    await this.sync()
    // A cancellation can win after the receipt was read but before the exclusive claim.
    if (await this.cancellationRequested(id)) {
      return this.save({ ...initial, state: 'cancelled', outcomeKnown: true, inputStopped: true, updatedMs: Date.now() })
    }
    const running = await this.save({ ...initial, state: 'running', updatedMs: Date.now() })
    if (await this.cancellationRequested(id)) {
      return this.save({ ...running, state: 'cancelled', outcomeKnown: true, inputStopped: true, updatedMs: Date.now() })
    }
    try {
      const result = await operation()
      if (Buffer.byteLength(JSON.stringify(result)) > 128_000) throw receiptError('CHROME_OPERATION_OUTPUT_LIMIT')
      return await this.save({ ...running, state: 'succeeded', outcomeKnown: true, inputStopped: true,
        result, updatedMs: Date.now() })
    } catch (error) {
      const code = operationFailureCode(error.message)
      const known = code !== 'CHROME_OPERATION_OUTCOME_UNKNOWN'
      return this.save({ ...running, state: known ? 'failed' : 'unknown', outcomeKnown: known,
        inputStopped: true, errorCode: code, updatedMs: Date.now() })
    }
  }
}
