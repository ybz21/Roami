import assert from 'node:assert/strict'
import { once } from 'node:events'
import net from 'node:net'
import test from 'node:test'
import { handleConnection } from './driver.mjs'

test('a disconnected queued probe cannot block the next browser command', { timeout: 2000 }, async () => {
  let release
  const gate = new Promise(resolve => { release = resolve })
  let queue = gate
  const sockets = new Set()
  const session = { run: async (_verb, _flags, _pos, _timeout, io) => { io.log('real command completed') } }
  const server = net.createServer(conn => {
    sockets.add(conn)
    conn.on('close', () => sockets.delete(conn))
    queue = queue.then(() => handleConnection(conn, session))
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  let client
  try {
    const probe = net.connect(server.address().port, '127.0.0.1')
    await once(probe, 'connect')
    const closed = once(probe, 'close')
    probe.destroy()
    await closed
    await new Promise(resolve => setImmediate(resolve))
    client = net.connect(server.address().port, '127.0.0.1')
    await once(client, 'connect')
    const parts = []
    client.on('data', part => parts.push(part))
    const end = once(client, 'end')
    client.write(JSON.stringify({ argv: ['title'], cwd: process.cwd() }) + '\n')
    release()
    await end
    const response = JSON.parse(Buffer.concat(parts).toString())
    assert.equal(response.code, 0)
    assert.match(response.stdout, /real command completed/)
  } finally {
    release()
    client?.destroy()
    for (const socket of sockets) socket.destroy()
    server.close()
  }
})
