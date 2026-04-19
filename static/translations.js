const API_BASE = 'https://api.alquran.cloud/v1';
const THEME_KEY = 'qiraat-theme';

let allSurahs = [];
let curSurah = null;
let catalog = [];
let selected = new Set(['hafs_ar_text']);
let activeTab = 'mushaf';
let audios = {};

function esc(v) {
  return String(v ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function toast(msg) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1800);
}

const memCache = new Map();
const CACHE_PREFIX = 'translations-cache-v1:';

function cacheKey(key) { return `${CACHE_PREFIX}${key}`; }
function readCache(key) {
  const now = Date.now();
  const mem = memCache.get(key);
  if (mem) {
    if (mem.exp > now) return { value: mem.value, fresh: true };
    memCache.delete(key);
  }
  try {
    const raw = localStorage.getItem(cacheKey(key));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed.exp > now) {
      memCache.set(key, parsed);
      return { value: parsed.value, fresh: true };
    } else {
      localStorage.removeItem(cacheKey(key));
    }
  } catch {}
  return null;
}

function _evictStorage() {
  let entries = [];
  const now = Date.now();
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.startsWith(CACHE_PREFIX)) {
      try {
        const parsed = JSON.parse(localStorage.getItem(k));
        entries.push({ k, exp: parsed.exp });
      } catch {
        localStorage.removeItem(k); // corrupted
      }
    }
  }
  
  // 1. Purge expired globally
  const valid = [];
  for (const e of entries) {
    if (e.exp <= now) {
      localStorage.removeItem(e.k);
    } else {
      valid.push(e);
    }
  }
  
  // 2. If still need space, purge oldest 20%
  if (valid.length > 10) {
    valid.sort((a, b) => a.exp - b.exp);
    const toRemove = Math.ceil(valid.length * 0.2);
    for (let i = 0; i < toRemove; i++) {
      localStorage.removeItem(valid[i].k);
    }
  }
}

