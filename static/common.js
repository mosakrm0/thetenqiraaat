// common.js — shared utilities for Thetenqiraaat

const THEME_KEY = 'qiraat-theme';

function escHtml(v) {
  return String(v ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function escAttr(v) {
  return escHtml(v);
}

function applyTheme(theme) {
  const safe = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', safe);
  const btn = document.getElementById('theme-toggle') || document.getElementById('landing-theme-toggle');
  if (btn) {
    const isLight = safe === 'light';
    btn.textContent = isLight ? '🌙' : '☀️';
    btn.title = isLight ? 'التحويل للوضع الداكن' : 'التحويل للوضع الفاتح';
    btn.setAttribute('aria-label', btn.title);
  }
}

function initTheme() {
  applyTheme(localStorage.getItem(THEME_KEY) || 'light');
}

function toggleTheme() {
  const now = document.documentElement.getAttribute('data-theme') || 'light';
  const next = now === 'dark' ? 'light' : 'dark';
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
}

function toast(msg, durationMs = 2600) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => t.classList.remove('show'), durationMs);
}

function fmtTime(sec) {
  if (!Number.isFinite(sec) || sec < 0) return '0:00';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function createCache(prefix) {
  const memCache = new Map();

  function _key(k) {
    return `${prefix}${k}`;
  }

  function _evictStorage() {
    const entries = [];
    const now = Date.now();
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(prefix)) {
        try {
          const parsed = JSON.parse(localStorage.getItem(k));
          entries.push({ k, exp: parsed.exp });
        } catch {
          localStorage.removeItem(k);
        }
      }
    }
    const valid = [];
    for (const e of entries) {
      if (e.exp <= now) localStorage.removeItem(e.k);
      else valid.push(e);
    }
    if (valid.length > 10) {
      valid.sort((a, b) => a.exp - b.exp);
      const toRemove = Math.ceil(valid.length * 0.2);
      for (let i = 0; i < toRemove; i++) localStorage.removeItem(valid[i].k);
    }
  }

  function read(key) {
    const now = Date.now();
    const mem = memCache.get(key);
    if (mem) {
      if (mem.exp > now) return { value: mem.value, fresh: true };
      memCache.delete(key);
    }
    try {
      const raw = localStorage.getItem(_key(key));
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (parsed.exp > now) {
        memCache.set(key, parsed);
        return { value: parsed.value, fresh: true };
      }
      localStorage.removeItem(_key(key));
    } catch {}
    return null;
  }

  function write(key, value, ttlMs) {
    const entry = { exp: Date.now() + ttlMs, value };
    memCache.set(key, entry);
    try {
      localStorage.setItem(_key(key), JSON.stringify(entry));
    } catch {
      _evictStorage();
      try {
        localStorage.setItem(_key(key), JSON.stringify(entry));
      } catch {}
    }
  }

  return { read, write };
}

async function fetchJsonWithRetry(url, { retries = 2, timeoutMs = 15000, backoffMs = 400 } = {}) {
  let lastErr;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const resp = await fetch(url, { signal: ctrl.signal });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return await resp.json();
    } catch (err) {
      lastErr = err;
      if (attempt < retries) await sleep(backoffMs * (attempt + 1));
    } finally {
      clearTimeout(timer);
    }
  }
  throw lastErr;
}

async function getCachedJson(cache, { key, url, ttlMs, retries = 2 }) {
  const cached = cache.read(key);
  if (cached?.fresh) return cached.value;
  try {
    const data = await fetchJsonWithRetry(url, { retries });
    cache.write(key, data, ttlMs);
    return data;
  } catch (err) {
    if (cached?.value) {
      toast('تم العرض من النسخة المحفوظة بسبب مشكلة اتصال');
      return cached.value;
    }
    throw err;
  }
}

function normalizeAudioUrl(url) {
  if (typeof url !== 'string') return null;
  const trimmed = url.trim();
  if (!trimmed || trimmed === 'null' || trimmed === 'undefined') return null;
  try {
    const parsed = new URL(trimmed, window.location.href);
    if (!['http:', 'https:', 'blob:', 'data:'].includes(parsed.protocol)) return null;
    return parsed.href;
  } catch {
    return null;
  }
}

function buildProxyAudioUrl(url) {
  if (!url || !url.startsWith('https://')) return null;
  if (url.includes('/api/audio-proxy')) return null;
  return `/api/audio-proxy?url=${encodeURIComponent(url)}`;
}

window.Common = {
  escHtml,
  escAttr,
  initTheme,
  applyTheme,
  toggleTheme,
  toast,
  fmtTime,
  createCache,
  fetchJsonWithRetry,
  getCachedJson,
  normalizeAudioUrl,
  buildProxyAudioUrl,
};
window.toggleTheme = toggleTheme;
