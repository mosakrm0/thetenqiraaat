// translations.js — Translations comparison page
(function () {
  'use strict';

  const {
  escHtml,
  escAttr,
  initTheme,
  toast,
  fmtTime,
  createCache,
  getCachedJson,
  normalizeAudioUrl,
  buildProxyAudioUrl,
} = window.Common;

const cache = createCache('translations-cache-v2:');

let allSurahs       = [];
let curSurah        = null;
let catalog         = [];
let selected        = new Set(['hafs_ar_text']);
let activeTab       = 'mushaf';
let audios          = {};
let searchQuery     = '';
let audioOnly       = false;
let autoPlayEnabled = false;
let playbackSpeed   = 1;

function toggleSB() {
  const sb = document.getElementById('sidebar');
  if (sb) sb.classList.toggle('collapsed');
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

function setState(pid, state) {
  const btn = document.getElementById(`pbtn-${pid}`);
  if (!btn) return;
  btn.className = `play-btn${state === 'playing' ? ' is-playing' : ''}`;
  btn.textContent = state === 'playing' ? 'إيقاف' : 'تشغيل';
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
  }
  tim.textContent = fmtTime(cur);
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

function playerHTML(pid, url, entryKey = '', ayahNum = 0) {
  if (!url) return '<div class="audio-player disabled">لا يتوفر صوت</div>';
  return `<div class="audio-player" data-pid="${escAttr(pid)}" data-url="${escAttr(url)}" data-ekey="${escAttr(entryKey)}" data-ayah="${ayahNum}">
    <button type="button" class="play-btn" id="pbtn-${escAttr(pid)}">تشغيل</button>
    <div class="prog-track" id="ptrk-${escAttr(pid)}">
      <div class="prog-rail"><div class="prog-bar" id="pbar-${escAttr(pid)}"></div></div>
    </div>
    <span class="time-lbl" id="ptim-${escAttr(pid)}">0:00</span>
  </div>`;
}

function _playNextAyah(entryKey, ayahNum) {
  if (!autoPlayEnabled || !entryKey || !ayahNum) return;
  const prefix = activeTab === 'compare' ? 'c' : 'm';
  const safeKey = entryKey.replace(/[^a-zA-Z0-9_]/g, '_');
  const nextPid = `${prefix}_${safeKey}_${ayahNum + 1}`;
  const nextBtn = document.getElementById(`pbtn-${nextPid}`);
  if (nextBtn) nextBtn.click();
}

async function togglePlay(pid, rawUrl, entryKey = '', ayahNum = 0) {
  Object.entries(audios).forEach(([k, a]) => {
    if (k !== pid && a && !a.paused) {
      a.pause();
      setState(k, 'idle');
    }
  });

  let a = audios[pid];
  if (!a) {
    a = new Audio();
    a._proxied = false;
    audios[pid] = a;
    a.addEventListener('timeupdate', () => updateBar(pid, a));
    a.addEventListener('ended', () => {
      setState(pid, 'idle');
      resetBar(pid);
      _playNextAyah(entryKey, ayahNum);
    });
    a.addEventListener('error', () => {
      if (!a._proxied) {
        const proxy = buildProxyAudioUrl(a._origUrl);
        if (proxy) {
          a._proxied = true;
          a.src = proxy;
          a.playbackRate = playbackSpeed;
          a.play().catch(() => { setState(pid, 'idle'); toast('تعذر تشغيل الصوت'); });
          return;
        }
      }
      setState(pid, 'idle');
      toast('تعذر تشغيل الصوت');
    });
  }

  if (!a._srcSet) {
    const clean = normalizeAudioUrl(rawUrl);
    if (!clean) {
      toast('ملف الصوت غير صالح');
      return;
    }
    a._origUrl = clean;
    a.src = clean;
    a._srcSet = true;
  }

  a.playbackRate = playbackSpeed;

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

document.addEventListener('click', (e) => {
  const btn = e.target.closest('.play-btn');
  if (btn) {
    e.stopPropagation();
    const player = btn.closest('.audio-player');
    if (player) {
      togglePlay(
        player.dataset.pid,
        player.dataset.url,
        player.dataset.ekey || '',
        Number(player.dataset.ayah || 0),
      );
    }
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
  const el = document.getElementById('surah-list');
  if (Array.isArray(window.__INITIAL_SURAHS__) && window.__INITIAL_SURAHS__.length) {
    allSurahs = window.__INITIAL_SURAHS__;
    renderList(allSurahs);
    return;
  }
  try {
    const d = await getCachedJson(cache, { key: 'surah-list-local-v1', url: '/api/surahs', ttlMs: 1000 * 60 * 60 * 24, retries: 2 });
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

function languageLabel(code) {
  const c = String(code || '').toLowerCase();
  const map = {
    ar: 'العربية', en: 'English', ur: 'اردو', fa: 'فارسی',
    tr: 'Türkçe', fr: 'Français', de: 'Deutsch', es: 'Español',
    ru: 'Русский', id: 'Bahasa Indonesia', ms: 'Bahasa Melayu',
    az: 'Azərbaycanca', bs: 'Bosanski', bn: 'বাংলা', hi: 'हिन्दी',
    ps: 'پښتو', dv: 'ދިވެހި', cs: 'Čeština', nl: 'Nederlands',
    it: 'Italiano', pt: 'Português', sv: 'Svenska', no: 'Norsk',
    da: 'Dansk', fi: 'Suomi', pl: 'Polski', ro: 'Română',
    sq: 'Shqip', ku: 'Kurdî', tg: 'Тоҷикӣ', ta: 'தமிழ்',
    te: 'తెలుగు', ml: 'മലയാളം', ha: 'Hausa', sw: 'Kiswahili',
    zh: '中文', ja: '日本語', ko: '한국어', th: 'ไทย',
  };
  if (map[c]) return map[c];
  try {
    if (c) {
      const native = new Intl.DisplayNames([c], { type: 'language' }).of(c);
      if (native) return native;
    }
  } catch {}
  return c || 'لغة أخرى';
}

function getFilteredCatalog() {
  const q = searchQuery.trim().toLowerCase();
  return catalog.filter(item => {
    if (audioOnly && !item.has_audio) return false;
    if (!q) return true;
    const langLabel = languageLabel(item.language).toLowerCase();
    return (
      langLabel.includes(q) ||
      String(item.language || '').toLowerCase().includes(q) ||
      String(item.name || '').toLowerCase().includes(q) ||
      String(item.englishName || '').toLowerCase().includes(q)
    );
  });
}

function filterCatalog(q) {
  searchQuery = q || '';
  buildChips();
}

function toggleAudioOnly(enabled) {
  audioOnly = Boolean(enabled);
  buildChips();
}

function buildChips() {
  const wrap = document.getElementById('tr-chips');
  if (!wrap) return;
  wrap.innerHTML = '';

  const items = getFilteredCatalog();
  const selectedItems = catalog.filter(x => selected.has(x.key) && !items.some(y => y.key === x.key));
  const toShow = [...selectedItems, ...items].slice(0, 60);

  toShow.forEach(item => {
    const c = document.createElement('button');
    c.type = 'button';
    c.className = `q-chip${selected.has(item.key) ? ' on' : ''}`;
    c.dataset.key = item.key;
    const label = `${languageLabel(item.language)} · ${item.name || item.englishName}`;
    c.title = label;
    c.innerHTML = `<span class="dot" style="background:${item.has_audio ? '#16A34A' : '#808080'}"></span>${escHtml(label)}${item.has_audio ? ' [صوت]' : ''}`;
    c.onclick = () => {
      if (selected.has(item.key)) selected.delete(item.key);
      else selected.add(item.key);
      buildChips();
      syncUrlState();
      if (curSurah) loadContent();
    };
    wrap.appendChild(c);
  });

  if (items.length > 60) {
    const more = document.createElement('span');
    more.className = 'tr-more-hint';
    more.textContent = `+${items.length - 60} ترجمة أخرى (استخدم البحث)`;
    wrap.appendChild(more);
  }
}

async function loadCatalog() {
  const wrap = document.getElementById('tr-chips');
  try {
    const d = await getCachedJson(cache, {
      key: 'translations-catalog-v2',
      url: '/api/translations/catalog',
      ttlMs: 1000 * 60 * 60 * 12,
      retries: 1,
    });
    catalog = (d.items || []).filter(x => x.mode === 'ayah-text');

    if (selected.size <= 1) {
      const en = catalog.find(x => x.edition === 'en.sahih') || catalog.find(x => (x.language || '') === 'en');
      if (en) selected.add(en.key);
    }

    buildChips();
  } catch {
    if (wrap) {
      wrap.innerHTML = `<span class="tr-more-hint">تعذّر تحميل قائمة الترجمات</span>
        <button type="button" class="v-btn" onclick="loadCatalog()">إعادة المحاولة</button>`;
    }
    toast('تعذّر تحميل قائمة الترجمات');
  }
}

function syncUrlState() {
  try {
    const url = new URL(window.location.href);
    if (curSurah) url.searchParams.set('surah', String(curSurah.number));
    else url.searchParams.delete('surah');
    const s = document.getElementById('r-start');
    const e = document.getElementById('r-end');
    if (curSurah && s && e) {
      url.searchParams.set('start', s.value);
      url.searchParams.set('end', e.value);
    }
    url.searchParams.set('tab', activeTab);
    if (selected.size) url.searchParams.set('keys', Array.from(selected).join(','));
    else url.searchParams.delete('keys');
    window.history.replaceState({}, '', url.toString());
  } catch {}
}

function switchTab(tab) {
  activeTab = tab === 'compare' ? 'compare' : 'mushaf';
  const b1 = document.getElementById('tab-tr-mushaf');
  const b2 = document.getElementById('tab-tr-compare');
  if (b1) b1.classList.toggle('active', activeTab === 'mushaf');
  if (b2) b2.classList.toggle('active', activeTab === 'compare');
  syncUrlState();
  if (curSurah) loadContent();
}

async function pickSurah(num, rangeOverride = null) {
  curSurah = allSurahs.find(s => s.number === num);
  if (!curSurah) return;

  const max = curSurah.numberOfAyahs;
  const sEl = document.getElementById('r-start');
  const eEl = document.getElementById('r-end');
  sEl.max = max;
  eEl.max = max;
  sEl.value = rangeOverride?.start ? Math.max(1, Math.min(max, rangeOverride.start)) : 1;
  eEl.value = rangeOverride?.end ? Math.max(Number(sEl.value), Math.min(max, rangeOverride.end)) : Math.min(max, 7);

  renderList(filterArr(document.getElementById('sb-q').value));
  await loadContent();
}

function workspaceHeaderMarkup() {
  if (!curSurah) return '';
  return `<div class="workspace-hdr">
    <div class="tb-name">${escHtml(curSurah.name)}</div>
    <div class="tb-meta">${escHtml(curSurah.englishName)} · ${curSurah.numberOfAyahs} آية · ${selected.size} ترجمات محددة</div>
  </div>`;
}

function entryLabel(e) {
  const lang = languageLabel(e.language);
  return e.name ? `${lang} — ${e.name}` : lang;
}

function normalizeRange(maxAyah) {
  const start = Math.max(1, Number(document.getElementById('r-start').value || 1));
  const endInput = Number(document.getElementById('r-end').value || start);
  const end = Math.min(maxAyah, Math.max(start, endInput));
  return { start, end };
}

function buildEntryCard(entry, ayah) {
  if (entry.fetch_status === 'error') {
    return `<div class="q-card"><div class="qc-label"><span class="qc-name">${escHtml(entryLabel(entry))}</span></div><div class="qc-text">تعذر الجلب: ${escHtml(entry.error || '')}</div></div>`;
  }
  const txt = entry.ayahs?.[ayah - 1]?.text || '(النص غير متاح)';
  const dir = (entry.direction || 'ltr').toLowerCase() === 'rtl' ? 'rtl' : 'ltr';
  const audioUrl = entry.ayah_audio_map ? entry.ayah_audio_map[ayah] : null;
  const pid = `m_${(entry.key || entry.language || 'x').replace(/[^a-zA-Z0-9_]/g, '_')}_${ayah}`;
  return `<div class="q-card">
    <div class="qc-label"><span class="qc-name">${escHtml(entryLabel(entry))}</span></div>
    <div class="qc-text" dir="${dir}">${escHtml(txt)}</div>
    <div>${playerHTML(pid, audioUrl, entry.key || '', ayah)}</div>
  </div>`;
}

function renderMushafTranslations(data, start, end) {
  let html = `${workspaceHeaderMarkup()}<div class="mushaf-page"><div class="mushaf-body">`;
  for (let ayah = start; ayah <= end; ayah++) {
    const cards = Object.values(data).map(entry => buildEntryCard(entry, ayah)).join('');
    html += `<section class="ayah-block">
      <div class="ayah-master"><span>الآية</span><span class="ayah-badge">${ayah}</span></div>
      <div class="cards-row">${cards}</div>
    </section>`;
  }
  html += '</div></div>';
  return html;
}

function renderCompareTranslations(data, start, end) {
  const entries = Object.values(data);
  const cols = Math.min(entries.length || 1, 3);
  let html = `${workspaceHeaderMarkup()}<div class="compare-grid" style="grid-template-columns:repeat(${cols},1fr)">`;

  entries.forEach(entry => {
    html += `<div class="cmp-col">
      <div class="cmp-head">
        <div class="cmp-head-name">
          ${escHtml(entryLabel(entry))}
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
        <div style="flex:1;min-width:0">
          <div class="cmp-text" dir="${dir}">${escHtml(txt)}</div>
          <div style="margin-top:6px">${playerHTML(pid, audioUrl, entry.key || '', ayah)}</div>
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
    content.innerHTML = `${workspaceHeaderMarkup()}<div class="empty-state v-window">
      <div class="v-titlebar"><span>تنبيه</span><span class="mono">EMPTY</span></div>
      <div class="v-window-body"><div class="empty-title">لا توجد بيانات ترجمة متاحة لهذه السورة</div></div>
    </div>`;
    return;
  }

  const { start, end } = normalizeRange(maxAyah);
  const html = activeTab === 'compare'
    ? renderCompareTranslations(data, start, end)
    : renderMushafTranslations(data, start, end);

  stopAll();
  audios = {};
  content.innerHTML = html;
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
  syncUrlState();
  document.getElementById('content').innerHTML = `${workspaceHeaderMarkup()}
    <div class="v-window" style="max-width:520px;margin:0 auto">
      <div class="v-titlebar"><span>تحميل البيانات</span><span class="mono">WAIT</span></div>
      <div class="loader"><div class="loader-ring"></div><div class="loader-txt">جاري تحميل الترجمات...</div></div>
    </div>`;

  const keys = Array.from(selected);
  try {
    const payload = await getCachedJson(cache, {
      key: `translations:${curSurah.number}:${keys.slice().sort().join(',')}`,
      url: `/api/translations/surah/${curSurah.number}?keys=${encodeURIComponent(keys.join(','))}`,
      ttlMs: 1000 * 60 * 60 * 6,
    });
    renderPayload(payload);
  } catch (err) {
    document.getElementById('content').innerHTML = `${workspaceHeaderMarkup()}
      <div class="empty-state v-window">
        <div class="v-titlebar"><span>خطأ</span><span class="mono">ERR</span></div>
        <div class="v-window-body">
          <div class="empty-title">تعذر تحميل الترجمات</div>
          <div class="empty-sub">${escHtml(err.message || err)}</div>
          <button type="button" class="v-btn v-btn-primary" onclick="loadContent()">إعادة المحاولة</button>
        </div>
      </div>`;
  }
}

window.toggleSB = toggleSB;
window.toggleQiraatBar = toggleQiraatBar;
window.filterSurahs = filterSurahs;
window.pickSurah = pickSurah;
window.loadSurahs = loadSurahs;
window.loadCatalog = loadCatalog;
window.loadContent = loadContent;
window.switchTab = switchTab;
window.filterCatalog = filterCatalog;
window.toggleAudioOnly = toggleAudioOnly;
window.setAutoPlay = setAutoPlay;
window.setPlaybackSpeed = setPlaybackSpeed;

(async function boot() {
  initTheme();
  const params = new URLSearchParams(window.location.search);
  const keysParam = params.get('keys');
  if (keysParam) {
    const keys = keysParam.split(',').map(s => s.trim()).filter(Boolean);
    if (keys.length) selected = new Set(keys);
  }
  const tabParam = params.get('tab');
  if (tabParam === 'compare' || tabParam === 'mushaf') {
    activeTab = tabParam;
    const b1 = document.getElementById('tab-tr-mushaf');
    const b2 = document.getElementById('tab-tr-compare');
    if (b1) b1.classList.toggle('active', activeTab === 'mushaf');
    if (b2) b2.classList.toggle('active', activeTab === 'compare');
  }

  await Promise.all([loadSurahs(), loadCatalog()]);

  const surahNum = Number(params.get('surah'));
  if (surahNum >= 1 && surahNum <= 114 && allSurahs.length) {
    await pickSurah(surahNum, {
      start: Number(params.get('start')) || null,
      end: Number(params.get('end')) || null,
    });
  }
  })();
})();
