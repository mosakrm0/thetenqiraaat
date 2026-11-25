// script.js — Readings comparison page
(function () {
  'use strict';

  const {
  escHtml,
  escAttr,
  initTheme,
  toast,
  fmtTime,
  createCache,
  fetchJsonWithRetry,
  getCachedJson,
  normalizeAudioUrl,
  buildProxyAudioUrl,
} = window.Common;

const SURAH_LIST_TTL = 1000 * 60 * 60 * 24;
const EDITION_TTL    = 1000 * 60 * 60 * 6;
const AUDIO_MAP_TTL  = 1000 * 60 * 60 * 6;

const cache          = createCache('qiraat-cache-v4:');
const audioMapCache  = new Map();
const recitersCache  = new Map();

let QIRAAT               = [];
let IMAMS                = [];
let allSurahs            = [];
let curSurah             = null;
let activeTab            = 'mushaf';
let selected             = new Set(['hafs', 'warsh']);
let selectedReciters     = {};
let audios               = {};
let resolvedAudioSources = {};
let loadTicket           = 0;
let highlightDiffs       = true;
let autoPlayEnabled      = false;
let playbackSpeed        = 1;

// ── boot ───────────────────────────────────────────────────────────────────────
(async () => {
  initTheme();
  const params = new URLSearchParams(window.location.search);
  const qParam = params.get('q');
  if (qParam) {
    const keys = qParam.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
    if (keys.length) selected = new Set(keys);
  }
  const tabParam = params.get('tab');
  if (tabParam === 'compare' || tabParam === 'mushaf') {
    activeTab = tabParam;
    document.querySelectorAll('.tab[data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === activeTab));
  }

  await Promise.all([loadQiraat(), loadSurahs()]);
  buildGroups();
  syncQiraatBarToggle();

  const surahNum = Number(params.get('surah'));
  if (surahNum >= 1 && surahNum <= 114 && allSurahs.length) {
    await pickSurah(surahNum, {
      start: Number(params.get('start')) || null,
      end: Number(params.get('end')) || null,
    });
  }
})();

async function loadQiraat() {
  try {
    const [qList, iList] = await Promise.all([
      getCachedJson(cache, { key: 'qiraat-list-v2', url: '/api/qiraat', ttlMs: 1000 * 60 * 60 * 24 }),
      getCachedJson(cache, { key: 'imams-list-v1', url: '/api/imams', ttlMs: 1000 * 60 * 60 * 24 }).catch(() => []),
    ]);
    QIRAAT = Array.isArray(qList) ? qList : [];
    IMAMS = Array.isArray(iList) ? iList : [];
  } catch {
    toast('تعذّر تحميل قائمة القراءات من الخادم');
  }
}

// ── URL state sync ─────────────────────────────────────────────────────────────
function syncUrlState() {
  try {
    const url = new URL(window.location.href);
    if (curSurah) url.searchParams.set('surah', String(curSurah.number));
    else url.searchParams.delete('surah');

    const startEl = document.getElementById('r-start');
    const endEl = document.getElementById('r-end');
    if (curSurah && startEl && endEl) {
      url.searchParams.set('start', startEl.value);
      url.searchParams.set('end', endEl.value);
    }
    url.searchParams.set('tab', activeTab);
    if (selected.size) url.searchParams.set('q', Array.from(selected).join(','));
    else url.searchParams.delete('q');
    window.history.replaceState({}, '', url.toString());
  } catch {}
}

// ── grouped qiraat chips & presets ─────────────────────────────────────────────
function buildGroups() {
  const container = document.getElementById('q-groups');
  if (!container) return;

  const byImam = new Map();
  QIRAAT.forEach(q => {
    const ik = q.imamKey || 'other';
    if (!byImam.has(ik)) {
      byImam.set(ik, { key: ik, name: q.imamName || ik, items: [] });
    }
    byImam.get(ik).items.push(q);
  });

  const orderedGroups = [];
  if (IMAMS.length) {
    IMAMS.forEach(im => {
      if (byImam.has(im.key)) orderedGroups.push(byImam.get(im.key));
    });
  }
  byImam.forEach((grp, key) => {
    if (!orderedGroups.some(g => g.key === key)) orderedGroups.push(grp);
  });

  container.innerHTML = orderedGroups.map(grp => `
    <div class="q-group">
      <span class="q-group-title">${escHtml(grp.name)}</span>
      <div class="q-group-chips">
        ${grp.items.map(q => {
          const isOn = selected.has(q.key);
          const isFull = q.textTier === 'kfgqpc_full' || q.textTier === 'full';
          return `<button type="button" class="q-chip${isOn ? ' on' : ''}" data-key="${escAttr(q.key)}" title="${escAttr(q.displayName || q.rawiName || q.key)}">
            <span class="dot" style="background:${escAttr(q.color || '#888')}"></span>
            <span>${escHtml(q.rawiName || q.key)}</span>
            ${isFull ? '' : '<span class="chip-mini-tag" title="نص حفص مع بيان الأوجه">أوجه</span>'}
          </button>`;
        }).join('')}
      </div>
    </div>
  `).join('');

  container.querySelectorAll('.q-chip').forEach(btn => {
    btn.addEventListener('click', () => {
      const k = btn.dataset.key;
      if (selected.has(k)) selected.delete(k);
      else selected.add(k);
      btn.classList.toggle('on', selected.has(k));
      syncUrlState();
    });
  });
}

function applyPreset(mode) {
  if (mode === 'clear') {
    selected.clear();
  } else if (mode === 'kfgqpc') {
    selected = new Set(QIRAAT.filter(q => q.textTier === 'kfgqpc_full' || q.textTier === 'full').map(q => q.key));
  } else if (mode === 'ten') {
    const picks = [];
    const preferred = ['qaloon', 'bazzi', 'douri', 'hisham', 'hafs', 'khalaf_hamzah', 'harith', 'wardan', 'ruways', 'ishaq'];
    preferred.forEach(k => {
      const q = QIRAAT.find(x => x.key === k);
      if (q) picks.push(q.key);
    });
    selected = new Set(picks);
  }
  buildGroups();
  syncUrlState();
  if (curSurah && selected.size) loadContent();
}

// ── surah list (SSR hydrated or local /api/surahs) ─────────────────────────────
async function loadSurahs() {
  const el = document.getElementById('surah-list');
  if (Array.isArray(window.__INITIAL_SURAHS__) && window.__INITIAL_SURAHS__.length) {
    allSurahs = window.__INITIAL_SURAHS__;
    renderList(allSurahs);
    return;
  }
  try {
    const d = await getCachedJson(cache, { key: 'surah-list-local-v1', url: '/api/surahs', ttlMs: SURAH_LIST_TTL, retries: 2 });
    allSurahs = d.data || [];
    renderList(allSurahs);
  } catch {
    if (el) {
      el.innerHTML = `<div class="loader">
        <div class="loader-txt">تعذّر تحميل فهرس السور</div>
        <button type="button" class="v-btn" style="margin-top:8px" onclick="loadSurahs()">إعادة المحاولة</button>
      </div>`;
    }
    toast('تعذّر تحميل السور');
  }
}

function renderList(list) {
  const el = document.getElementById('surah-list');
  if (!el) return;
  el.innerHTML = list.length
    ? list.map(s => `<button type="button" class="s-item${curSurah?.number === s.number ? ' active' : ''}" onclick="pickSurah(${s.number})">
        <span class="s-num">${s.number}</span>
        <span class="s-name">${escHtml(s.name)}</span>
        <span class="s-count">${s.numberOfAyahs}</span>
      </button>`).join('')
    : '<div class="loader"><div class="loader-txt">لا نتائج</div></div>';
}

function filterArr(q) {
  if (!q) return allSurahs;
  const qq = q.toLowerCase();
  return allSurahs.filter(s =>
    s.name.includes(q) ||
    (s.englishName || '').toLowerCase().includes(qq) ||
    String(s.number).startsWith(q)
  );
}

function filterSurahs(q) {
  renderList(filterArr(q));
}

async function pickSurah(num, rangeOverride = null) {
  curSurah = allSurahs.find(s => s.number === num);
  if (!curSurah) return;
  stopAll();
  const max = curSurah.numberOfAyahs;
  const startEl = document.getElementById('r-start');
  const endEl = document.getElementById('r-end');
  startEl.max = max;
  endEl.max = max;
  startEl.value = rangeOverride?.start ? Math.max(1, Math.min(max, rangeOverride.start)) : 1;
  endEl.value = rangeOverride?.end ? Math.max(Number(startEl.value), Math.min(max, rangeOverride.end)) : Math.min(max, 7);

  renderList(filterArr(document.getElementById('sb-q').value));
  await loadContent();
}

function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll('.tab[data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  syncUrlState();
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

function toggleDiffHighlight(enabled) {
  highlightDiffs = Boolean(enabled);
  if (curSurah) loadContent();
}

function setAutoPlay(enabled) {
  autoPlayEnabled = Boolean(enabled);
}

function setPlaybackSpeed(val) {
  const num = Number(val);
  playbackSpeed = Number.isFinite(num) && num > 0 ? num : 1;
  Object.values(audios).forEach(a => {
    try { a.playbackRate = playbackSpeed; } catch {}
  });
}

  // ── Arabic word diff highlighting vs Hafs ───────────────────────────────────
  function _normToken(word) {
    return String(word || '')
      .replace(/[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]/g, '')
      .replace(/[\u0640\u00A0]/g, '')
      .replace(/[أإآٱ]/g, 'ا')
      .replace(/[ى]/g, 'ي')
      .replace(/[٠-٩0-9]+/g, '')
      .trim();
  }

  function renderAyahTextWithDiff(text, hafsText, qKey) {
    if (!highlightDiffs || !hafsText || qKey === 'hafs') {
      return escHtml(text);
    }
    const tokens = String(text || '').split(/\s+/).filter(Boolean);
    const hafsTokens = String(hafsText || '').split(/\s+/).filter(Boolean);
    const hafsNormSet = new Set(hafsTokens.map(_normToken).filter(Boolean));
    const hafsExactSet = new Set(hafsTokens);

    return tokens.map(tok => {
      const norm = _normToken(tok);
      // Skip pure verse numbers or pause/ornament symbols
      if (!norm) return escHtml(tok);
      const differs = !hafsExactSet.has(tok) && (!hafsNormSet.has(norm) || hafsTokens.every(ht => _normToken(ht) === norm ? ht !== tok : true));
      if (differs) {
        return `<span class="diff-word">${escHtml(tok)}</span>`;
      }
      return escHtml(tok);
    }).join(' ');
  }

// ── audio source resolution (backend 4-tier) ──────────────────────────────────
async function fetchBackendReciters(qKey, surahNumber) {
  const rKey = `${qKey}:${surahNumber}`;
  const cached = recitersCache.get(rKey);
  if (cached && cached.exp > Date.now()) return cached.items;
  try {
    const d = await fetchJsonWithRetry(
      `/api/audio/reciters?qiraa=${encodeURIComponent(qKey)}&surah=${surahNumber}`,
      { retries: 1, timeoutMs: 10000 },
    );
    const items = d?.reciters || [];
    recitersCache.set(rKey, { exp: Date.now() + AUDIO_MAP_TTL, items });
    return items;
  } catch {
    return [];
  }
}

async function fetchBackendAudioMap(qKey, surahNumber, reciterId = null) {
  const cKey = `audiomap:${qKey}:${surahNumber}:${reciterId || 'auto'}`;
  const cached = audioMapCache.get(cKey);
  if (cached && cached.exp > Date.now()) return cached.data;

  try {
    let url = `/api/audio/surah-map?qiraa=${encodeURIComponent(qKey)}&surah=${surahNumber}`;
    if (reciterId) url += `&reciter=${encodeURIComponent(reciterId)}`;
    const data = await fetchJsonWithRetry(url, { retries: 1, timeoutMs: 14000 });
    if (data?.available) {
      audioMapCache.set(cKey, { exp: Date.now() + AUDIO_MAP_TTL, data });
      return data;
    }
  } catch {}
  audioMapCache.set(cKey, { exp: Date.now() + AUDIO_MAP_TTL, data: null });
  return null;
}

async function resolveAudioSources(chosen, surahNumber) {
  const pairs = await Promise.all(chosen.map(async q => {
    const prefReciter = selectedReciters[q.key] || null;
    const [res, reciters] = await Promise.all([
      fetchBackendAudioMap(q.key, surahNumber, prefReciter),
      fetchBackendReciters(q.key, surahNumber),
    ]);

    if (!res || !res.available) {
      return [q.key, { mode: 'none', reciter: q.displayName || q.rawiName, reciters }];
    }

    if (res.mode === 'ayah' && res.ayah_map) {
      return [q.key, {
        mode:        'ayah',
        source:      res.source,
        reciterId:   res.reciter_id || prefReciter,
        reciter:     res.reciter_name || q.rawiName,
        reciters,
        urlForAyah:  n => res.ayah_map[String(n)] || res.ayah_map[n] || null,
      }];
    }

    if (res.mode === 'timed-surah' && res.surah_url && res.timings) {
      return [q.key, {
        mode:        'timed-surah',
        source:      res.source,
        reciterId:   res.reciter_id || prefReciter,
        reciter:     res.reciter_name || q.rawiName,
        reciters,
        surahUrl:    res.surah_url,
        timings:     res.timings,
      }];
    }

    if (res.mode === 'surah' && res.surah_url) {
      return [q.key, {
        mode:        'surah',
        source:      res.source,
        reciterId:   res.reciter_id || prefReciter,
        reciter:     res.reciter_name || q.rawiName,
        reciters,
        url:         res.surah_url,
      }];
    }

    return [q.key, { mode: 'none', reciter: q.rawiName, reciters }];
  }));
  return Object.fromEntries(pairs);
}

function buildDefaultAudioSources(chosen) {
  return Object.fromEntries(chosen.map(q => [q.key, { mode: 'none', reciter: 'جارٍ تجهيز الصوت...', reciters: [] }]));
}

async function onReciterChange(qKey, newReciterId) {
  if (!curSurah) return;
  selectedReciters[qKey] = newReciterId;
  stopAll();
  const chosen = QIRAAT.filter(q => selected.has(q.key));
  const res = await fetchBackendAudioMap(qKey, curSurah.number, newReciterId);
  const existingReciters = resolvedAudioSources[qKey]?.reciters || [];

  if (res?.available && res.mode === 'ayah' && res.ayah_map) {
    resolvedAudioSources[qKey] = {
      mode: 'ayah', source: res.source, reciterId: res.reciter_id,
      reciter: res.reciter_name, reciters: existingReciters,
      urlForAyah: n => res.ayah_map[String(n)] || res.ayah_map[n] || null,
    };
  } else if (res?.available && res.mode === 'timed-surah' && res.surah_url) {
    resolvedAudioSources[qKey] = {
      mode: 'timed-surah', source: res.source, reciterId: res.reciter_id,
      reciter: res.reciter_name, reciters: existingReciters,
      surahUrl: res.surah_url, timings: res.timings,
    };
  } else if (res?.available && res.mode === 'surah' && res.surah_url) {
    resolvedAudioSources[qKey] = {
      mode: 'surah', source: res.source, reciterId: res.reciter_id,
      reciter: res.reciter_name, reciters: existingReciters,
      url: res.surah_url,
    };
  }

  const start = +document.getElementById('r-start').value || 1;
  const end = +document.getElementById('r-end').value || 7;
  if (window._lastRenderArgs) {
    const { textData, fallbackFlags, fetchMeta, variantsMap, countNotesMap } = window._lastRenderArgs;
    renderCurrentView(chosen, textData, start, end, resolvedAudioSources, fallbackFlags, fetchMeta, variantsMap, countNotesMap);
  }
}

// ── rendering helpers ──────────────────────────────────────────────────────────
function workspaceHeaderMarkup() {
  if (!curSurah) return '';
  const rev = curSurah.revelationType === 'Meccan' ? 'مكية' : 'مدنية';
  return `<div class="workspace-hdr">
    <div class="tb-name">${escHtml(curSurah.name)}</div>
    <div class="tb-meta">${escHtml(curSurah.englishName)} · ${rev} · ${curSurah.numberOfAyahs} آية · ${selected.size} روايات محددة</div>
  </div>`;
}

function textTierBadge(q, textState) {
  if (textState?.status === 'error') {
    const tip = textState.error ? ` title="${escAttr(textState.error)}"` : '';
    return `<span class="fallback-badge" style="background:var(--danger);color:#fff"${tip}>تعذّر جلب النص</span>`;
  }
  if (textState?.status === 'unavailable') {
    return '<span class="fallback-badge" style="background:var(--bevel-mid);color:#fff">النص غير متاح</span>';
  }
  if (q.textTier === 'kfgqpc_full') {
    return '<span class="tier-badge tier-full" title="نص عثماني مخصص من مجمع الملك فهد">مجمع الملك فهد</span>';
  }
  if (q.textTier === 'annotated_hafs' || q.fallback) {
    return '<span class="fallback-badge" title="يعرض نص حفص مع بيان أوجه القراءة المتوفرة">نص حفص + الأوجه</span>';
  }
  return '';
}

function buildAudioMarkup(audio, pid, qKey, audioAyah, extraAyah = null, slotAyah = audioAyah) {
  if (audioAyah === null) {
    return '<div class="audio-player disabled">لا يوجد مقطع صوتي مستقل (تبدأ التلاوة من الآية التالية)</div>';
  }
  if (!audio) return '<div class="audio-player disabled">لا يتوفر صوت</div>';
  if (audio.mode === 'ayah') {
    const url = typeof audio.urlForAyah === 'function' ? audio.urlForAyah(audioAyah) : null;
    const extraUrl = extraAyah && typeof audio.urlForAyah === 'function' ? audio.urlForAyah(extraAyah) : null;
    return playerHTML(pid, url, qKey, slotAyah, extraUrl);
  }
  if (audio.mode === 'timed-surah') {
    const t = audio.timings?.[String(audioAyah)] || audio.timings?.[audioAyah];
    if (!t) {
      return '<div class="audio-player disabled">لا يتوفر توقيت لهذه الآية (استمع للسورة كاملة)</div>';
    }
    let endMs = t.end_ms;
    if (extraAyah) {
      const tExtra = audio.timings?.[String(extraAyah)] || audio.timings?.[extraAyah];
      if (tExtra && Number.isFinite(tExtra.end_ms)) {
        endMs = tExtra.end_ms;
      }
    }
    return playerHTMLTimed(pid, qKey, slotAyah, audio.surahUrl, t.start_ms, endMs);
  }
  if (audio.mode === 'surah') {
    return '<div class="audio-player disabled">الصوت متاح كاملًا أعلى الصفحة</div>';
  }
  return '<div class="audio-player disabled">لا يتوفر صوت لهذه القراءة حالياً</div>';
}

  function buildVariantsMarkup(variantsList) {
    if (!Array.isArray(variantsList) || !variantsList.length) return '';
    return `<div class="q-variants">
      <div class="qv-title">أوجه القراءة في هذه الآية:</div>
      ${variantsList.map(v => {
        const hw = (v.hafs_word || '').trim();
        const vt = (v.variant_text || '').trim();
        const wordHtml = (hw && vt && hw !== vt)
          ? `<span class="qv-hafs">${escHtml(hw)}</span> - <span class="qv-var">${escHtml(vt)}</span>`
          : `<span class="qv-var">${escHtml(vt || hw)}</span>`;
        return `<div class="qv-item">
          ${wordHtml}
          <span class="qv-rule">${v.rule_type === 'usul' ? 'أصول' : 'فرش'}</span>
          ${v.note ? `<div class="qv-note">${escHtml(v.note)}</div>` : ''}
        </div>`;
      }).join('')}
    </div>`;
  }

function buildCountNotesMarkup(notesList) {
  if (!Array.isArray(notesList) || !notesList.length) return '';
  return `<div class="count-notes-wrap">
    ${notesList.map(n => `<span class="count-note-badge" title="${escAttr(n.note || '')}">عدّ الآي: ${escHtml(n.note || n.anchor_word || 'اختلاف عدّ الآي')}</span>`).join('')}
  </div>`;
}

function buildReciterSelectMarkup(q, audio) {
  const list = audio?.reciters || [];
  if (list.length <= 1) return '';
  return `<select class="reciter-select" onchange="onReciterChange('${escAttr(q.key)}', this.value)" aria-label="اختيار القارئ">
    ${list.map(r => `<option value="${escAttr(r.id)}"${r.id === audio.reciterId ? ' selected' : ''}>${escHtml(r.name)}</option>`).join('')}
  </select>`;
}

function buildQiraatLabel(q, audio, textState) {
  const timedBadge = audio?.mode === 'timed-surah'
    ? '<span class="tier-badge tier-timed" title="مقطع آية بآية من ملف السورة عبر توقيت الآيات">موقّت</span>'
    : '';
  return `<div class="qc-label">
    <span class="qc-dot" style="background:${escAttr(q.color || '#888')}"></span>
    <span class="qc-name">${escHtml(q.displayName || q.rawiName || q.key)}</span>
    <span class="qc-reciter">${escHtml(audio?.reciter || '')}</span>
    ${textTierBadge(q, textState)}
    ${timedBadge}
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

  syncUrlState();
  stopAll();
  document.getElementById('content').innerHTML = `${workspaceHeaderMarkup()}
    <div class="v-window" style="max-width:520px;margin:0 auto">
      <div class="v-titlebar"><span>تحميل البيانات</span><span class="mono">WAIT</span></div>
      <div class="loader"><div class="loader-ring"></div><div class="loader-txt">جاري تحميل القراءات...</div></div>
    </div>`;

  const ticket   = ++loadTicket;
  const chosen   = QIRAAT.filter(q => selected.has(q.key));
  const reqKeys  = Array.from(new Set(['hafs', ...chosen.map(q => q.key)]));
  const textData = {}, fallbackFlags = {}, fetchMeta = {}, variantsMap = {}, countNotesMap = {};
  resolvedAudioSources = {};

  try {
    const d = await getCachedJson(cache, {
      key: `backend:surah:${curSurah.number}:${reqKeys.sort().join(',')}`,
      url: `/api/surah/${curSurah.number}?qiraat=${encodeURIComponent(reqKeys.join(','))}`,
      ttlMs: EDITION_TTL, retries: 2,
    });
    if (d?.data) {
      for (const key of reqKeys) {
        const entry = d.data[key];
        if (entry) {
          textData[key]      = entry.ayahs || null;
          fallbackFlags[key] = Boolean(entry.fallback);
          fetchMeta[key]     = { status: entry.fetch_status || 'cached', error: entry.error || null };
          variantsMap[key]   = entry.variants || {};
          countNotesMap[key] = entry.count_notes || {};
        }
      }
    }
  } catch (err) {
    console.error(err);
    if (ticket !== loadTicket) return;
    document.getElementById('content').innerHTML = `${workspaceHeaderMarkup()}
      <div class="empty-state v-window">
        <div class="v-titlebar"><span>خطأ في الاتصال</span><span class="mono">ERR</span></div>
        <div class="v-window-body">
          <div class="empty-title">تعذّر تحميل النص من الخادم</div>
          <button type="button" class="v-btn v-btn-primary" onclick="loadContent()">إعادة المحاولة</button>
        </div>
      </div>`;
    toast('تعذّر تحميل النص من الخادم');
    return;
  }

  if (ticket !== loadTicket) return;
  window._lastRenderArgs = { textData, fallbackFlags, fetchMeta, variantsMap, countNotesMap };
  renderCurrentView(chosen, textData, start, end, buildDefaultAudioSources(chosen), fallbackFlags, fetchMeta, variantsMap, countNotesMap);

  resolveAudioSources(chosen, curSurah.number)
    .then(sources => {
      if (ticket !== loadTicket) return;
      resolvedAudioSources = sources;
      renderCurrentView(chosen, textData, start, end, sources, fallbackFlags, fetchMeta, variantsMap, countNotesMap);
    })
    .catch(err => {
      if (ticket !== loadTicket) return;
      console.warn('Audio hydration failed:', err);
      toast('تعذّر تجهيز بعض مصادر الصوت');
    });
}

function renderCurrentView(chosen, textData, start, end, audioSources, fallbackFlags, fetchMeta, variantsMap, countNotesMap) {
  if (activeTab === 'mushaf') {
    renderMushaf(chosen, textData, start, end, audioSources, fallbackFlags, fetchMeta, variantsMap, countNotesMap);
  } else {
    renderCompare(chosen, textData, start, end, audioSources, fallbackFlags, fetchMeta, variantsMap, countNotesMap);
  }
}

// ── mushaf view ────────────────────────────────────────────────────────────────
function renderMushaf(chosen, textData, start, end, audioSources, fallbackFlags, fetchMeta = {}, variantsMap = {}, countNotesMap = {}) {
  const showB = curSurah.number !== 9;
  const isF   = curSurah.number === 1;

  let h = `${workspaceHeaderMarkup()}<div class="mushaf-page">
    <div class="mushaf-hdr">
      ${showB && !isF ? '<span class="basmala">بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ</span>' : ''}
      <div class="mushaf-sname">${escHtml(curSurah.name)}</div>
      <div class="mushaf-smeta">${escHtml(curSurah.englishName)} · ${curSurah.revelationType === 'Meccan' ? 'مكية' : 'مدنية'} · ${curSurah.numberOfAyahs} آية</div>
    </div>`;

  const surahModeQiraat = chosen.filter(q => audioSources[q.key]?.mode === 'surah');
  if (surahModeQiraat.length) {
    h += `<div class="sura-audio-list">`;
    surahModeQiraat.forEach(q => {
      const audio = audioSources[q.key];
      h += `<div class="sura-audio-item">
        <span class="sa-label">${escHtml(q.displayName || q.rawiName)} (${escHtml(audio.reciter)}):</span>
        ${buildReciterSelectMarkup(q, audio)}
        ${playerHTML(`sura_${q.key}_${curSurah.number}`, audio.url, q.key, 0)}
      </div>`;
    });
    h += `</div>`;
  }
  h += `<div class="mushaf-body">`;

  for (let i = start; i <= end; i++) {
    const idx     = i - 1;
    const hafsTxt = textData.hafs?.[idx]?.text || '';

    h += `<div class="ayah-block">
      <div class="ayah-master"><span>الآية</span><span class="ayah-badge">${i}</span></div>
      <div class="cards-row">`;

    chosen.forEach(q => {
      const ayahObj    = textData[q.key]?.[idx] || {};
      const txt        = ayahObj.text || '(النص غير متاح لهذه القراءة)';
      const skipDiff   = Boolean(ayahObj.skip_diff);
      const audioAyah  = ayahObj.audio_ayah === undefined ? i : ayahObj.audio_ayah;
      const extraAyah  = ayahObj.audio_ayah_extra || null;
      const audio      = audioSources[q.key] || { mode: 'none', reciter: q.rawiName };
      const pid        = `m_${q.key}_${curSurah.number}_${i}`;
      const isFallback = Boolean(fallbackFlags[q.key] || q.fallback);
      const textState  = fetchMeta[q.key] || { status: 'cached', error: null };
      const qFont      = q.fontFamily || "'Amiri Quran','Amiri',serif";
      const vList      = variantsMap[q.key]?.[String(i)] || [];
      const cNotes     = countNotesMap[q.key]?.[String(i)] || [];

      h += `<div class="q-card${isFallback ? ' is-fallback' : ''}">
        ${buildQiraatLabel(q, audio, textState)}
        ${buildReciterSelectMarkup(q, audio)}
        ${buildCountNotesMarkup(cNotes)}
        <div class="qc-text" style="font-family:${escAttr(qFont)}">${skipDiff ? escHtml(txt) : renderAyahTextWithDiff(txt, hafsTxt, q.key)}</div>
        ${buildVariantsMarkup(vList)}
        ${buildAudioMarkup(audio, pid, q.key, audioAyah, extraAyah, i)}
      </div>`;
    });

    h += '</div></div>';
  }
  h += '</div></div>';
  document.getElementById('content').innerHTML = h;
}

// ── compare view ───────────────────────────────────────────────────────────────
function renderCompare(chosen, textData, start, end, audioSources, fallbackFlags, fetchMeta = {}, variantsMap = {}, countNotesMap = {}) {
  const cols = Math.min(chosen.length || 1, 3);
  let h = `${workspaceHeaderMarkup()}<div class="compare-grid" style="grid-template-columns:repeat(${cols},1fr)">`;

  chosen.forEach(q => {
    const audio      = audioSources[q.key] || { mode: 'none', reciter: q.rawiName };
    const isFallback = Boolean(fallbackFlags[q.key] || q.fallback);
    const textState  = fetchMeta[q.key] || { status: 'cached', error: null };
    const headAudio  = audio.mode === 'surah' ? playerHTML(`cmp_sura_${q.key}_${curSurah.number}`, audio.url, q.key, 0) : '';
    const qFont      = q.fontFamily || "'Amiri Quran','Amiri',serif";

    h += `<div class="cmp-col${isFallback ? ' is-fallback' : ''}">
      <div class="cmp-head">
        <div class="cmp-head-name">
          <span class="qc-dot" style="background:${escAttr(q.color)}"></span>
          ${escHtml(q.displayName || q.rawiName)}
          ${textTierBadge(q, textState)}
        </div>
        <div class="cmp-head-sub">${escHtml(audio.reciter || '')}</div>
        ${buildReciterSelectMarkup(q, audio)}
        ${headAudio ? `<div style="margin-top:8px">${headAudio}</div>` : ''}
      </div>
      <div class="cmp-body">`;

    for (let i = start; i <= end; i++) {
      const idx       = i - 1;
      const ayahObj   = textData[q.key]?.[idx] || {};
      const txt       = ayahObj.text || '(النص غير متاح لهذه القراءة)';
      const skipDiff  = Boolean(ayahObj.skip_diff);
      const audioAyah = ayahObj.audio_ayah === undefined ? i : ayahObj.audio_ayah;
      const extraAyah = ayahObj.audio_ayah_extra || null;
      const hafsTxt   = textData.hafs?.[idx]?.text || '';
      const pid       = `c_${q.key}_${curSurah.number}_${i}`;
      const vList     = variantsMap[q.key]?.[String(i)] || [];
      const cNotes    = countNotesMap[q.key]?.[String(i)] || [];

      h += `<div class="cmp-ayah">
        <div class="cmp-num">${i}</div>
        <div style="flex:1;min-width:0">
          ${buildCountNotesMarkup(cNotes)}
          <div class="cmp-text" style="font-family:${escAttr(qFont)}">${skipDiff ? escHtml(txt) : renderAyahTextWithDiff(txt, hafsTxt, q.key)}</div>
          ${buildVariantsMarkup(vList)}
          ${buildAudioMarkup(audio, pid, q.key, audioAyah, extraAyah, i)}
        </div>
      </div>`;
    }
    h += '</div></div>';
  });

  h += '</div>';
  document.getElementById('content').innerHTML = h;
}

// ── player HTML ────────────────────────────────────────────────────────────────
function playerHTML(pid, url, qKey = '', ayahNum = 0, extraUrl = null) {
  if (!url) return '<div class="audio-player disabled">لا يتوفر صوت مطابق لهذه القراءة عبر المصدر الحالي</div>';
  const extraAttr = extraUrl ? ` data-extra-url="${escAttr(extraUrl)}"` : '';
  return `<div class="audio-player" data-pid="${escAttr(pid)}" data-url="${escAttr(url)}"${extraAttr} data-qkey="${escAttr(qKey)}" data-ayah="${ayahNum}">
    <button type="button" class="play-btn" id="pbtn-${escAttr(pid)}">تشغيل</button>
    <div class="prog-track" id="ptrk-${escAttr(pid)}">
      <div class="prog-rail"><div class="prog-bar" id="pbar-${escAttr(pid)}"></div></div>
    </div>
    <span class="time-lbl" id="ptim-${escAttr(pid)}">0:00</span>
  </div>`;
}

function playerHTMLTimed(pid, qKey, ayahNum, surahUrl, startMs, endMs) {
  return `<div class="audio-player" data-pid="${escAttr(pid)}" data-url="${escAttr(surahUrl)}" data-qkey="${escAttr(qKey)}" data-ayah="${ayahNum}" data-start-ms="${startMs}" data-end-ms="${endMs}">
    <button type="button" class="play-btn" id="pbtn-${escAttr(pid)}">تشغيل</button>
    <div class="prog-track" id="ptrk-${escAttr(pid)}">
      <div class="prog-rail"><div class="prog-bar" id="pbar-${escAttr(pid)}"></div></div>
    </div>
    <span class="time-lbl" id="ptim-${escAttr(pid)}">0:00</span>
  </div>`;
}

// ── global event delegation + playback ─────────────────────────────────────────
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.play-btn');
  if (btn) {
    e.stopPropagation();
    const player = btn.closest('.audio-player');
    if (!player) return;
    const pid = player.dataset.pid;
    const url = player.dataset.url;
    const startMs = player.dataset.startMs !== undefined ? Number(player.dataset.startMs) : null;
    const endMs   = player.dataset.endMs   !== undefined ? Number(player.dataset.endMs)   : null;
    const qKey     = player.dataset.qkey || '';
    const ayah     = Number(player.dataset.ayah || 0);
    const extraUrl = player.dataset.extraUrl || null;
    togglePlay(pid, url, { startMs, endMs, qKey, ayah, extraUrl });
    return;
  }

  const trk = e.target.closest('.prog-track');
  if (trk) {
    const player = trk.closest('.audio-player');
    if (player) seek(player.dataset.pid, e, trk);
  }
});

function _playNextInSequence(qKey, ayah) {
  if (!autoPlayEnabled || !qKey || !ayah) return;
  const prefix = activeTab === 'mushaf' ? 'm' : 'c';
  const maxAyah = curSurah?.numberOfAyahs || ayah + 1;
  for (let nextAyah = ayah + 1; nextAyah <= maxAyah; nextAyah++) {
    const nextPid = `${prefix}_${qKey}_${curSurah.number}_${nextAyah}`;
    const nextPlayer = document.querySelector(`.audio-player[data-pid="${nextPid}"]`);
    if (nextPlayer) {
      const nextBtn = nextPlayer.querySelector('.play-btn');
      if (nextBtn) {
        nextBtn.click();
        return;
      }
    }
  }
}

async function togglePlay(pid, rawUrl, { startMs = null, endMs = null, qKey = '', ayah = 0, extraUrl = null } = {}) {
  Object.entries(audios).forEach(([k, a]) => {
    if (k !== pid && !a.paused) { a.pause(); setState(k, 'idle'); }
  });

  const hasWindow = Number.isFinite(startMs) && Number.isFinite(endMs) && endMs > startMs;
  const startSec = hasWindow ? startMs / 1000 : null;
  const endSec   = hasWindow ? endMs   / 1000 : null;

  let a = audios[pid];
  if (!a) {
    a = new Audio();
    a._proxied = false;
    a._windowStartSec = startSec;
    a._windowEndSec = endSec;
    a._extraUrl = extraUrl ? normalizeAudioUrl(extraUrl) : null;
    a._playingExtra = false;
    audios[pid] = a;

    a.addEventListener('timeupdate', () => {
      updateBar(pid, a);
      if (Number.isFinite(a._windowEndSec) && a.currentTime >= a._windowEndSec) {
        a.pause();
        a.currentTime = a._windowStartSec || 0;
        setState(pid, 'idle');
        resetBar(pid);
        _playNextInSequence(qKey, ayah);
      }
    });

    a.addEventListener('ended', () => {
      if (a._extraUrl && !a._playingExtra) {
        a._playingExtra = true;
        a._proxied = false;
        a._origUrl = a._extraUrl;
        a.src = a._extraUrl;
        a.playbackRate = playbackSpeed;
        a.play().catch(() => {
          a._playingExtra = false;
          setState(pid, 'idle');
          resetBar(pid);
          _playNextInSequence(qKey, ayah);
        });
        return;
      }
      if (a._playingExtra) {
        a._playingExtra = false;
        a._proxied = false;
        const mainUrl = normalizeAudioUrl(rawUrl);
        if (mainUrl) {
          a._origUrl = mainUrl;
          a.src = mainUrl;
          a._srcSet = true;
        }
      }
      setState(pid, 'idle');
      resetBar(pid);
      _playNextInSequence(qKey, ayah);
    });

    a.addEventListener('error', () => {
      if (!a._proxied) {
        const proxyUrl = buildProxyAudioUrl(a._origUrl);
        if (proxyUrl) {
          a._proxied = true;
          a.src = proxyUrl;
          a.playbackRate = playbackSpeed;
          a.play().catch(() => {
            toast('ملف الصوت غير متاح');
            setState(pid, 'idle');
          });
          return;
        }
      }
      toast('ملف الصوت غير متاح أو هناك مشكلة في الاتصال');
      setState(pid, 'idle');
    });
  }

  if (!a._srcSet) {
    const cleanUrl = normalizeAudioUrl(rawUrl);
    if (!cleanUrl) {
      toast('تعذّر تحميل الصوت');
      setState(pid, 'idle');
      return;
    }
    a._origUrl = cleanUrl;
    a.src = cleanUrl;
    a._srcSet = true;
  }

  a.playbackRate = playbackSpeed;

  if (a.paused) {
    setState(pid, 'loading');
    const playAtWindow = () => {
      if (Number.isFinite(a._windowStartSec)) {
        try {
          if (a.currentTime < a._windowStartSec || a.currentTime >= a._windowEndSec) {
            a.currentTime = a._windowStartSec;
          }
        } catch {}
      }
      a.play().then(() => setState(pid, 'playing')).catch(err => {
        console.error('Audio play error:', err);
        setState(pid, 'idle');
        toast('تعذّر تشغيل الصوت');
      });
    };

    if (Number.isFinite(a._windowStartSec) && a.readyState < 1) {
      a.addEventListener('loadedmetadata', () => playAtWindow(), { once: true });
      a.load();
    } else {
      playAtWindow();
    }
  } else {
    a.pause();
    setState(pid, 'idle');
  }
}

function setState(pid, state) {
  const btn = document.getElementById(`pbtn-${pid}`);
  if (!btn) return;
  btn.className = `play-btn${state === 'playing' ? ' is-playing' : state === 'loading' ? ' is-loading' : ''}`;
  btn.textContent = state === 'playing' ? 'إيقاف' : state === 'loading' ? 'جارٍ...' : 'تشغيل';
}

function updateBar(pid, a) {
  const bar = document.getElementById(`pbar-${pid}`);
  const tim = document.getElementById(`ptim-${pid}`);
  if (!bar) return;

  if (Number.isFinite(a._windowStartSec) && Number.isFinite(a._windowEndSec)) {
    const winDur = Math.max(0.1, a._windowEndSec - a._windowStartSec);
    const elapsed = Math.max(0, a.currentTime - a._windowStartSec);
    bar.style.width = `${Math.min(100, (elapsed / winDur) * 100)}%`;
    if (tim) tim.textContent = fmtTime(elapsed);
    return;
  }

  bar.style.width = `${a.duration ? (a.currentTime / a.duration) * 100 : 0}%`;
  if (tim) tim.textContent = fmtTime(a.currentTime);
}

function resetBar(pid) { updateBar(pid, { currentTime: 0, duration: 0 }); }

function seek(pid, e, el) {
  const a = audios[pid];
  if (!a) return;
  const r = el.getBoundingClientRect();
  if (!Number.isFinite(r.width) || r.width <= 0) return;
  const x = Math.max(0, Math.min(r.width, e.clientX - r.left));
  const ratio = x / r.width;

  if (Number.isFinite(a._windowStartSec) && Number.isFinite(a._windowEndSec)) {
    const winDur = a._windowEndSec - a._windowStartSec;
    a.currentTime = a._windowStartSec + ratio * winDur;
    return;
  }
  if (a.duration) a.currentTime = ratio * a.duration;
}

function stopAll() {
  Object.values(audios).forEach(a => {
    try {
      a.pause();
      a.removeAttribute('src');
      a.load();
      a._srcSet = false;
    } catch {}
  });
  audios = {};
}

window.toggleSB = toggleSB;
window.toggleQiraatBar = toggleQiraatBar;
window.filterSurahs = filterSurahs;
window.pickSurah = pickSurah;
window.loadSurahs = loadSurahs;
window.loadContent = loadContent;
window.switchTab = switchTab;
window.applyPreset = applyPreset;
window.toggleDiffHighlight = toggleDiffHighlight;
  window.setAutoPlay = setAutoPlay;
  window.setPlaybackSpeed = setPlaybackSpeed;
  window.onReciterChange = onReciterChange;
})();
