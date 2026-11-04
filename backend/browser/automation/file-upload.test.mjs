import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createHash } from 'node:crypto'
import { mkdtemp, mkdir, writeFile, readFile, chmod, stat, symlink, truncate, rm } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { tmpdir } from 'node:os'
import { MAX_FILE_UPLOAD_BYTES, uploadArguments, withUploadFile } from './file-upload.mjs'
import { OperationReceipts, operationFailureCode } from './operation-receipts.mjs'
import { daemonRequestWithRetry } from './driver.mjs'

const digest = body => createHash('sha256').update(body).digest('hex')

test('upload requires an exact target, selector and absolute file, with valid constraints', () => {
  const path = join(tmpdir(), 'video.mp4')
  uploadArguments({ target: 'owned-target' }, ['input[type=file]', path])
  for (const flags of [{}, { target: 'owned', tab: '1' }, { target: 'owned', url: 'example' }, { target: 'owned', 'file-root': undefined }, { target: 'owned', 'max-file-bytes': '0' }, { target: 'owned', 'max-file-bytes': '9007199254740992' }, { target: 'owned', 'expected-file-sha256': 'wrong' }]) {
    assert.throws(() => uploadArguments(flags, ['#file', path]), /CHROME_UPLOAD_/)
  }
  for (const pos of [['#file', 'relative.mp4'], ['#file', path, path], ['#file'], ['', path]]) assert.throws(() => uploadArguments({ target: 'owned' }, pos), /CHROME_UPLOAD_ARGUMENTS_INVALID/)
})

test('selection receives a private stable snapshot with actual file identity and removes it afterward', async () => {
  const root = await mkdtemp(join(tmpdir(), 'roami-file-source-'))
  let snapshot
  try {
    const body = Buffer.from('original\0media bytes'), source = join(root, '中文 demo.mp4')
    await writeFile(source, body)
    const result = await withUploadFile(source, { root, maxBytes: body.length, sha256: digest(body) }, async (path, file) => {
      snapshot = path
      assert.notEqual(path, source)
      assert.equal((await stat(dirname(path))).mode & 0o077, 0)
      assert.equal((await stat(path)).mode & 0o077, 0)
      await writeFile(source, 'changed source after snapshot')
      assert.deepEqual(await readFile(path), body)
      return file
    })
    assert.deepEqual(result, { name: '中文 demo.mp4', sizeBytes: body.length, sha256: digest(body) })
    await assert.rejects(stat(dirname(snapshot)), { code: 'ENOENT' })
  } finally { await rm(root, { recursive: true, force: true }) }
})

test('unreadable, empty, missing, symlink, out-of-root and mismatched files fail before selecting', async () => {
  const root = await mkdtemp(join(tmpdir(), 'roami-file-admission-'))
  let selected = 0
  const select = () => { selected++; throw new Error('must not select') }
  try {
    const allowed = join(root, 'allowed'), outside = join(root, 'outside')
    await mkdir(allowed); await mkdir(outside)
    const source = join(allowed, 'video.mp4'), secret = join(outside, 'private.mp4'), empty = join(allowed, 'empty.mp4'), unreadable = join(allowed, 'unreadable.mp4')
    await writeFile(source, 'video'); await writeFile(secret, 'private'); await writeFile(empty, ''); await writeFile(unreadable, 'blocked'); await chmod(unreadable, 0)
    await symlink(source, join(allowed, 'linked.mp4')); await symlink(outside, join(allowed, 'escape'))
    for (const [path, options, code] of [
      ['relative.mp4', {}, 'ARGUMENTS_INVALID'], [join(allowed, 'missing'), {}, 'FILE_UNAVAILABLE'],
      [empty, {}, 'FILE_INVALID'], [allowed, {}, 'FILE_INVALID'], [unreadable, {}, 'FILE_UNAVAILABLE|FILE_INVALID'],
      [join(allowed, 'linked.mp4'), {}, 'FILE_UNAVAILABLE'], [secret, { root: allowed }, 'OUTSIDE_ROOT'],
      [join(allowed, 'escape/private.mp4'), { root: allowed }, 'OUTSIDE_ROOT'],
      [source, { root: allowed, maxBytes: 4 }, 'LIMIT_EXCEEDED'], [source, { root: allowed, sha256: 'a'.repeat(64) }, 'HASH_MISMATCH'],
    ]) await assert.rejects(withUploadFile(path, options, select), new RegExp('CHROME_UPLOAD_(' + code + ')'))
    const tooLarge = join(allowed, 'too-large.mp4')
    await writeFile(tooLarge, ''); await truncate(tooLarge, MAX_FILE_UPLOAD_BYTES + 1)
    await assert.rejects(withUploadFile(tooLarge, { root: allowed }, select), /CHROME_UPLOAD_TRANSPORT_LIMIT_EXCEEDED/)
    assert.equal(selected, 0)
  } finally { await rm(root, { recursive: true, force: true }) }
})

test('an unknown selection is not dispatched twice and its private snapshot is reclaimed', async () => {
  const root = await mkdtemp(join(tmpdir(), 'roami-upload-unknown-'))
  let selected = 0, snapshot
  try {
    const source = join(root, 'video.mp4'), payload = ['upload', '#file', source], id = 'a'.repeat(32)
    await writeFile(source, 'video')
    const receipts = new OperationReceipts(join(root, 'receipts'))
    const first = await receipts.begin(id, payload)
    const result = await receipts.execute(id, first.record.payloadHash, () => withUploadFile(source, { root }, async path => {
      selected++; snapshot = path
      throw new Error('connection lost after selecting')
    }))
    assert.equal(result.state, 'unknown'); assert.equal(result.outcomeKnown, false)
    assert.equal((await receipts.begin(id, payload)).dispatch, false)
    await receipts.execute(id, first.record.payloadHash, () => { selected++; return {} })
    assert.equal(selected, 1)
    await assert.rejects(stat(dirname(snapshot)), { code: 'ENOENT' })
    assert.equal(operationFailureCode('CHROME_UPLOAD_OUTSIDE_ROOT'), 'CHROME_UPLOAD_OUTSIDE_ROOT')
    assert.equal(operationFailureCode('CHROME_UPLOAD_NETWORK_FAILED'), 'CHROME_OPERATION_OUTCOME_UNKNOWN')
  } finally { await rm(root, { recursive: true, force: true }) }
})

test('upload transport makes only one attempt even when the connection fails before acknowledgement', async () => {
  let calls = 0
  const result = await daemonRequestWithRetry(['upload', '#file', '/tmp/video.mp4', '--target', 'owned'], 100, 'upload', async () => { calls++; return { resp: null, sentBeforeFailure: false } }, async () => {})
  assert.equal(result, null); assert.equal(calls, 1)
})
