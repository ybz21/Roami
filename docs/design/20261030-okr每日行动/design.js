
(() => {
  const root = document.documentElement;
  root.dataset.pointer = navigator.maxTouchPoints > 0 ? 'coarse' : 'fine';
  document.addEventListener('pointerdown', event => { root.dataset.pointer = event.pointerType === 'mouse' ? 'fine' : 'coarse'; }, { passive: true });
  const theme = document.getElementById('theme-toggle');
  try { root.dataset.theme = localStorage.getItem('roami-okr-design-theme') || 'light'; } catch {}
  const labelTheme = () => { theme.textContent = root.dataset.theme === 'dark' ? '浅色' : '深色'; };
  labelTheme();
  theme.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem('roami-okr-design-theme', root.dataset.theme); } catch {}
    labelTheme();
  });
})();
