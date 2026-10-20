import type { Catalog } from '../src/components/capabilities/CapabilityCatalog'
import type { ManagedEntry, ManagedKind } from '../src/components/capabilities/capability-format'

const initial = {
  skills: {
    'release-checklist': { name: 'release-checklist', description: '发布前检查变更、验证结果与交付产物，让每次交付都有据可查。', text: '# 发布检查\n\n## 执行步骤\n1. 阅读变更，确认本次范围。\n2. 运行项目要求的测试。\n3. 核对截图、文档与交付产物。\n\n## 输出\n一份简洁的发布检查报告。' },
    'writing-review': { name: 'writing-review', description: '检查文章结构与表达，给出具体的修改建议。', text: '# 写作检查\n\n阅读全文，检查逻辑、语气与可读性。保留作者原意，给出可直接应用的修改。' },
  },
  cli: { 'json-format': { name: 'json-format', description: '在工作区中格式化、校验 JSON 文件。', argv: ['python3', '-m', 'json.tool', '{input}'] } },
  mcp: { 'team-docs': { name: 'team-docs', config: { transport: 'streamable_http', url: 'https://docs.example.com/mcp' } }, 'local-files': { name: 'local-files', config: { transport: 'stdio', command: 'npx', args: ['-y', '@modelcontextprotocol/server-filesystem', '/workspace'] } } },
}
const managed: Record<ManagedKind, Record<string, ManagedEntry>> = structuredClone(initial)
const disabled = new Set<string>()
const connected = new Set(['team-docs'])
const plugins = [
  { manifest: { id: 'demo.notifications', name: 'notifications', version: '1.0.0', displayName: { 'zh-CN': '工作通知', 'en-US': 'Work notifications' }, description: { 'zh-CN': '在任务完成或需要确认时提醒你。', 'en-US': 'Notify you when work finishes or needs your attention.' }, runtime: { kind: 'builtin' }, contributes: { configFields: [{ key: 'destination', title: { 'zh-CN': '通知目标', 'en-US': 'Destination' }, description: { 'zh-CN': '选择接收通知的位置。', 'en-US': 'Choose where notifications arrive.' } }] }, permissions: { notifications: true } }, enabled: true, installed: '2026-10-21' },
  { manifest: { id: 'demo.archive', name: 'archive', version: '1.0.0', displayName: { 'zh-CN': '交付归档', 'en-US': 'Delivery archive' }, description: { 'zh-CN': '整理报告、截图和交付文件。', 'en-US': 'Organize reports, screenshots and deliverables.' }, runtime: { kind: 'builtin' }, contributes: {}, permissions: {} }, enabled: false, installed: '2026-10-21' },
]
const removedPlugins: typeof plugins = []
const uploadedTemplate = structuredClone(plugins[1])
const config: Record<string, string> = { destination: 'Roami' }
const foundations = ['read', 'bash', 'edit', 'write', 'tool_list', 'delegate', 'ask_user']
export function catalog(): Catalog {
  return {
    managed: structuredClone(managed),
    skills: [
      ...Object.values(managed.skills).map(item => ({ ...item, text: item.text || '', version: 'prototype', source: 'managed', enabled: !disabled.has(item.name), mutable: true })),
      { name: 'roami-dispatch', text: '# Roami 工作流\n\n管理项目、会话和任务，并核对执行结果。', version: 'builtin', source: 'builtin', enabled: true, mutable: false },
    ],
    tools: foundations.map(name => ({ name, description: name, schema: { type: 'object', properties: {} }, effect: 'read', source: 'builtin', mutable: false, enabled: true })),
    cli: [{ name: 'registered', commands: Object.values(managed.cli).map(item => ({ name: 'cli_' + item.name, description: item.description || '', source: 'external', enabled: !disabled.has('cli_' + item.name), mutable: true })) }, { name: 'mcp', commands: Object.keys(managed.mcp).filter(name => connected.has(name)).map(name => ({ name: 'mcp_' + name + '_search', description: 'Search connected content', enabled: !disabled.has('mcp_' + name + '_search'), mutable: true, source: 'external' })) }],
    mcp: Object.values(managed.mcp).map(item => ({ name: item.name, transport: String(item.config?.transport || 'stdio'), state: connected.has(item.name) ? 'connected' : 'not_connected', tools: connected.has(item.name) ? 1 : 0, toolNames: connected.has(item.name) ? ['mcp_' + item.name + '_search'] : [] })),
  }
}
export function installPrototypeApi() {
  const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
  window.fetch = async (input, init) => {
    const path = new URL(String(input), 'https://prototype.invalid').pathname.split('/api')[1] || ''
    const method = init?.method || 'GET'
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : {}
    if (path === '/agent/capability-settings') {
      if (method === 'PUT') body.enabled ? disabled.delete(body.name) : disabled.add(body.name)
      return response({ data: catalog() })
    }
    if (path.startsWith('/agent/capability-imports/')) {
      const [kind, name, action] = path.slice('/agent/capability-imports/'.length).split('/') as [ManagedKind, string?, string?]
      if (!managed[kind]) return response({ error: { code: 'INVALID_CAPABILITY_IMPORT' } }, 400)
      if (action === 'connect') { await new Promise(resolve => setTimeout(resolve, 450)); connected.add(name!); return response({ data: catalog() }) }
      if (method === 'DELETE') { delete managed[kind][decodeURIComponent(name!)]; return response({ data: catalog() }) }
      const entries: ManagedEntry[] = body.mcpServers ? Object.entries(body.mcpServers).map(([name, config]) => ({ name, config: config as Record<string, unknown> })) : [body]
      for (const item of entries) {
        if (!/^[a-z][a-z0-9_-]{0,63}$/.test(item.name) || kind === 'mcp' && item.name.length > 20) return response({ error: { code: 'INVALID_CAPABILITY_NAME' } }, 400)
        if (method === 'POST' && managed[kind][item.name]) return response({ error: { code: 'CAPABILITY_ALREADY_EXISTS' } }, 409)
        if (kind === 'skills' && !item.text?.trim()) return response({ error: { code: 'INVALID_CAPABILITY_IMPORT' } }, 400)
      }
      entries.forEach(item => { managed[kind][item.name] = item })
      return response({ data: catalog() })
    }
    if (path === '/plugins') return response(plugins)
    if (path === '/plugin/status') return response({ daemon: { running: true } })
    if (path.startsWith('/plugins/')) {
      const [rawId, operation] = path.slice('/plugins/'.length).split('/')
      const id = decodeURIComponent(rawId)
      if (operation === 'config') { if (method === 'PUT') Object.assign(config, body.set); return response(config) }
      if (method === 'DELETE') {
        const index = plugins.findIndex(plugin => plugin.manifest.id === id)
        if (index >= 0) removedPlugins.push(...plugins.splice(index, 1))
        return response({})
      }
      if (operation === 'restore') {
        const index = removedPlugins.findIndex(plugin => plugin.manifest.id === id)
        if (index >= 0) plugins.push(...removedPlugins.splice(index, 1))
        return response({})
      }
      const plugin = plugins.find(plugin => plugin.manifest.id === id)
      if (plugin && ['enable', 'disable'].includes(operation)) plugin.enabled = operation === 'enable'
      return response([])
    }
    if (path === '/preferences') return response({ data: {} })
    if (path === '/plugin/install') {
      const file = init?.body instanceof FormData ? init.body.get('file') : null
      const name = file instanceof File ? file.name : 'uploaded-plugin'
      const plugin = structuredClone(uploadedTemplate)
      plugin.manifest.id = 'demo.uploaded-' + Date.now(); plugin.manifest.name = name; plugin.manifest.displayName = { 'zh-CN': name, 'en-US': name }; plugin.enabled = false; plugin.manifest.runtime.kind = 'exec'
      plugins.push(plugin)
      return response({ data: null })
    }
    if (path === '/plugin/removed') return response(removedPlugins.filter(plugin => plugin.manifest.runtime.kind === 'builtin'))
    return response({ error: { code: 'PROTOTYPE_OPERATION_UNAVAILABLE' } }, 400)
  }
}
