const THEME_KEY = 'qiraat-theme';

let allSurahs = [];
let curSurah = null;
let catalog = [];
let selected = new Set(['hafs']);
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

async function jget(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
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
  document.querySelectorAll('.audio-player[data-pid]').forEach(el => {
    const pid = el.dataset.pid;
    const url = el.dataset.url;
    const btn = document.getElementById(`pbtn-${pid}`);
    const trk = document.getElementById(`ptrk-${pid}`);
    if (btn) {
      btn.onclick = (e) => {
        e.stopPropagation();
        togglePlay(pid, url);
      };
    }
    if (trk) trk.onclick = (e) => seek(pid, e, trk);
  });
}

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
  const d = await jget('/api/surahs');
  allSurahs = d.data || [];
  renderList(allSurahs);
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
    c.innerHTML = `<span class="dot" style="background:#c9a84c"></span>${esc(item.name || languageLabel(item.language))}`;
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
  const d = await jget('/api/translations/catalog');
  catalog = (d.items || []).filter(x => x.mode === 'ayah-text');

  if (!catalog.find(x => x.key === 'hafs') && catalog[0]) {
    selected = new Set([catalog[0].key]);
  }

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
  return e.name || languageLabel(e.language);
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
    const payload = await jget(`/api/translations/surah/${curSurah.number}?keys=${encodeURIComponent(keys.join(','))}`);
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
