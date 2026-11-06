(() => {
  const subscriptions = [], charts = [];
  async function start() {
    if (!window.okr?.data) return;
    await okr.ready();
    const words = () => okr.context.locale?.startsWith('en')
      ? { unknown: 'Unknown', empty: 'No observations', version: 'Data revision', failed: 'Data unavailable. Ask Main to check the source.' }
      : { unknown: '未知', empty: '尚无观测', version: '数据版本', failed: '数据尚不可用，请由 Main 核对来源。' };
    const status = document.getElementById('status');
    for (const element of document.querySelectorAll('[data-metric]')) {
      const chartElement = element.querySelector('[data-chart]');
      const chart = chartElement && window.echarts ? echarts.init(chartElement) : null;
      if (chart) charts.push(chart);
      const draw = data => {
        const text = words();
        const value = element.querySelector('[data-value]');
        const date = element.querySelector('[data-as-of]');
        if (value) value.textContent = data.latest.value ?? text.unknown;
        if (date) date.textContent = data.asOf || text.empty;
        element.querySelector('[data-quality]').textContent = data.quality === 'unknown' ? text.empty : '';
        document.getElementById('updated').textContent = `${text.version} ${data.revision}`;
        if (chart) {
          const style = getComputedStyle(document.documentElement);
          const label = { color: style.getPropertyValue('--text-dim').trim(), fontSize: parseFloat(style.getPropertyValue('--fs-meta')) };
          const line = { color: style.getPropertyValue('--border-subtle').trim() };
          chart.setOption({
            color: [style.getPropertyValue('--accent').trim()],
            textStyle: label,
            xAxis: { type: 'category', data: data.points.map(point => point.date), axisLabel: label, axisLine: { lineStyle: line }, axisTick: { lineStyle: line } },
            yAxis: { type: 'value', axisLabel: label, splitLine: { lineStyle: line } },
            series: [{ type: chartElement.dataset.chart === 'bar' ? 'bar' : 'line', data: data.points.map(point => point.value) }],
          });
        }
      };
      try {
        draw(await okr.data.read(element.dataset.metric));
        subscriptions.push(okr.data.subscribe(element.dataset.metric, draw));
      } catch { status.textContent = words().failed; return; }
    }
    status.hidden = true;
  }
  const resize = new ResizeObserver(() => charts.forEach(chart => chart.resize()));
  resize.observe(document.body);
  void start();
  window.addEventListener('pagehide', () => {
    resize.disconnect();
    subscriptions.forEach(unsubscribe => unsubscribe());
    charts.forEach(chart => chart.dispose());
  });
})();
