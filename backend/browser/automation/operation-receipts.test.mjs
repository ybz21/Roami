import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtemp, rm, writeFile, chmod, symlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { OperationReceipts } from './operation-receipts.mjs'

const id = 'a'.repeat(32)
async function fixture(run) {
  const root = await mkdtemp(join(tmpdir(), 'roami-operation-'))
  try { await run(new OperationReceipts(root), root) } finally { await rm(root, { recursive: true, force: true }) }
}

test('durable operation keys dispatch once and reject changed payloads', () => fixture(async receipts => {
  const first = await receipts.begin(id, ['click', '#confirm'])
  assert(first.dispatch)
  assert(!(await receipts.begin(id, ['click', '#confirm'])).dispatch)
  await assert.rejects(receipts.begin(id, ['click', '#delete']), /CHROME_OPERATION_CONFLICT/)
  let calls = 0
  const result = await receipts.execute(id, first.record.payloadHash, async () => { calls++; return { text: 'done' } })
  assert.equal(result.state, 'succeeded')
  assert.equal(result.inputStopped, true)
  assert.deepEqual(await receipts.execute(id, first.record.payloadHash, async () => { calls++ }), result)
  assert.equal(calls, 1)
}))

test('cancelling queued work prevents a late daemon from executing it', () => fixture(async receipts => {
  const first = await receipts.begin(id, ['fill'])
  const cancelled = await receipts.cancel(id)
  assert.equal(cancelled.state, 'cancelled')
  assert.equal(cancelled.inputStopped, true)
  let calls = 0
  await receipts.execute(id, first.record.payloadHash, async () => { calls++ })
  assert.equal(calls, 0)
}))

test('cancellation before admission prevents delayed creation from executing', () => fixture(async receipts => {
  const cancelled = await receipts.cancel(id)
  assert.equal(cancelled.receiptExists, false)
  assert.equal(cancelled.inputStopped, true)
  const admitted = await receipts.begin(id, ['click'])
  let calls = 0
  const result = await receipts.execute(id, admitted.record.payloadHash, async () => { calls++ })
  assert.equal(result.state, 'cancelled')
  assert.equal(calls, 0)
}))

test('a missing receipt with an execution claim never proves cancellation', () => fixture(async (receipts, root) => {
  await writeFile(join(root, id + '.lock'), '', { mode: 0o600 })
  const cancelled = await receipts.cancel(id)
  assert.equal(cancelled.state, 'unknown')
  assert.equal(cancelled.inputStopped, false)
}))

test('cancelling an active operation waits for its actual terminal receipt', () => fixture(async receipts => {
  const first = await receipts.begin(id, ['click'])
  let release, started
  const running = new Promise(resolve => { started = resolve })
  const gate = new Promise(resolve => { release = resolve })
  let calls = 0
  const executing = receipts.execute(id, first.record.payloadHash, async () => {
    calls++; started(); await gate; return { changed: true }
  })
  await running
  const pending = await receipts.cancel(id)
  assert.equal(pending.state, 'running')
  assert.equal(pending.inputStopped, false)
  const duplicate = await receipts.execute(id, first.record.payloadHash, async () => { calls++ })
  assert.equal(duplicate.state, 'running')
  release()
  const result = await executing
  assert.equal(result.state, 'succeeded')
  assert.equal(result.inputStopped, true)
  assert.equal(calls, 1)
}))

test('errors expose stable codes and preserve unknown side effects', () => fixture(async receipts => {
  const first = await receipts.begin(id, ['click'])
  const result = await receipts.execute(id, first.record.payloadHash, async () => {
    throw new Error('secret server details')
  })
  assert.equal(result.state, 'unknown')
  assert.equal(result.outcomeKnown, false)
  assert.equal(result.inputStopped, true)
  assert(!JSON.stringify(result).includes('secret server details'))
}))

test('target preflight rejection is known and does not masquerade as a successful action', () => fixture(async receipts => {
  const first = await receipts.begin(id, ['fill'])
  const result = await receipts.execute(id, first.record.payloadHash, async () => {
    throw new Error('CHROME_TARGET_NOT_FOUND')
  })
  assert.equal(result.state, 'failed')
  assert.equal(result.outcomeKnown, true)
}))

test('corrupted, symlinked and publicly readable receipts are never replayed', () => fixture(async (receipts, root) => {
  await receipts.begin(id, ['click'])
  await writeFile(receipts.path(id), '{partial')
  await assert.rejects(receipts.begin(id, ['click']), /CHROME_RECEIPT_UNAVAILABLE/)
  await rm(receipts.path(id))
  await symlink('/etc/passwd', receipts.path(id))
  await assert.rejects(receipts.read(id), /CHROME_RECEIPT_UNAVAILABLE/)
  await rm(receipts.path(id))
  await receipts.begin(id, ['click'])
  await chmod(receipts.path(id), 0o644)
  await assert.rejects(receipts.read(id), /CHROME_RECEIPT_UNAVAILABLE/)
  await chmod(root, 0o755)
  await assert.rejects(receipts.read(id), /CHROME_RECEIPT_ROOT_INVALID/)
}))

test('executor death leaves a persistent claim that a new process cannot replay', () => fixture(async (receipts, root) => {
  const first = await receipts.begin(id, ['click'])
  const source = new URL('./operation-receipts.mjs', import.meta.url).href
  const script = `import { OperationReceipts } from ${JSON.stringify(source)};
    const receipts = new OperationReceipts(process.argv[1]);
    await receipts.execute(process.argv[2], process.argv[3], async () => process.exit(17));`
  await assert.rejects(promisify(execFile)(process.execPath, ['--input-type=module', '-e', script, root, id, first.record.payloadHash]), error => error.code === 17)
  const recovered = new OperationReceipts(root)
  let calls = 0
  const result = await recovered.execute(id, first.record.payloadHash, async () => { calls++ })
  assert.equal(result.state, 'running')
  assert.equal(result.inputStopped, false)
  assert.equal(calls, 0)
  assert.equal((await recovered.cancel(id)).state, 'running')
}))

test('a full tab pool persists a known rejection without replaying creation', () => fixture(async (receipts, root) => {
  const first = await receipts.begin(id, ['new'])
  const result = await receipts.execute(id, first.record.payloadHash, async () => { throw new Error('BROWSER_TAB_BUDGET_EXCEEDED') })
  assert.equal(result.state, 'failed')
  assert.equal(result.outcomeKnown, true)
  assert.equal(result.inputStopped, true)
  const recovered = new OperationReceipts(root)
  let creations = 0
  const replay = await recovered.execute(id, first.record.payloadHash, async () => { creations++ })
  assert.equal(replay.state, 'failed')
  assert.equal(creations, 0)
}))
