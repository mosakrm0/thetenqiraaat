// script.js

// ── constants ──────────────────────────────────────────────────────────────────
// Cumulative ayah offsets per surah (index 0 = surah 1).
// Used to build absolute ayah numbers for cdn.islamic.network URLs.
const SA = [0,7,293,493,669,789,954,1160,1235,1364,1473,1596,1707,1750,1802,1901,
  2029,2140,2250,2348,2483,2595,2673,2791,2855,2932,3159,3252,3340,3409,3469,3503,
  3533,3606,3660,3705,3788,3970,4058,4133,4218,4272,4325,4414,4473,4510,4545,4583,
  4612,4630,4675,4735,4784,4846,4901,4979,5075,5104,5126,5150,5163,5177,5188,5199,
  5217,5229,5241,5271,5323,5375,5419,5447,5475,5495,5551,5591,5622,5672,5712,5758,
  5800,5829,5848,5884,5909,5952,6020,6090,6145,6185,6253,6302,6369,6422,6438,6461,
  6480,6498,6516,6542,6592,6608,6621,6638,6656,6671,6708,6714,6733,6749,6763,6774,
  6785,6802,6811,6829];

const MP3QURAN_BASE    = 'https://mp3quran.net/api/v3';
const CACHE_PREFIX     = 'qiraat-cache-v3:';
const THEME_KEY        = 'qiraat-theme';
const SURAH_LIST_TTL   = 1000 * 60 * 60 * 12;
const EDITION_TTL      = 1000 * 60 * 60 * 6;   // 6 h (was 7 days — too stale)
const MP3QURAN_TTL     = 1000 * 60 * 60 * 24;
const AUDIO_MAP_TTL    = 1000 * 60 * 60 * 6;
const DEFAULT_TIMING_DIR = 'Alafasy_128kbps';

// ── runtime state ──────────────────────────────────────────────────────────────
const memCache        = new Map();
const audioMapCache   = new Map();  // '{key}:{surah}' → ayah_map
let QIRAAT            = [];         // loaded from /api/qiraat on boot
let allSurahs         = [];
let curSurah          = null;
let activeTab         = 'mushaf';
let selected          = new Set(['hafs', 'warsh']);
let audios            = {};
let resolvedAudioSources = {};
let loadTicket        = 0;

const MUQATTAAT_SURAHS = new Set([
  1,2,3,7,10,11,12,13,14,15,19,20,26,27,28,29,30,31,32,36,38,
  40,41,42,43,44,45,46,50,68,
]);

// Per-qiraa display config (color, reciter label, audio source hints).
// Keyed by qiraa key; merged with server QIRAAT data at boot.
//
// Audio source priority (handled in resolveAudioSources):
//   1. everyAyah   → everyayah.com per-file per-ayah (للروايات المتوفرة)
//   2. qfPublicId  → QF public CDN, per-ayah
//   3. audioId     → cdn.islamic.network per-ayah
//   4. rewayaId    → mp3quran.net surah-level fallback
const QIRAAT_UI = {
  hafs:    { name: 'عاصم - حفص',           color: '#4cc9a0', reciter: 'رواية حفص',
             everyAyah: 'Alafasy_128kbps', audioId: 'ar.alafasy', timingDir: 'Alafasy_128kbps' },

  warsh:   { name: 'نافع - ورش',           color: '#d66a2e', reciter: 'رواية ورش',
             everyAyah: 'warsh/warsh_Abdul_Basit_128kbps' },

  // شعبة — mp3quran fallback
  shouba:  { name: 'عاصم - شعبة',          color: '#f0a23a', reciter: 'رواية شعبة',
             },

  // قالون — mp3quran fallback
  qaloon:  { name: 'نافع - قالون',         color: '#c9a84c', reciter: 'رواية قالون',
             rewayaId: 5 },

  // البزي — mp3quran fallback
  bazzi:   { name: 'ابن كثير - البزي',     color: '#4c9ac9', reciter: 'رواية البزي',
             rewayaId: 4 },

  // قنبل — mp3quran fallback
  qumbul:  { name: 'ابن كثير - قنبل',      color: '#5f7ad9', reciter: 'رواية قنبل',
             },

  // الدوري — mp3quran fallback
  douri:   { name: 'أبو عمرو - الدوري',    color: '#7aad4c', reciter: 'رواية الدوري',
             rewayaId: 13 },

  // السوسي — نثبت على مصدر rewaya لتفادي أي عدم تطابق في الرواية
  susi:    { name: 'أبو عمرو - السوسي',    color: '#5bc0a3', reciter: 'رواية السوسي',
             rewayaId: 7 },

  // هشام — mp3quran fallback
  hisham:  { name: 'ابن عامر - هشام',      color: '#9c4cc9', reciter: 'رواية هشام',
             rewayaId: 14 },

  // خلاد — mp3quran fallback
  khallad: { name: 'حمزة - خلاد',          color: '#c94c4c', reciter: 'رواية خلاد',
             rewayaId: 11 },

  // أبو الحارث — mp3quran fallback
  harith:  { name: 'الكسائي - أبو الحارث', color: '#cc7f2a', reciter: 'رواية أبي الحارث',
             rewayaId: 10 },

  // ابن وردان — mp3quran fallback
  wardan:  { name: 'أبو جعفر - ابن وردان', color: '#2aa2b0', reciter: 'رواية ابن وردان',
             rewayaId: 12 },

  // رويس — mp3quran fallback
  ruways:  { name: 'يعقوب - رويس',         color: '#8cbf26', reciter: 'رواية رويس',
             rewayaId: 15 },

  // إسحاق — mp3quran fallback
  ishaq:   { name: 'خلف العاشر - إسحاق',   color: '#d16b8a', reciter: 'رواية إسحاق',
             rewayaId: 16 },
};

