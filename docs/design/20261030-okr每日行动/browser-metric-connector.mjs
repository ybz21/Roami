import { execFileSync } from 'node:child_process'
import { readFile, writeFile } from 'node:fs/promises'

const args = process.argv.slice(2)
function option(name) { const index = args.indexOf(name); if (index < 0 || !args[index + 1]) throw new Error(`Missing ${name}`); return args[index + 1] }
try {
  const spec = JSON.parse(await readFile(option('--spec'),'utf8'))
  const target = option('--target'), out = option('--out')
  if (spec.method !== 'browser' || !/^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/.test(spec.id) || !Number.isInteger(spec.revision) || spec.revision < 1) throw new Error('Invalid connector identity')
  const origin = new URL(spec.origin)
  if (!['127.0.0.1','localhost'].includes(origin.hostname) || !['http:','https:'].includes(origin.protocol) || origin.origin !== spec.origin || spec.path !== '/fixtures/creator-console.html') throw new Error('This design runner only reads the local creator fixture')
  if (typeof spec.expectedAccountId !== 'string' || !spec.expectedAccountId || ![spec.account,spec.date].every(item => item && typeof item.selector === 'string' && item.selector && typeof item.attribute === 'string' && item.attribute)) throw new Error('Missing account/date contract')
  if (!Array.isArray(spec.fields) || spec.fields.length < 1 || spec.fields.length > 40 || spec.fields.some(f => !/^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/.test(f.id) || typeof f.selector !== 'string' || !f.selector || typeof f.unit !== 'string' || !f.unit) || new Set(spec.fields.map(f => f.id)).size !== spec.fields.length) throw new Error('Invalid field contract')
  const expression = `(() => {
    const spec = ${JSON.stringify(spec)};
    if (location.origin !== spec.origin || location.pathname !== spec.path) throw new Error('Source URL mismatch');
    const one = selector => { const nodes = document.querySelectorAll(selector); if (nodes.length !== 1) throw new Error('Field missing or ambiguous: ' + selector); return nodes[0] };
    const accountId = one(spec.account.selector).getAttribute(spec.account.attribute);
    if (accountId !== spec.expectedAccountId) throw new Error('Account mismatch');
    const date = one(spec.date.selector).getAttribute(spec.date.attribute);
    if (!/^\\d{4}-\\d{2}-\\d{2}$/.test(date) || !Number.isFinite(Date.parse(date)) || new Date(date).toISOString().slice(0,10) !== date) throw new Error('Invalid observation date');
    const values = Object.fromEntries(spec.fields.map(field => {
      const raw = one(field.selector).textContent.trim();
      if (!/^(?:\\d+|\\d{1,3}(?:,\\d{3})+)(?:\\.\\d+)?$/.test(raw)) throw new Error('Unrecognized numeric format: ' + field.id);
      const value = Number(raw.replaceAll(',', ''));
      if (!Number.isFinite(value) || value < 0 || value > Number.MAX_SAFE_INTEGER) throw new Error('Value outside supported range');
      return [field.id,{ value,unit:field.unit }];
    }));
    return { connectorId:spec.id,connectorRevision:spec.revision,accountId,date,capturedAt:new Date().toISOString(),sourceUrl:location.href,evidenceKind:'browser-fixture',values };
  })()`
  const response = execFileSync('roami',['chrome','eval',expression,'--target',target,'--no-retry'],{ encoding:'utf8',stdio:'pipe',timeout:30000,maxBuffer:1024*1024 })
  const sample = JSON.parse(response)
  if (!sample?.values || sample.accountId !== spec.expectedAccountId || sample.connectorId !== spec.id || sample.evidenceKind !== 'browser-fixture') throw new Error('Invalid browser receipt')
  await writeFile(out,JSON.stringify(sample,null,2)+'\n',{ flag:'wx' })
  process.stdout.write(`Read ${Object.keys(sample.values).length} fields for ${sample.accountId} on ${sample.date}; local fixture only. Saved ${out}\n`)
} catch(error) {
  const detail = error.stderr?.toString().split('\n')[0] || error.message
  process.stderr.write(`Connector stopped: ${detail}\n`)
  process.exitCode = 1
}