function writeCache(key, value, ttlMs) {
  const entry = { exp: Date.now() + ttlMs, value };
  memCache.set(key, entry);
  try { 
    localStorage.setItem(cacheKey(key), JSON.stringify(entry)); 
  } catch { 
    _evictStorage();
    try {
      localStorage.setItem(cacheKey(key), JSON.stringify(entry));
    } catch {}
  }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
async function fetchJsonWithRetry(url, { retries = 2, timeoutMs = 15000, backoffMs = 400 } = {}) {
  let lastErr;
  for (let attempt = 0; attempt <= retries; attempt++) {
    const ctrl  = new AbortController();
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
async function getCachedJson({ key, url, ttlMs, retries = 2 }) {
  const cached = readCache(key);
  if (cached?.fresh) return cached.value;
  try {
    const data = await fetchJsonWithRetry(url, { retries });
    writeCache(key, data, ttlMs);
    return data;
  } catch (err) {
    if (cached?.value) { toast('تم العرض من النسخة المحفوظة بسبب مشكلة اتصال'); return cached.value; }
    throw err;
  }
}


function initTheme() {
  applyTheme(localStorage.getItem(THEME_KEY) || 'light');
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = theme === 'light' ? '🌙' : '☀️';
}

function toggleTheme() {
  const now = document.documentElement.getAttribute('data-theme') || 'light';
  const next = now === 'dark' ? 'light' : 'dark';
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
}

function toggleSB() {
  const sb = document.getElementById('sidebar');
  if (!sb) return;
  sb.classList.toggle('collapsed');
}

function toggleQiraatBar() {
  const bar = document.getElementById('qiraat-bar');
  const btn = document.getElementById('qbar-toggle');
  if (!bar || !btn) return;
  bar.classList.toggle('is-collapsed');
  const collapsed = bar.classList.contains('is-collapsed');
  btn.textContent = collapsed ? 'إظهار الأدوات' : 'إخفاء الأدوات';
  btn.setAttribute('aria-expanded', String(!collapsed));
}

function renderList(list) {
  const el = document.getElementById('surah-list');
  el.innerHTML = list.length
    ? list.map(s => `<div class="s-item${curSurah?.number===s.number?' active':''}" onclick="pickSurah(${s.number})">
        <div class="s-num">${s.number}</div>
        <div class="s-name">${esc(s.name)}</div>
        <div class="s-count">${s.numberOfAyahs} آية</div>
      </div>`).join('')
    : '<div style="text-align:center;padding:20px;color:var(--txt2)">لا نتائج</div>';
}

function fmtTime(sec) {
  if (!Number.isFinite(sec) || sec < 0) return '0:00';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function setState(pid, state) {
  const btn = document.getElementById(`pbtn-${pid}`);
  if (!btn) return;
  btn.textContent = state === 'playing' ? '⏸' : '▶';
}

function resetBar(pid) {
  const bar = document.getElementById(`pbar-${pid}`);
  const tim = document.getElementById(`ptim-${pid}`);
  if (bar) bar.style.width = '0%';
  if (tim) tim.textContent = '0:00';
}

function updateBar(pid, a) {
  const bar = document.getElementById(`pbar-${pid}`);
  const tim = document.getElementById(`ptim-${pid}`);
  if (!a || !bar || !tim) return;
  const dur = a.duration;
  const cur = a.currentTime;
  if (Number.isFinite(dur) && dur > 0) {
    bar.style.width = `${Math.max(0, Math.min(100, (cur / dur) * 100))}%`;
    tim.textContent = `${fmtTime(cur)}`;
  } else {
    tim.textContent = fmtTime(cur);
  }
}

function seek(pid, e, trackEl) {
  const a = audios[pid];
  if (!a || !trackEl || !Number.isFinite(a.duration) || a.duration <= 0) return;
  const rect = trackEl.getBoundingClientRect();
  const x = e.clientX - rect.left;
  const ratio = Math.max(0, Math.min(1, x / rect.width));
  a.currentTime = ratio * a.duration;
}

function stopAll() {
  Object.entries(audios).forEach(([pid, a]) => {
    if (a && !a.paused) a.pause();
    setState(pid, 'idle');
  });
}

function playerHTML(pid, url) {
  if (!url) return '<div class="audio-player disabled">لا يتوفر صوت</div>';
  return `<div class="audio-player" data-pid="${pid}" data-url="${url}">
    <button class="play-btn" id="pbtn-${pid}">▶</button>
    <div class="prog-track" id="ptrk-${pid}">
      <div class="prog-rail"><div class="prog-bar" id="pbar-${pid}"></div></div>
    </div>
    <span class="time-lbl" id="ptim-${pid}">0:00</span>
  </div>`;
}

async function togglePlay(pid, url) {
  Object.entries(audios).forEach(([k, a]) => {
    if (k !== pid && a && !a.paused) {
      a.pause();
      setState(k, 'idle');
    }
  });

  let a = audios[pid];
  if (!a) {
    a = new Audio();
    audios[pid] = a;
    a.addEventListener('timeupdate', () => updateBar(pid, a));
    a.addEventListener('ended', () => { setState(pid, 'idle'); resetBar(pid); });
    a.addEventListener('error', () => { setState(pid, 'idle'); toast('تعذر تشغيل الصوت'); });
  }

  if (!a.src || a.src !== url) {
    try {
      a.src = url;
    } catch {
      toast('ملف الصوت غير صالح');
      return;
    }
  }

  if (!a.paused) {
    a.pause();
    setState(pid, 'idle');
    return;
  }

  try {
    await a.play();
    setState(pid, 'playing');
  } catch {
    setState(pid, 'idle');
    toast('تعذر تشغيل الصوت');
  }
}

function bindPlayers() {
  // Deprecated: O(N) looping bypassed in favor of global Event Delegation below
}

document.addEventListener('click', (e) => {
  const btn = e.target.closest('.play-btn');
  if (btn) {
    e.stopPropagation();
    const player = btn.closest('.audio-player');
    if (player) togglePlay(player.dataset.pid, player.dataset.url);
    return;
  }
  
  const trk = e.target.closest('.prog-track');
  if (trk) {
    const player = trk.closest('.audio-player');
    if (player) seek(player.dataset.pid, e, trk);
  }
});

function filterArr(q) {
  if (!q) return allSurahs;
  const qq = String(q).toLowerCase();
  return allSurahs.filter(s =>
    String(s.name).includes(q) ||
    String(s.englishName || '').toLowerCase().includes(qq) ||
    String(s.number).startsWith(q)
  );
}

function filterSurahs(q) {
  renderList(filterArr(q));
}

async function loadSurahs() {
  try {
    const d = await getCachedJson({ key: 'surah-list', url: `${API_BASE}/surah`, ttlMs: 1000 * 60 * 60 * 12 });
    allSurahs = d.data || [];
    renderList(allSurahs);
  } catch { toast('تعذّر تحميل السور'); }
}

function selectedByLanguage(lang) {
  return catalog.find(c => selected.has(c.key) && (c.language || '') === lang);
}

function languageLabel(code) {
  const c = String(code || '').toLowerCase();
  const map = {
    ar: 'العربية',
    en: 'English',
    ur: 'اردو',
    fa: 'فارسی',
    tr: 'Türkçe',
    fr: 'Français',
    de: 'Deutsch',
    es: 'Español',
    ru: 'Русский',
    id: 'Bahasa Indonesia',
    ms: 'Bahasa Melayu',
    az: 'Azərbaycanca',
    bs: 'Bosanski',
    bn: 'বাংলা',
    hi: 'हिन्दी',
    ps: 'پښتو',
    dv: 'ދިވެހި',
    cs: 'Čeština',
    nl: 'Nederlands',
    it: 'Italiano',
    pt: 'Português',
    sv: 'Svenska',
    no: 'Norsk',
    da: 'Dansk',
    fi: 'Suomi',
    pl: 'Polski',
    ro: 'Română',
    sq: 'Shqip',
    ku: 'Kurdî',
    tg: 'Тоҷикӣ',
    ta: 'தமிழ்',
    te: 'తెలుగు',
    ml: 'മലയാളം',
    ha: 'Hausa',
    sw: 'Kiswahili',
  };

  if (map[c]) return map[c];

  // Prefer native language self-name when available.
  try {
    if (c) {
      const native = new Intl.DisplayNames([c], { type: 'language' }).of(c);
      if (native) return native;
    }
  } catch (_) {}

  return 'لغة غير معروفة';
}

function buildChips() {
  const bar = document.getElementById('qiraat-bar');
  const rng = bar.querySelector('.range-wrap');
  bar.querySelectorAll('.q-chip').forEach(n => n.remove());

  catalog.forEach(item => {
    const c = document.createElement('div');
    c.className = `q-chip${selected.has(item.key) ? ' on' : ''}`;
    c.dataset.key = item.key;
    c.innerHTML = `<span class="dot" style="background:#c9a84c"></span>${esc(languageLabel(item.language))}`;
    c.onclick = () => {
      const lang = item.language || '';
      if (selected.has(item.key)) {
        selected.delete(item.key);
      } else {
        const existing = lang ? selectedByLanguage(lang) : null;
        if (existing) selected.delete(existing.key);
        selected.add(item.key);
      }
      buildChips();
      if (curSurah) loadContent();
    };
    bar.insertBefore(c, rng);
  });
}

async function loadCatalog() {
  const d = await getCachedJson({ key: 'translations-catalog', url: '/api/translations/catalog', ttlMs: 1000 * 60 * 60 * 12 });
  catalog = (d.items || []).filter(x => x.mode === 'ayah-text' && x.has_audio);

  const en = catalog.find(x => (x.language || '') === 'en');
  if (en) selected.add(en.key);

  buildChips();
}

function switchTab(tab) {
  activeTab = tab === 'compare' ? 'compare' : 'mushaf';
  const b1 = document.getElementById('tab-tr-mushaf');
  const b2 = document.getElementById('tab-tr-compare');
  if (b1) b1.classList.toggle('active', activeTab === 'mushaf');
  if (b2) b2.classList.toggle('active', activeTab === 'compare');
  if (curSurah) loadContent();
}

async function pickSurah(num) {
  curSurah = allSurahs.find(s => s.number === num);
  if (!curSurah) return;

  const max = curSurah.numberOfAyahs;
  document.getElementById('r-start').max = max;
  document.getElementById('r-end').max = max;
  document.getElementById('r-start').value = 1;
  document.getElementById('r-end').value = Math.min(max, 7);

  document.getElementById('tb-name').textContent = curSurah.name;
  document.getElementById('tb-meta').textContent = `${curSurah.englishName} · ${max} آية`;
  renderList(filterArr(document.getElementById('sb-q').value));

  await loadContent();
}

function entryLabel(e) {
  return languageLabel(e.language);
}

function normalizeRange(maxAyah) {
  const start = Math.max(1, Number(document.getElementById('r-start').value || 1));
  const endInput = Number(document.getElementById('r-end').value || start);
  const end = Math.min(maxAyah, Math.max(start, endInput));
  return { start, end };
}

function buildEntryCard(entry, ayah) {
  if (entry.fetch_status === 'error') {
    return `<div class="q-card"><div class="qc-label"><span class="qc-name">${esc(entryLabel(entry))}</span></div><div class="qc-text">تعذر الجلب: ${esc(entry.error || '')}</div></div>`;
  }
  const txt = entry.ayahs?.[ayah - 1]?.text || '(النص غير متاح)';
  const dir = (entry.direction || 'ltr').toLowerCase() === 'rtl' ? 'rtl' : 'ltr';
  const audioUrl = entry.ayah_audio_map ? entry.ayah_audio_map[ayah] : null;
  const pid = `m_${(entry.key || entry.language || 'x').replace(/[^a-zA-Z0-9_]/g, '_')}_${ayah}`;
  return `<div class="q-card">
    <div class="qc-label"><span class="qc-name">${esc(entryLabel(entry))}</span></div>
    <div class="qc-text" dir="${dir}">${esc(txt)}</div>
    <div style="margin-top:8px">${playerHTML(pid, audioUrl ? esc(audioUrl) : null)}</div>
  </div>`;
}

function renderMushafTranslations(data, start, end) {
  let html = '';
  for (let ayah = start; ayah <= end; ayah++) {
    const cards = Object.values(data).map(entry => buildEntryCard(entry, ayah)).join('');
    html += `<section class="ayah-block">
      <div class="ayah-master">﴿ ${ayah} ﴾</div>
      <div class="cards-row">${cards}</div>
    </section>`;
  }
  return html;
}

function renderCompareTranslations(data, start, end) {
  const entries = Object.values(data);
  const cols = Math.min(entries.length || 1, 3);
  let html = `<div class="compare-grid" style="grid-template-columns:repeat(${cols},1fr)">`;

  entries.forEach(entry => {
    html += `<div class="cmp-col">
      <div class="cmp-head">
        <div class="cmp-head-name">
          <span class="qc-dot" style="background:#c9a84c"></span>
          ${esc(entryLabel(entry))}
        </div>
      </div>
      <div class="cmp-body">`;

    for (let ayah = start; ayah <= end; ayah++) {
      const txt = entry.ayahs?.[ayah - 1]?.text || '(النص غير متاح)';
      const dir = (entry.direction || 'ltr').toLowerCase() === 'rtl' ? 'rtl' : 'ltr';
      const audioUrl = entry.ayah_audio_map ? entry.ayah_audio_map[ayah] : null;
      const pid = `c_${(entry.key || entry.language || 'x').replace(/[^a-zA-Z0-9_]/g, '_')}_${ayah}`;
      html += `<div class="cmp-ayah">
        <div class="cmp-num">${ayah}</div>
        <div style="flex:1">
          <div class="cmp-text" dir="${dir}">${esc(txt)}</div>
          <div style="margin-top:8px">${playerHTML(pid, audioUrl ? esc(audioUrl) : null)}</div>
        </div>
      </div>`;
    }

    html += '</div></div>';
  });

  html += '</div>';
  return html;
}

function renderPayload(payload) {
  const content = document.getElementById('content');
  const maxAyah = Number(payload?.meta?.max_ayah || 0);
  const data = payload?.data || {};
  if (!maxAyah) {
    content.innerHTML = '<div class="empty-state"><div class="empty-title">لا توجد بيانات ترجمة متاحة لهذه السورة</div></div>';
    return;
  }

  const { start, end } = normalizeRange(maxAyah);
  const html = activeTab === 'compare'
    ? renderCompareTranslations(data, start, end)
    : renderMushafTranslations(data, start, end);

  stopAll();
  audios = {};
  content.innerHTML = html;
  bindPlayers();
}

async function loadContent() {
  if (!curSurah) {
    toast('اختر سورة أولاً');
    return;
  }
  if (!selected.size) {
    toast('اختر ترجمة واحدة على الأقل');
    return;
  }
  const keys = Array.from(selected);
  try {
    const payload = await getCachedJson({
      key: `translations:${curSurah.number}:${keys.sort().join(',')}`,
      url: `/api/translations/surah/${curSurah.number}?keys=${encodeURIComponent(keys.join(','))}`,
      ttlMs: 1000 * 60 * 60 * 6
    });
    renderPayload(payload);
  } catch (err) {
    document.getElementById('content').innerHTML = `<div class="empty-state"><div class="empty-title">تعذر تحميل الترجمات</div><div class="empty-sub">${esc(err.message || err)}</div></div>`;
  }
}

window.toggleTheme = toggleTheme;
window.toggleSB = toggleSB;
window.toggleQiraatBar = toggleQiraatBar;
window.filterSurahs = filterSurahs;
window.pickSurah = pickSurah;
window.loadContent = loadContent;
window.switchTab = switchTab;

(async function boot() {
  initTheme();
  await Promise.all([loadCatalog(), loadSurahs()]);
})();