// ── cache helpers ──────────────────────────────────────────────────────────────
function cacheKey(key) { return `${CACHE_PREFIX}${key}`; }

function readCache(key) {
  const now = Date.now();
  const mem = memCache.get(key);
  if (mem) return { value: mem.value, fresh: mem.exp > now };
  try {
    const raw = localStorage.getItem(cacheKey(key));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    memCache.set(key, parsed);
    return { value: parsed.value, fresh: parsed.exp > now };
  } catch { return null; }
}

function writeCache(key, value, ttlMs) {
  const entry = { exp: Date.now() + ttlMs, value };
  memCache.set(key, entry);
  try { localStorage.setItem(cacheKey(key), JSON.stringify(entry)); } catch { /* quota */ }
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

// ── boot ───────────────────────────────────────────────────────────────────────
(async () => {
  initTheme();
  await loadQiraat();
  buildChips();
  await loadSurahs();
  syncQiraatBarToggle();
})();

async function loadQiraat() {
  try {
    const list = await getCachedJson({
      key: 'qiraat-list', url: '/api/qiraat', ttlMs: 1000 * 60 * 60 * 24,
    });
    // Merge server QIRAAT with local UI config
    QIRAAT = list.map(q => ({ ...q, ...(QIRAAT_UI[q.key] || {}) }));
  } catch {
    // Fallback: build from local UI config if server unreachable
    QIRAAT = Object.entries(QIRAAT_UI).map(([key, ui]) => ({ key, fallback: false, ...ui }));
    toast('تعذّر تحميل القراءات من الخادم');
  }
}

// ── theme ──────────────────────────────────────────────────────────────────────
function initTheme() {
  applyTheme(localStorage.getItem(THEME_KEY) || 'light');
}
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  const btn = document.getElementById('theme-toggle');
  if (btn) {
    btn.textContent = theme === 'light' ? '🌙' : '☀️';
    btn.title = theme === 'light' ? 'التحويل للوضع الداكن' : 'التحويل للوضع الفاتح';
    btn.setAttribute('aria-label', btn.title);
  }
}
function toggleTheme() {
  const next = (document.documentElement.getAttribute('data-theme') || 'light') === 'dark' ? 'light' : 'dark';
  localStorage.setItem(THEME_KEY, next);
  applyTheme(next);
}

// ── chips ──────────────────────────────────────────────────────────────────────
function buildChips() {
  const bar = document.getElementById('qiraat-bar');
  const rng = bar.querySelector('.range-wrap');
  QIRAAT.forEach(q => {
    const c = document.createElement('div');
    c.className = `q-chip${selected.has(q.key) ? ' on' : ''}`;
    c.dataset.key = q.key;
    c.innerHTML = `<span class="dot" style="background:${q.color || '#888'}"></span>${q.name || q.key}`;
    c.onclick = () => {
      selected[selected.has(q.key) ? 'delete' : 'add'](q.key);
      c.classList.toggle('on', selected.has(q.key));
    };
    bar.insertBefore(c, rng);
  });
}

