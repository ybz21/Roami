export function mountSourceCreation(byId, bind, root) {
  const directory = {
    api: ['local-chat', 'local-vision'],
    openrouter: ['qwen/qwen3-coder:free', 'google/gemma:free'],
    magpie: ['hy4flash-free'],
  }
  const defaults = { openrouter: 'OpenRouter 免费模型', magpie: 'WorkBuddy' }
  const input = byId('source-address')
  const type = byId('source-type')
  const plugin = byId('source-plugin')
  const status = byId('source-create-status')
  const discover = byId('source-discover')
  const selection = new Set()
  const save = byId('source-save')
  const matches = byId('source-matches')

  function resetDirectory() {
    byId('source-directory').hidden = true
    byId('source-search').value = ''
    selection.clear()
    save.disabled = true
    status.textContent = '演示目录 · 选择模型后保存'
    input.removeAttribute('aria-invalid')
    plugin.removeAttribute('aria-invalid')
  }
  function chooseType() {
    const kind = type.value
    input.value = kind === 'openrouter' ? 'https://openrouter.ai/api/v1' : ''
    input.readOnly = kind === 'openrouter'
    byId('source-address-row').hidden = kind === 'magpie'
    byId('source-protocol-row').hidden = kind !== 'api'
    byId('source-plugin-row').hidden = kind !== 'magpie'
    discover.textContent = { api: '拉取所有模型', openrouter: '拉取免费模型', magpie: '识别插件' }[kind]
    resetDirectory()
  }
  function renderDirectory() {
    const query = byId('source-search').value.trim().toLowerCase()
    matches.replaceChildren(...directory[type.value].filter(id => id.toLowerCase().includes(query)).map(id => {
      const label = document.createElement('label')
      const checkbox = document.createElement('input')
      checkbox.type = 'checkbox'
      checkbox.value = id
      checkbox.checked = selection.has(id)
      label.append(checkbox, id)
      return label
    }))
    if (!matches.children.length) matches.textContent = '没有匹配模型。'
  }
  bind(type, 'change', chooseType)
  bind(input, 'input', resetDirectory)
  bind(plugin, 'input', resetDirectory)
  bind(discover, 'click', () => {
    if (type.value === 'api') {
      const url = URL.canParse(input.value.trim()) && new URL(input.value.trim())
      const local = url && (/^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|\[(::1\]|f[cd]))/i.test(url.hostname) || url.hostname === 'localhost')
      if (!url || !['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || (url.protocol === 'http:' && !local)) {
        input.setAttribute('aria-invalid', 'true')
        status.textContent = url?.protocol === 'http:' && !local ? '公网模型源需要 HTTPS。' : '填写有效的服务地址再读取目录。'
        return
      }
    }
    if (type.value === 'magpie' && !['packages/workbuddy', 'https://github.com/magpie-community/plugins/tree/main/packages/workbuddy'].includes(plugin.value.trim().replace(/\/$/, ''))) {
      plugin.setAttribute('aria-invalid', 'true')
      status.textContent = '演示目录包含 packages/workbuddy。'
      return
    }
    renderDirectory()
    byId('source-directory').hidden = false
    status.textContent = '已读取演示目录。'
  })
  bind(byId('source-search'), 'input', renderDirectory)
  bind(matches, 'change', event => {
    const checkbox = event.target
    if (checkbox.checked) selection.add(checkbox.value)
    else selection.delete(checkbox.value)
    save.disabled = selection.size === 0
  })
  bind(byId('source-form'), 'submit', event => {
    event.preventDefault()
    if (!selection.size) return
    const name = byId('source-name').value.trim() || defaults[type.value] || new URL(input.value.trim()).host
    const ids = [...selection]
    root.dispatchEvent(new CustomEvent('prototype-source-saved', { bubbles: true, detail: { source: name, ids } }))
    const row = document.createElement('li')
    row.textContent = name + ' · ' + ids.join('、')
    byId('saved-sources').append(row)
    byId('source-saved').textContent = '已保存 ' + ids.length + ' 个演示模型。'
    byId('source-form').reset()
    byId('source-create').open = false
    chooseType()
  })
}
