function bootstrap(boot) {
  'use strict';
  const allowed = new Set(boot.metricIds), subscriptions = new Map();
  let datasets = {}, context = {}, port, settled = false, failedEarly = false;
  let finish;
  const ready = new Promise(resolve => { finish = resolve; });
  document.documentElement.style.visibility = 'hidden';
  const permitted = id => typeof id === 'string' && allowed.has(id);
  const data = Object.freeze({
    ids: Object.freeze([...allowed]),
    async read(id) {
      if (!permitted(id)) throw new Error('DATASET_NOT_ALLOWED');
      await ready;
      if (!Object.hasOwn(datasets, id)) throw new Error('DATASET_UNAVAILABLE');
      return structuredClone(datasets[id]);
    },
    subscribe(id, callback) {
      if (!permitted(id) || typeof callback !== 'function') throw new Error('DATASET_NOT_ALLOWED');
      if (!subscriptions.has(id)) subscriptions.set(id, new Set());
      const listeners = subscriptions.get(id);
      listeners.add(callback);
      return () => { listeners.delete(callback); if (!listeners.size) subscriptions.delete(id); };
    },
  });
  const api = { data, ready: () => ready };
  Object.defineProperty(api, 'context', { get: () => Object.freeze({ ...context }) });
  Object.defineProperty(window, 'okr', { value: Object.freeze(api), writable: false, configurable: false });
  function receive(event) {
    const value = event.data;
    if (value?.type !== 'okr:snapshot' || value.digest !== boot.digest) return;
    if (failedEarly) { port.postMessage({ type: 'okr:error', digest: boot.digest }); return; }
    context = value.context || {};
    for (const [name, text] of Object.entries(context.tokens || {})) document.documentElement.style.setProperty(name, text);
    document.documentElement.lang = context.locale || 'zh-CN';
    document.documentElement.dataset.theme = context.theme;
    document.documentElement.dataset.size = context.size;
    document.documentElement.dataset.pointer = context.pointer;
    datasets = {};
    for (const id of allowed) if (Object.hasOwn(value.datasets || {}, id)) datasets[id] = value.datasets[id];
    if (!settled) {
      for (const source of value.libraries || []) {
        const script = document.createElement('script');
        script.textContent = source;
        document.head.append(script);
      }
      if (failedEarly) return;
      settled = true;
      finish(api.context);
      document.documentElement.style.visibility = '';
      port.postMessage({ type: 'okr:ready', digest: boot.digest });
    }
    for (const [id, listeners] of subscriptions) {
      if (!Object.hasOwn(datasets, id)) continue;
      for (const callback of listeners) { try { callback(structuredClone(datasets[id])); } catch {} }
    }
  }
  function initialize(event) {
    if (event.source !== parent || event.data?.type !== 'okr:init' || event.data.nonce !== boot.nonce || event.data.digest !== boot.digest || !event.ports[0] || port) return;
    port = event.ports[0];
    window.removeEventListener('message', initialize);
    port.onmessage = receive;
    port.start();
  }
  const failed = () => { failedEarly = true; if (port) port.postMessage({ type: 'okr:error', digest: boot.digest }); };
  window.addEventListener('error', failed, true);
  window.addEventListener('unhandledrejection', failed);
  window.addEventListener('message', initialize);
  window.addEventListener('pagehide', () => { port?.close(); subscriptions.clear(); });
}