// ── surah list ─────────────────────────────────────────────────────────────────
async function loadSurahs() {
  try {
    const d = await getCachedJson({ key: 'surah-list', url: '/api/surahs', ttlMs: SURAH_LIST_TTL, retries: 3 });
    allSurahs = d.data;
    renderList(allSurahs);
  } catch { toast('تعذّر تحميل السور'); }
}
function renderList(list) {
  const el = document.getElementById('surah-list');
  el.innerHTML = list.length
    ? list.map(s => `<div class="s-item${curSurah?.number===s.number?' active':''}" onclick="pickSurah(${s.number})">
        <div class="s-num">${s.number}</div>
        <div class="s-name">${s.name}</div>
        <div class="s-count">${s.numberOfAyahs} آية</div>
      </div>`).join('')
    : '<div style="text-align:center;padding:20px;color:var(--txt2)">لا نتائج</div>';
}
function filterSurahs(q) { renderList(q ? allSurahs.filter(s => s.name.includes(q) || s.englishName.toLowerCase().includes(q.toLowerCase()) || String(s.number).startsWith(q)) : allSurahs); }

async function pickSurah(num) {
  curSurah = allSurahs.find(s => s.number === num);
  if (!curSurah) return;
  stopAll();
  const max = curSurah.numberOfAyahs;
  document.getElementById('r-start').max = max;
  document.getElementById('r-end').max   = max;
  document.getElementById('r-start').value = 1;
  document.getElementById('r-end').value   = Math.min(max, 7);
  document.getElementById('tb-name').textContent = curSurah.name;
  const revelationLabel = curSurah.revelationType === 'Meccan'
    ? 'مكية'
    : (curSurah.revelationType === 'Medinan' ? 'مدنية' : '—');
  document.getElementById('tb-meta').textContent =
    `${curSurah.englishName} · ${revelationLabel} · ${max} آية`;
  renderList(filterArr(document.getElementById('sb-q').value));
  await loadContent();
}

function filterArr(q) {
  if (!q) return allSurahs;
  const qq = q.toLowerCase();
  return allSurahs.filter(s => s.name.includes(q) || s.englishName.toLowerCase().includes(qq) || String(s.number).startsWith(q));
}

function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  if (curSurah) loadContent();
}
function toggleSB() { document.getElementById('sidebar').classList.toggle('collapsed'); }

function syncQiraatBarToggle() {
  const bar = document.getElementById('qiraat-bar');
  const btn = document.getElementById('qbar-toggle');
  if (!bar || !btn) return;

  const collapsed = bar.classList.contains('is-collapsed');
  btn.textContent = collapsed ? 'إظهار الأدوات' : 'إخفاء الأدوات';
  btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
}

function toggleQiraatBar() {
  const bar = document.getElementById('qiraat-bar');
  if (!bar) return;
  bar.classList.toggle('is-collapsed');
  syncQiraatBarToggle();
}

// ── audio source resolution ────────────────────────────────────────────────────
function padN(n) { return String(n).padStart(3, '0'); }
function globalN(surah, ayah) { return SA[surah - 1] + ayah; }

function mapAyahForAudio(q, surahNumber, ayahNumber) {
  return ayahNumber;
}

