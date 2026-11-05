(() => {
  const subscriptions = [];
  async function start() {
    if (!window.okr?.data) return;
    const status = document.getElementById('status');
    for (const element of document.querySelectorAll('[data-metric]')) {
      const draw = data => {
        element.querySelector('[data-value]').textContent = data.latest.value ?? '未知';
        element.querySelector('[data-as-of]').textContent = data.asOf || '尚无观测';
        element.querySelector('[data-quality]').textContent = data.quality === 'stale' ? '采集未完成，保留上次有效值' : '';
        element.querySelector('[data-quality]').dataset.quality = data.quality;
        document.getElementById('updated').textContent = `数据版本 ${data.revision}`;
      };
      try {
        draw(await okr.data.read(element.dataset.metric));
        subscriptions.push(okr.data.subscribe(element.dataset.metric, draw));
      } catch { status.textContent = '数据尚不可用，请由 Main 核对来源'; return; }
    }
    status.hidden = true;
  }
  void start();
  window.addEventListener('pagehide', () => subscriptions.forEach(unsubscribe => unsubscribe()));
})();
