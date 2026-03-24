function $(id) { return document.getElementById(id); }

const THEME_KEY = 'qiraat-theme';

function initTheme() {
  applyTheme(localStorage.getItem(THEME_KEY) || 'light');
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const btn = $('theme-toggle');
  if (btn) {
    btn.textContent = theme === 'light' ? '🌙' : '☀️';
    btn.title = theme === 'light' ? 'التحويل للوضع الداكن' : 'التحويل للوضع الفاتح';
    btn.setAttribute('aria-label', btn.title);
  }
}

function toggleTheme() {
  const now = document.documentElement.getAttribute('data-theme') || 'light';
  const next = now === 'dark' ? 'light' : 'dark';
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
}

window.toggleTheme = toggleTheme;
initTheme();