function normalizeServerUrl(server) {
  if (!server) return null;
  const s = server.endsWith('/') ? server : `${server}/`;
  return s.replace(/^http:\/\//i, 'https://');
}

function parseSurahList(listValue) {
  if (!listValue) return new Set();
  return new Set(listValue.split(',').map(n => Number(n.trim())).filter(n => Number.isFinite(n) && n > 0));
}

function pickMoshafForSurah(moshafList, surahNumber) {
  if (!Array.isArray(moshafList)) return null;
  const enriched = moshafList
    .filter(m => m?.server)
    .map(m => ({ ...m, surahSet: parseSurahList(m.surah_list), surahTotalN: Number(m.surah_total) || 0 }));
  const full = enriched.filter(m => m.surahTotalN >= 114).sort((a, b) => b.surahTotalN - a.surahTotalN);
  if (full.length) return full[0];
  const partial = enriched.filter(m => m.surahSet.has(surahNumber)).sort((a, b) => b.surahTotalN - a.surahTotalN);
  return partial[0] || null;
}

async function getMp3QuranRecitersByRewaya(rewayaId) {
  const d = await getCachedJson({
    key: `mp3quran:rewaya:${rewayaId}`,
    url: `${MP3QURAN_BASE}/reciters?language=ar&rewaya=${rewayaId}`,
    ttlMs: MP3QURAN_TTL, retries: 2,
  });
  return d.reciters || [];
}

/**
 * Fetch the full surah ayah→URL map from the backend's /api/audio/surah-map endpoint.
 * Returns null if unavailable.
 */
async function fetchBackendAudioMap(qKey, surahNumber) {
  const cKey = `audiomap:${qKey}:${surahNumber}`;
  const cached = audioMapCache.get(cKey);
  if (cached && cached.exp > Date.now()) return cached.map;

  try {
    const data = await fetchJsonWithRetry(
      `/api/audio/surah-map?qiraa=${encodeURIComponent(qKey)}&surah=${surahNumber}`,
      { retries: 1, timeoutMs: 12000 },
    );
    if (data?.available && data.ayah_map) {
      audioMapCache.set(cKey, { exp: Date.now() + AUDIO_MAP_TTL, map: data.ayah_map });
      return data.ayah_map;
    }
  } catch { /* unavailable */ }
  audioMapCache.set(cKey, { exp: Date.now() + AUDIO_MAP_TTL, map: null });
  return null;
}

async function resolveAudioSources(chosen, surahNumber) {
  async function resolveMp3Source(q) {
    if (!q.rewayaId) return null;
    try {
      const reciters = await getMp3QuranRecitersByRewaya(q.rewayaId);
      const picked = reciters
        .map(r => ({ r, m: pickMoshafForSurah(r.moshaf, surahNumber) }))
        .filter(x => x.m?.server)
        .map(x => {
          const hasSurah = x.m.surahSet?.has(surahNumber) ? 1 : 0;
          const full     = (Number(x.m.surah_total) || 0) >= 114 ? 1 : 0;
          return { ...x, score: hasSurah * 100000 + full * 50000 + (Number(x.m.surah_total) || 0) };
        })
        .sort((a, b) => b.score - a.score)[0];

      if (!picked?.m?.server) return null;

      const base       = normalizeServerUrl(picked.m.server);
      const chapterUrl = `${base}${padN(surahNumber)}.mp3`;

      return {
        mode: 'surah',
        reciter: q.reciter,
        url: chapterUrl,
      };
    } catch {
      return null;
    }
  }

  const pairs = await Promise.all(chosen.map(async q => {
    // ── priority 1: EveryAyah per-file (for supported qiraat) ───────────────
    if (q.everyAyah) {
      return [q.key, {
        mode: 'ayah',
        reciter: q.reciter,
        urlForAyah: n => `https://everyayah.com/data/${q.everyAyah}/${padN(surahNumber)}${padN(n)}.mp3`,
      }];
    }

    // ── priority 2: backend surah map (QF public CDN, full ayah list at once) ──
    const ayahMap = await fetchBackendAudioMap(q.key, surahNumber);
    if (ayahMap) {
      return [q.key, {
        mode: 'ayah',
        reciter: q.reciter || q.name,
        urlForAyah: n => ayahMap[n] || null,
      }];
    }

    // ── priority 3: alquran.cloud CDN (Hafs only, direct per-ayah) ────────────
    if (q.audioId) {
      return [q.key, {
        mode: 'ayah',
        reciter: q.reciter,
        urlForAyah: n => `https://cdn.islamic.network/quran/audio/128/${q.audioId}/${globalN(surahNumber, n)}.mp3`,
      }];
    }

    // ── priority 3 (Warsh only): mp3quran first, then EveryAyah fallback ───
    if (q.preferMp3First) {
      const mp3 = await resolveMp3Source(q);
      if (mp3) return [q.key, mp3];
    }

    // ── priority 4: mp3quran.net (surah-level) ───────────────────────────────
    // ملاحظة: timing segmentation غير موثوق هنا لأن timestamps الافاسي
    // لا تنطبق على ملفات mp3quran لقراءات أخرى.
    const mp3 = await resolveMp3Source(q);
    if (mp3) return [q.key, mp3];

    return [q.key, { mode: 'none', reciter: q.reciter }];
  }));
  return Object.fromEntries(pairs);
}

function buildDefaultAudioSources(chosen) {
  return Object.fromEntries(chosen.map(q => [q.key, { mode: 'none', reciter: `${q.reciter || q.name} · جارٍ تجهيز الصوت` }]));
}

// ── rendering helpers (shared between mushaf + compare) ───────────────────────
function textStatusBadge(status, error) {
  if (status === 'error') {
    const tip = error ? ` title="${error.replace(/"/g, '&quot;')}"` : '';
    return `<span class="fallback-badge" style="background:#8a2f2f"${tip}>تعذّر جلب النص</span>`;
  }
  if (status === 'unavailable') return '<span class="fallback-badge" style="background:#646464">النص غير متاح</span>';
  return '';
}

function buildAudioMarkup(audio, pid, qKey, ayahNum) {
  if (!audio) return '<div class="audio-player disabled" style="font-size:.72rem">لا يتوفر صوت</div>';
  const { mode } = audio;
  if (mode === 'ayah') {
    const url = typeof audio.urlForAyah === 'function' ? audio.urlForAyah(ayahNum) : null;
    if (!url) console.warn(`[audio] null URL — qKey=${qKey} ayah=${ayahNum} mode=ayah`);
    return playerHTML(pid, url);
  }
  if (mode === 'ayah-async' || mode === 'timed-surah') return playerHTMLAsync(pid, qKey, ayahNum);
  if (mode === 'surah') return '<div class="audio-player disabled" style="font-size:.75rem">الصوت متاح كاملًا أعلى الصفحة ☝️</div>';
  return '<div class="audio-player disabled" style="font-size:.75rem">لا يتوفر صوت لهذه القراءة حالياً</div>';
}

function buildQiraatLabel(q, audio, isFallback, stateBadge) {
  return `<div class="qc-label">
    <span class="qc-dot" style="background:${q.color || '#888'}"></span>
    <span class="qc-name">${q.name || q.key}</span>
    <span class="qc-reciter">${audio?.reciter || ''}</span>
    ${isFallback ? '<span class="fallback-badge">نص حفص</span>' : ''}
    ${stateBadge}
  </div>`;
}

// ── load content ───────────────────────────────────────────────────────────────
async function loadContent() {
  if (!curSurah) { toast('اختر سورة أولاً'); return; }
  if (!selected.size) { toast('اختر قراءة واحدة على الأقل'); return; }

  const start = +document.getElementById('r-start').value || 1;
  const end   = +document.getElementById('r-end').value   || 7;
  const max   = curSurah.numberOfAyahs;
  if (start < 1 || end > max || start > end) { toast(`المدى يجب بين 1 و${max}`); return; }

  stopAll();
  setContent('<div class="loader"><div class="loader-ring"></div><div class="loader-txt">جاري تحميل القراءات...</div></div>');

  const ticket  = ++loadTicket;
  const chosen  = QIRAAT.filter(q => selected.has(q.key));
  const textData = {}, fallbackFlags = {}, fetchMeta = {};
  resolvedAudioSources = {};
  const t0 = performance.now();

  try {
    const d = await getCachedJson({
      key: `backend:surah:${curSurah.number}`,
      url: `/api/surah/${curSurah.number}`,
      ttlMs: EDITION_TTL, retries: 2,
    });
    if (d?.data) {
      for (const q of chosen) {
        const entry = d.data[q.key];
        if (entry) {
          textData[q.key]     = entry.ayahs || null;
          fallbackFlags[q.key] = entry.fallback || false;
          fetchMeta[q.key]    = { status: entry.fetch_status || 'cached', error: entry.error || null };
        }
      }
    }
  } catch (err) {
    console.error(err);
    toast('تعذّر تحميل النص من الخادم');
  }

  if (ticket !== loadTicket) return;
  renderCurrentView(chosen, textData, start, end, buildDefaultAudioSources(chosen), fallbackFlags, fetchMeta);
  console.info('Rendered text in', Math.round(performance.now() - t0), 'ms');

  resolveAudioSources(chosen, curSurah.number)
    .then(sources => {
      if (ticket !== loadTicket) return;
      resolvedAudioSources = sources;
      renderCurrentView(chosen, textData, start, end, sources, fallbackFlags, fetchMeta);
      console.info('Hydrated audio in', Math.round(performance.now() - t0), 'ms');
    })
    .catch(err => {
      if (ticket !== loadTicket) return;
      console.warn('Audio hydration failed:', err);
      toast('تعذّر تجهيز بعض مصادر الصوت');
    });
}

function renderCurrentView(chosen, textData, start, end, audioSources, fallbackFlags, fetchMeta) {
  if (activeTab === 'mushaf') renderMushaf(chosen, textData, start, end, audioSources, fallbackFlags, fetchMeta);
  else                        renderCompare(chosen, textData, start, end, audioSources, fallbackFlags, fetchMeta);
}

// ── mushaf view ────────────────────────────────────────────────────────────────
function renderMushaf(chosen, textData, start, end, audioSources, fallbackFlags, fetchMeta = {}) {
  const showB = curSurah.number !== 9;
  const isF   = curSurah.number === 1;

  let h = `<div class="mushaf-page">
    <div class="mushaf-hdr">
      <span class="orn r">❧</span><span class="orn l">❧</span>
      ${showB && !isF ? '<span class="basmala">بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ</span>' : ''}
      <div class="mushaf-sname">${curSurah.name}</div>
      <div class="mushaf-smeta">${curSurah.englishName} · ${(curSurah.revelationType === 'Meccan' ? 'مكية' : (curSurah.revelationType === 'Medinan' ? 'مدنية' : '—'))} · ${curSurah.numberOfAyahs} آية</div>`;

  const surahModeQiraat = chosen.filter(q => audioSources[q.key]?.mode === 'surah');
  if (surahModeQiraat.length) {
    h += `<div class="sura-audio-list">`;
    surahModeQiraat.forEach(q => {
      const audio = audioSources[q.key];
      h += `<div class="sura-audio-item">
        <span class="sa-label" style="color:${q.color}">${q.name} (${audio.reciter}):</span>
        ${playerHTML(`sura_${q.key}_${curSurah.number}`, audio.url)}
      </div>`;
    });
    h += `</div>`;
  }
  h += `</div><div class="mushaf-body">`;

  for (let i = start; i <= end; i++) {
    const idx   = i - 1;
    const delay = (i - start) * 55;

    h += `<div class="ayah-block" style="animation-delay:${delay}ms">
      <div class="ayah-master"><span class="ayah-badge">${i}</span></div>
      <div class="cards-row">`;

    chosen.forEach(q => {
      const txt   = textData[q.key]?.[idx]?.text || '(النص غير متاح لهذه القراءة)';
      const audio = audioSources[q.key] || { mode: 'none', reciter: q.reciter };
      const pid   = `m_${q.key}_${curSurah.number}_${i}`;
      const isFallback = fallbackFlags[q.key] || q.fallback;
      const textState  = fetchMeta[q.key] || { status: 'cached', error: null };
      const qFont = q.key === 'hafs' ? "'Amiri Quran','Amiri',serif" : "'Amiri',serif";

      h += `<div class="q-card${isFallback ? ' is-fallback' : ''}">
        ${buildQiraatLabel(q, audio, isFallback, textStatusBadge(textState.status, textState.error))}
        <div class="qc-text" style="font-family:${qFont}">${txt}</div>
        ${buildAudioMarkup(audio, pid, q.key, i)}
      </div>`;
    });

    h += '</div></div>';
  }
  h += '</div></div>';
  setContent(h);
  bindPlayers();
}

// ── compare view ───────────────────────────────────────────────────────────────
function renderCompare(chosen, textData, start, end, audioSources, fallbackFlags, fetchMeta = {}) {
  const cols = Math.min(chosen.length, 3);
  let h = `<div class="compare-grid" style="grid-template-columns:repeat(${cols},1fr)">`;

  chosen.forEach(q => {
    const audio      = audioSources[q.key] || { mode: 'none', reciter: q.reciter };
    const isFallback = fallbackFlags[q.key] || q.fallback;
    const textState  = fetchMeta[q.key] || { status: 'cached', error: null };
    const stateBadge = textStatusBadge(textState.status, textState.error);
    const headAudio  = audio.mode === 'surah' ? playerHTML(`cmp_sura_${q.key}_${curSurah.number}`, audio.url) : '';

    h += `<div class="cmp-col${isFallback ? ' is-fallback' : ''}">
      <div class="cmp-head">
        <div class="cmp-head-name">
          <span class="qc-dot" style="background:${q.color}"></span>
          ${q.name}${isFallback ? ' <span class="fallback-badge">نص حفص</span>' : ''}${stateBadge ? ` ${stateBadge}` : ''}
        </div>
        <div class="cmp-head-sub">${audio.reciter}</div>
        ${headAudio ? `<div style="margin-top:8px">${headAudio}</div>` : ''}
      </div>
      <div class="cmp-body">`;

    for (let i = start; i <= end; i++) {
      const idx  = i - 1;
      const txt  = textData[q.key]?.[idx]?.text || '(النص غير متاح لهذه القراءة)';
      const pid  = `c_${q.key}_${curSurah.number}_${i}`;
      const qFont = q.key === 'hafs' ? "'Amiri Quran','Amiri',serif" : "'Amiri',serif";
      h += `<div class="cmp-ayah">
        <div class="cmp-num">${i}</div>
        <div style="flex:1">
          <div class="cmp-text" style="font-family:${qFont}">${txt}</div>
          ${buildAudioMarkup(audio, pid, q.key, i)}
        </div>
      </div>`;
    }
    h += '</div></div>';
  });

  h += '</div>';
  setContent(h);
  bindPlayers();
}

// ── player HTML ────────────────────────────────────────────────────────────────
function playerHTML(pid, url) {
  if (!url) return '<div class="audio-player disabled">لا يتوفر صوت مطابق لهذه القراءة عبر المصدر الحالي</div>';
  return `<div class="audio-player" data-pid="${pid}" data-url="${url}">
    <button class="play-btn" id="pbtn-${pid}">▶</button>
    <div class="prog-track" id="ptrk-${pid}">
      <div class="prog-rail"><div class="prog-bar" id="pbar-${pid}"></div></div>
    </div>
    <span class="time-lbl" id="ptim-${pid}">0:00</span>
  </div>`;
}

function playerHTMLAsync(pid, qKey, ayah) {
  return `<div class="audio-player" data-pid="${pid}" data-url-fn="true" data-qkey="${qKey}" data-ayah="${ayah}">
    <button class="play-btn" id="pbtn-${pid}">▶</button>
    <div class="prog-track" id="ptrk-${pid}">
      <div class="prog-rail"><div class="prog-bar" id="pbar-${pid}"></div></div>
    </div>
    <span class="time-lbl" id="ptim-${pid}">0:00</span>
  </div>`;
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

function disablePlayer(pid, msg = 'لا يتوفر صوت مطابق لهذه القراءة عبر المصدر الحالي') {
  const holder = document.querySelector(`.audio-player[data-pid="${pid}"]`);
  if (!holder) return;
  holder.outerHTML = `<div class="audio-player disabled">${msg}</div>`;
}

// ── player binding + playback ──────────────────────────────────────────────────
function bindPlayers() {
  document.querySelectorAll('.audio-player[data-pid]').forEach(el => {
    const pid     = el.dataset.pid;
    const rawUrl  = el.dataset.url;
    // dataset بيحوّل null/undefined لـ string — نتأكد إن الـ URL حقيقي
    const url     = (rawUrl && rawUrl !== 'null' && rawUrl !== 'undefined') ? rawUrl : null;
    const isAsync = el.dataset.urlFn === 'true';
    const qKey    = el.dataset.qkey;
    const ayah    = Number(el.dataset.ayah);
    const btn     = document.getElementById(`pbtn-${pid}`);
    const trk     = document.getElementById(`ptrk-${pid}`);

    if (btn) {
      btn.onclick = e => {
        e.stopPropagation();
        if (isAsync) {
          const source = resolvedAudioSources[qKey];
          if ((source?.mode === 'ayah-async' || source?.mode === 'timed-surah') && typeof source.urlForAyah === 'function') {
            togglePlay(pid, null, () => source.mode === 'timed-surah'
              ? resolveTimedAyahPlayback(source, ayah)
              : source.urlForAyah(ayah));
          } else {
            toast('مصدر الصوت غير متاح');
          }
        } else {
          togglePlay(pid, url);
        }
      };
    }
    if (trk) trk.onclick = (e) => seek(pid, e, trk);
  });
}

async function resolveTimedAyahPlayback(source, ayahNumber) {
  const segUrl = await source.urlForAyah(ayahNumber);
  if (segUrl) return segUrl;

  if (typeof fetchTimingsForSurah === 'function' && source?.timingDir && source?.surahUrl && curSurah?.number) {
    const timings   = await fetchTimingsForSurah(source.timingDir, curSurah.number);
    const ayahKey   = `${padN(curSurah.number)}${padN(ayahNumber)}`;
    const ayahTiming = timings?.get(ayahKey);
    if (ayahTiming) return { url: source.surahUrl, startSec: ayahTiming.startMs / 1000, endSec: ayahTiming.endMs / 1000 };
  }
  return source?.surahUrl || null;
}

async function togglePlay(pid, url, urlFn) {
  // Pause all other active players
  Object.entries(audios).forEach(([k, a]) => {
    if (k !== pid && !a.paused) { a.pause(); setState(k, 'idle'); }
  });

  let a = audios[pid];
  if (!a) {
    a = new Audio();
    audios[pid] = a;
    a.addEventListener('timeupdate', () => {
      updateBar(pid, a);
      if (Number.isFinite(a._windowEndSec) && a.currentTime >= a._windowEndSec) {
        a.pause();
        if (Number.isFinite(a._windowStartSec)) a.currentTime = a._windowStartSec;
        setState(pid, 'idle');
      }
    });
    a.addEventListener('ended',  () => { setState(pid, 'idle'); resetBar(pid); });
    a.addEventListener('error',  () => { toast('ملف الصوت غير متاح أو هناك مشكلة في الاتصال'); setState(pid, 'idle'); });
  }

  // Use a._srcSet flag — comparing a.src === '' is unreliable because the browser
  // immediately resolves '' to the current page URL, causing NotSupportedError on play().
  const needsUrl = !a._srcSet;
  let playbackWindow = null;
  let shouldUpdateWindow = false;

  if (needsUrl) {
    let resolvedUrl = url;
    if (!resolvedUrl && typeof urlFn === 'function') {
      setState(pid, 'loading');
      try {
        const resolved = await urlFn();
        if (typeof resolved === 'string') {
          resolvedUrl = resolved;
          shouldUpdateWindow = true;
        } else if (resolved && typeof resolved === 'object') {
          resolvedUrl = resolved.url || null;
          playbackWindow = { startSec: resolved.startSec, endSec: resolved.endSec };
          shouldUpdateWindow = true;
        }
      } catch (err) {
        console.error('Audio URL resolution error:', err);
      }
    }
    if (!resolvedUrl) { toast('تعذّر تحميل الصوت'); setState(pid, 'idle'); return; }
    resolvedUrl = normalizeAudioUrl(resolvedUrl);
    if (!resolvedUrl) {
      toast('تعذّر تحميل الصوت'); setState(pid, 'idle'); return;
    }
    try {
      a.src = resolvedUrl;
    } catch {
      disablePlayer(pid);
      toast('مصدر الصوت غير مدعوم لهذه القراءة');
      setState(pid, 'idle');
      return;
    }
    a._srcSet = true;
  }

  if (shouldUpdateWindow) {
    a._windowStartSec = (playbackWindow && Number.isFinite(playbackWindow.startSec)) ? playbackWindow.startSec : null;
    a._windowEndSec   = (playbackWindow && Number.isFinite(playbackWindow.endSec))   ? playbackWindow.endSec   : null;
  }

  if (a.paused) {
    setState(pid, 'loading');
    if (Number.isFinite(a._windowStartSec)) {
      try { a.currentTime = a._windowStartSec; } catch { /* before metadata load */ }
    }
    a.play().then(() => setState(pid, 'playing')).catch(err => {
      console.error('Audio play error:', err);
      if (err?.name === 'NotSupportedError') {
        disablePlayer(pid);
        try {
          a.removeAttribute('src');
          a.load();
          a._srcSet = false;
        } catch { /* no-op */ }
        toast('هذا المصدر غير مدعوم لهذه الرواية في هذه الآية');
        setState(pid, 'idle');
        return;
      }
      toast('تعذّر تشغيل الصوت');
      setState(pid, 'idle');
    });
  } else {
    a.pause();
    setState(pid, 'idle');
  }
}

function setState(pid, state) {
  const btn = document.getElementById(`pbtn-${pid}`);
  if (!btn) return;
  btn.className = `play-btn${state === 'playing' ? ' is-playing' : state === 'loading' ? ' is-loading' : ''}`;
  btn.textContent = state === 'playing' ? '⏸' : state === 'loading' ? '…' : '▶';
}

function updateBar(pid, a) {
  const bar = document.getElementById(`pbar-${pid}`);
  const tim = document.getElementById(`ptim-${pid}`);
  if (!bar) return;
  bar.style.width = `${a.duration ? (a.currentTime / a.duration) * 100 : 0}%`;
  if (tim) tim.textContent = fmt(a.currentTime);
}

function resetBar(pid) { updateBar(pid, { currentTime: 0, duration: 0 }); }

function seek(pid, e, el) {
  const a = audios[pid];
  if (!a?.duration) return;
  const r = el.getBoundingClientRect();
  a.currentTime = ((e.clientX - r.left) / r.width) * a.duration;
}

function stopAll() {
  Object.values(audios).forEach(a => {
    try {
      a.pause();
      a.removeAttribute('src');
      a.load();       // reset element — clears network request and error state
      a._srcSet = false;
    } catch { /* no-op */ }
  });
  audios = {};
}

function fmt(s) { return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`; }
function setContent(html) { document.getElementById('content').innerHTML = html; }
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}
