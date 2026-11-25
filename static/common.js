// common.js — shared utilities for Thetenqiraaat
(function () {
  'use strict';

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
    btn.textContent = isLight ? 'النمط الداكن' : 'النمط الكلاسيكي';
    btn.title = isLight ? 'التحويل للنمط الداكن' : 'التحويل للنمط الكلاسيكي';
    btn.setAttribute('aria-label', btn.title);
  }
}

function initTheme() {
  let saved = 'light';
  try {
    saved = localStorage.getItem(THEME_KEY) || 'light';
  } catch {}
  applyTheme(saved);
}

function toggleTheme() {
  const now = document.documentElement.getAttribute('data-theme') || 'light';
  const next = now === 'dark' ? 'light' : 'dark';
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch {}
  applyTheme(next);
}

function normalizeArabicSearch(str) {
  return String(str || '')
    .replace(/[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640\u00A0]/g, '')
    .replace(/[أإآٱ]/g, 'ا')
    .replace(/ى/g, 'ي')
    .replace(/ة/g, 'ه')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
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
    const keys = [];
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k && k.startsWith(prefix)) keys.push(k);
      }
      for (const k of keys) {
        try {
          const parsed = JSON.parse(localStorage.getItem(k));
          entries.push({ k, exp: parsed.exp });
        } catch {
          localStorage.removeItem(k);
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
    } catch {}
  }

  function read(key, { allowStale = false } = {}) {
    const now = Date.now();
    const mem = memCache.get(key);
    if (mem) {
      if (mem.exp > now) return { value: mem.value, fresh: true };
      if (allowStale) return { value: mem.value, fresh: false };
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
      if (allowStale) {
        return { value: parsed.value, fresh: false };
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
  const cached = cache.read(key, { allowStale: true });
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

const MOBILE_DRAWER_BP = 900;
const MOBILE_BAR_BP = 768;
let _responsiveShellBound = false;

function isMobileDrawer() {
  return window.innerWidth <= MOBILE_DRAWER_BP;
}

function syncSidebarUi() {
  const sb = document.getElementById('sidebar');
  if (!sb) return;
  const isOpen = !sb.classList.contains('collapsed');
  const drawerActive = isOpen && isMobileDrawer();
  const backdrop = document.getElementById('sb-backdrop');
  if (backdrop) {
    backdrop.classList.toggle('open', drawerActive);
    backdrop.setAttribute('aria-hidden', drawerActive ? 'false' : 'true');
  }
  document.body.classList.toggle('sb-drawer-open', drawerActive);
  const btn = document.getElementById('toggle-sb');
  if (btn) btn.setAttribute('aria-expanded', String(isOpen));
}

function toggleSidebar(forceCollapse) {
  const sb = document.getElementById('sidebar');
  if (!sb) return;
  if (forceCollapse === true) sb.classList.add('collapsed');
  else if (forceCollapse === false) sb.classList.remove('collapsed');
  else sb.classList.toggle('collapsed');
  syncSidebarUi();
}

function closeSidebarOnMobile() {
  if (isMobileDrawer()) toggleSidebar(true);
}

function initResponsiveShell() {
  const sb = document.getElementById('sidebar');
  if (sb && isMobileDrawer()) {
    sb.classList.add('collapsed');
  }
  const bar = document.getElementById('qiraat-bar');
  const barBtn = document.getElementById('qbar-toggle');
  if (bar && window.innerWidth <= MOBILE_BAR_BP) {
    bar.classList.add('is-collapsed');
    if (barBtn) {
      barBtn.textContent = 'إظهار الأدوات';
      barBtn.setAttribute('aria-expanded', 'false');
    }
  }
  syncSidebarUi();

  if (_responsiveShellBound) return;
  _responsiveShellBound = true;

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isMobileDrawer()) toggleSidebar(true);
  });

  let wasMobile = isMobileDrawer();
  window.addEventListener('resize', () => {
    const nowMobile = isMobileDrawer();
    if (!wasMobile && nowMobile) {
      toggleSidebar(true);
    } else {
      syncSidebarUi();
    }
    wasMobile = nowMobile;
  });
}

  window.Common = {
    escHtml,
    escAttr,
    normalizeArabicSearch,
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
    isMobileDrawer,
    syncSidebarUi,
    toggleSidebar,
    closeSidebarOnMobile,
    initResponsiveShell,
  };
  window.toggleTheme = toggleTheme;
})();
