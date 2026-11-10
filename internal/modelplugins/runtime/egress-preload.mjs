import net from 'node:net'

// Only this transport socket crosses the network namespace boundary.
let connections = 0
const server = net.createServer(client => {
  if (++connections > 32) { connections--; client.destroy(); return }
  const upstream = net.createConnection('/run/model-egress.sock')
  let closed = false
  const close = () => {
    if (closed) return
    closed = true
    connections--
    client.destroy()
    upstream.destroy()
  }
  client.on('error', close).on('close', close)
  upstream.on('error', close).on('close', close)
  client.pipe(upstream).pipe(client)
})
await new Promise((resolve, reject) => {
  server.once('error', reject)
  server.listen(18080, '127.0.0.1', resolve)
})
server.unref()
