// translations.js — Translations comparison page
(function () {
  'use strict';

  const {
    escHtml,
    escAttr,
    normalizeArabicSearch,
    initTheme,
    toast,
    fmtTime,
    createCache,
    getCachedJson,
    normalizeAudioUrl,
    buildProxyAudioUrl,
    toggleSidebar,
    closeSidebarOnMobile,
    initResponsiveShell,
  } = window.Common;

  const cache = createCache('translations-cache-v3:');

  let allSurahs       = [];
  let curSurah        = null;
  let catalog         = [];
  let selected        = new Set(['hafs_ar_text']);
  let activeTab       = 'mushaf';
  let audios          = {};
  let searchQuery     = '';
  let langFilter      = '';
  let audioOnly       = false;
  let pickerOpen      = false;
  let loadTicket      = 0;
  let autoPlayEnabled = false;
  let playbackSpeed   = 1;

  const LANG_META = {
    ar: { native: 'العربية',            ar: 'العربية عربي' },
    en: { native: 'English',            ar: 'الإنجليزية انجليزي إنجليزي' },
    ur: { native: 'اردو',               ar: 'الأردية أردو اردو' },
    fa: { native: 'فارسی',              ar: 'الفارسية فارسي' },
    tr: { native: 'Türkçe',             ar: 'التركية تركي' },
    fr: { native: 'Français',           ar: 'الفرنسية فرنسي' },
    id: { native: 'Bahasa Indonesia',   ar: 'الإندونيسية إندونيسي اندونيسي' },
    de: { native: 'Deutsch',            ar: 'الألمانية ألماني الماني' },
    es: { native: 'Español',            ar: 'الإسبانية إسباني اسباني' },
    ru: { native: 'Русский',            ar: 'الروسية روسي' },
    bn: { native: 'বাংলা',               ar: 'البنغالية بنغالي' },
    ms: { native: 'Bahasa Melayu',      ar: 'الملايوية ماليزي' },
    bs: { native: 'Bosanski',           ar: 'البوسنية بوسني' },
    az: { native: 'Azərbaycanca',       ar: 'الأذربيجانية أذربيجاني' },
    hi: { native: 'हिन्दी',               ar: 'الهندية هندي' },
    ps: { native: 'پښتو',               ar: 'البشتوية بشتو' },
    dv: { native: 'ދިވެހި',              ar: 'المالديفية ديفهي' },
    cs: { native: 'Čeština',            ar: 'التشيكية تشيكي' },
    nl: { native: 'Nederlands',         ar: 'الهولندية هولندي' },
    it: { native: 'Italiano',           ar: 'الإيطالية إيطالي ايطالي' },
    pt: { native: 'Português',          ar: 'البرتغالية برتغالي' },
    sv: { native: 'Svenska',            ar: 'السويدية سويدي' },
    no: { native: 'Norsk',              ar: 'النرويجية نرويجي' },
    da: { native: 'Dansk',              ar: 'الدنماركية دنماركي' },
    fi: { native: 'Suomi',              ar: 'الفنلندية فنلندي' },
    pl: { native: 'Polski',             ar: 'البولندية بولندي' },
    ro: { native: 'Română',             ar: 'الرومانية روماني' },
    sq: { native: 'Shqip',              ar: 'الألبانية ألباني الباني' },
    ku: { native: 'Kurdî',              ar: 'الكردية كردي' },
    tg: { native: 'Тоҷикӣ',             ar: 'الطاجيكية طاجيكي' },
    ta: { native: 'தமிழ்',              ar: 'التاميلية تاميل' },
    te: { native: 'తెలుగు',             ar: 'التيلوغوية تيلوغو' },
    ml: { native: 'മലയാളം',             ar: 'المالايالامية مالايالام' },
    ha: { native: 'Hausa',              ar: 'الهوسا هوسا' },
    sw: { native: 'Kiswahili',          ar: 'السواحيلية سواحيلي' },
    zh: { native: '中文',                ar: 'الصينية صيني' },
    ja: { native: '日本語',              ar: 'اليابانية ياباني' },
    ko: { native: '한국어',              ar: 'الكورية كوري' },
    th: { native: 'ไทย',                ar: 'التايلاندية تايلاندي' },
  };

  function toggleSB(forceCollapse) {
    toggleSidebar(forceCollapse);
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
    const trk = document.getElementById(`ptrk-${pid}`);
    if (!a || !bar || !tim) return;
    const dur = a.duration;
    const cur = a.currentTime;
    if (Number.isFinite(dur) && dur > 0) {
      const pct = Math.max(0, Math.min(100, (cur / dur) * 100));
      bar.style.width = `${pct}%`;
      if (trk) trk.setAttribute('aria-valuenow', String(Math.round(pct)));
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
      if (a) {
        try {
          a.pause();
          a.removeAttribute('src');
          a.load();
          a._srcSet = false;
        } catch {}
      }
      setState(pid, 'idle');
    });
    audios = {};
  }

  function playerHTML(pid, url, entryKey = '', ayahNum = 0) {
    if (!url) return '<div class="audio-player disabled">لا يتوفر صوت</div>';
    return `<div class="audio-player" data-pid="${escAttr(pid)}" data-url="${escAttr(url)}" data-ekey="${escAttr(entryKey)}" data-ayah="${ayahNum}">
      <button type="button" class="play-btn" id="pbtn-${escAttr(pid)}">تشغيل</button>
      <div class="prog-track" id="ptrk-${escAttr(pid)}" role="slider" tabindex="0" aria-label="تقديم أو تأخير الصوت" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0">
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
    const rmBtn = e.target.closest('.tr-sel-remove[data-remove-key]');
    if (rmBtn) {
      removeSelected(rmBtn.dataset.removeKey);
      return;
    }

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

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && pickerOpen) {
      openPicker(false);
      return;
    }
    const trk = e.target.closest('.prog-track');
    if (!trk) return;
    const player = trk.closest('.audio-player');
    const a = player ? audios[player.dataset.pid] : null;
    if (!a || !Number.isFinite(a.duration) || a.duration <= 0) return;
    let handled = true;
    if (e.key === 'ArrowRight') a.currentTime = Math.min(a.duration, a.currentTime + 5);
    else if (e.key === 'ArrowLeft') a.currentTime = Math.max(0, a.currentTime - 5);
    else if (e.key === 'Home') a.currentTime = 0;
    else if (e.key === 'End') a.currentTime = a.duration;
    else handled = false;
    if (handled) e.preventDefault();
  });

  function filterArr(q) {
    if (!q) return allSurahs;
    const nq = normalizeArabicSearch(q);
    const qq = String(q).toLowerCase();
    return allSurahs.filter(s =>
      normalizeArabicSearch(s.name).includes(nq) ||
      String(s.englishName || '').toLowerCase().includes(qq) ||
      String(s.number).startsWith(String(q).trim())
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
    if (LANG_META[c]) return LANG_META[c].native;
    try {
      if (c) {
        const native = new Intl.DisplayNames([c], { type: 'language' }).of(c);
        if (native) return native;
      }
    } catch {}
    return c || 'لغة أخرى';
  }

  function languageSearchText(code) {
    const c = String(code || '').toLowerCase();
    const meta = LANG_META[c];
    return `${c} ${languageLabel(c)} ${meta ? meta.ar : ''}`.toLowerCase();
  }

  function getFilteredCatalog() {
    const q = searchQuery.trim().toLowerCase();
    return catalog.filter(item => {
      if (audioOnly && !item.has_audio) return false;
      if (langFilter && (item.language || '') !== langFilter) return false;
      if (!q) return true;
      return (
        languageSearchText(item.language).includes(q) ||
        String(item.name || '').toLowerCase().includes(q) ||
        String(item.englishName || '').toLowerCase().includes(q) ||
        String(item.edition || '').toLowerCase().includes(q)
      );
    });
  }

  function openPicker(open) {
    pickerOpen = Boolean(open);
    const panel = document.getElementById('tr-picker-panel');
    const toggleBtn = document.getElementById('tr-picker-toggle');
    if (panel) panel.style.display = pickerOpen ? 'block' : 'none';
    if (toggleBtn) {
      toggleBtn.setAttribute('aria-expanded', String(pickerOpen));
      const cnt = getFilteredCatalog().length;
      toggleBtn.textContent = pickerOpen ? `إخفاء القائمة (${cnt})` : `القائمة (${cnt})`;
    }
  }

  function togglePicker() {
    openPicker(!pickerOpen);
  }

  function populateLangFilter() {
    const sel = document.getElementById('tr-lang-filter');
    if (!sel) return;
    const counts = new Map();
    const order = [];
    catalog.forEach(item => {
      const lang = item.language || '';
      if (!lang) return;
      if (!counts.has(lang)) {
        counts.set(lang, 0);
        order.push(lang);
      }
      counts.set(lang, counts.get(lang) + 1);
    });

    sel.innerHTML = `<option value="">جميع اللغات (${catalog.length})</option>` +
      order.map(lang => {
        const meta = LANG_META[lang];
        const arShort = meta ? meta.ar.split(' ')[0] : '';
        const label = arShort && arShort !== languageLabel(lang)
          ? `${languageLabel(lang)} - ${arShort} (${counts.get(lang)})`
          : `${languageLabel(lang)} (${counts.get(lang)})`;
        return `<option value="${escAttr(lang)}"${lang === langFilter ? ' selected' : ''}>${escHtml(label)}</option>`;
      }).join('');
  }

  function renderSelectedBar() {
    const bar = document.getElementById('tr-selected-bar');
    if (!bar) return;
    const chosen = Array.from(selected).map(k => catalog.find(c => c.key === k)).filter(Boolean);
    if (!chosen.length) {
      bar.innerHTML = `<span class="tr-selected-lbl">المختارة: لا يوجد</span>
        <button type="button" class="v-btn" onclick="openPicker(true)">اختر ترجمات</button>`;
      return;
    }

    bar.innerHTML = `<span class="tr-selected-lbl">المختارة (${chosen.length}):</span>` +
      chosen.map(item => {
        const label = `${languageLabel(item.language)} · ${item.name || item.englishName}`;
        return `<span class="tr-sel-pill">
          <span>${escHtml(label)}</span>
          <button type="button" class="tr-sel-remove" data-remove-key="${escAttr(item.key)}" aria-label="إزالة ${escAttr(label)}">x</button>
        </span>`;
      }).join('') +
      `<button type="button" class="v-btn" onclick="resetSelected()">افتراضي</button>`;
  }

  function renderEmptySelection() {
    const content = document.getElementById('content');
    if (!content) return;
    stopAll();
    content.innerHTML = `${workspaceHeaderMarkup()}<div class="empty-state v-window">
      <div class="v-titlebar"><span>تنبيه</span><span class="mono">READY</span></div>
      <div class="v-window-body">
        <div class="empty-title">لم يتم اختيار أي ترجمة</div>
        <div class="empty-sub">اختر ترجمة واحدة على الأقل من القائمة لعرض الآيات.</div>
      </div>
    </div>`;
  }

  function removeSelected(key) {
    selected.delete(key);
    renderSelectedBar();
    buildChips();
    syncUrlState();
    if (curSurah) {
      if (selected.size) loadContent();
      else renderEmptySelection();
    }
  }

  function resetSelected() {
    selected = new Set(['hafs_ar_text']);
    const en = catalog.find(x => x.edition === 'en.sahih') || catalog.find(x => (x.language || '') === 'en');
    if (en) selected.add(en.key);
    renderSelectedBar();
    buildChips();
    syncUrlState();
    if (curSurah) loadContent();
  }

  function filterCatalog(q) {
    searchQuery = q || '';
    const clearBtn = document.getElementById('tr-clear-search');
    if (clearBtn) clearBtn.style.display = searchQuery ? 'inline-flex' : 'none';
    buildChips();
    openPicker(true);
  }

  function clearCatalogSearch() {
    const inp = document.getElementById('tr-search');
    if (inp) inp.value = '';
    filterCatalog('');
  }

  function filterByLang(lang) {
    langFilter = lang || '';
    buildChips();
    openPicker(true);
  }

  function toggleAudioOnly(enabled) {
    audioOnly = Boolean(enabled);
    buildChips();
    openPicker(true);
  }

  function buildChips() {
    const wrap = document.getElementById('tr-chips');
    const titleEl = document.getElementById('tr-picker-title');
    if (!wrap) return;
    wrap.innerHTML = '';

    const items = getFilteredCatalog();
    if (titleEl) titleEl.textContent = `قائمة الترجمات المتاحة (${items.length})`;

    const toggleBtn = document.getElementById('tr-picker-toggle');
    if (toggleBtn) {
      toggleBtn.textContent = pickerOpen ? `إخفاء القائمة (${items.length})` : `القائمة (${items.length})`;
    }

    if (!items.length) {
      wrap.innerHTML = '<div class="tr-more-hint" style="padding:12px">لا توجد ترجمات مطابقة للبحث</div>';
      return;
    }

    const toShow = items.slice(0, 120);
    toShow.forEach(item => {
      const isOn = selected.has(item.key);
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.role = 'option';
      btn.setAttribute('aria-selected', String(isOn));
      btn.className = `tr-option-row${isOn ? ' on' : ''}`;
      btn.innerHTML = `
        <span class="tr-opt-state">${isOn ? '[محدد]' : '[ ]'}</span>
        <span class="tr-opt-lang">${escHtml(languageLabel(item.language))}</span>
        <span class="tr-opt-name">${escHtml(item.name || item.englishName)}</span>
        <span class="tr-opt-src">${escHtml(item.source || '')}</span>
        ${item.has_audio ? '<span class="tr-opt-audio">[صوت]</span>' : ''}
      `;
      btn.onclick = () => {
        if (selected.has(item.key)) selected.delete(item.key);
        else selected.add(item.key);
        renderSelectedBar();
        buildChips();
        syncUrlState();
        if (curSurah) {
          if (selected.size) loadContent();
          else renderEmptySelection();
        }
      };
      wrap.appendChild(btn);
    });

    if (items.length > 120) {
      const more = document.createElement('div');
      more.className = 'tr-more-hint';
      more.style.padding = '8px 12px';
      more.textContent = `يتم عرض أول 120 نتيجة من أصل ${items.length} — اختر لغة أو ابحث لتضييق النتائج`;
      wrap.appendChild(more);
    }
  }

  async function loadCatalog() {
    const wrap = document.getElementById('tr-chips');
    try {
      const d = await getCachedJson(cache, {
        key: 'translations-catalog-v3',
        url: '/api/translations/catalog',
        ttlMs: 1000 * 60 * 60 * 12,
        retries: 1,
      });
      catalog = (d.items || []).filter(x => x.mode === 'ayah-text');

      if (selected.size <= 1) {
        const en = catalog.find(x => x.edition === 'en.sahih') || catalog.find(x => (x.language || '') === 'en');
        if (en) selected.add(en.key);
      }

      populateLangFilter();
      renderSelectedBar();
      buildChips();
      openPicker(false);
    } catch {
      if (wrap) {
        wrap.innerHTML = `<div class="tr-more-hint" style="padding:12px">تعذّر تحميل قائمة الترجمات
          <button type="button" class="v-btn" style="margin-right:8px" onclick="loadCatalog()">إعادة المحاولة</button></div>`;
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
    closeSidebarOnMobile();
    stopAll();

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
    const sEl = document.getElementById('r-start');
    const eEl = document.getElementById('r-end');
    const start = Math.max(1, Math.trunc(Number(sEl.value)) || 1);
    const endInput = Math.trunc(Number(eEl.value)) || start;
    const end = Math.min(maxAyah, Math.max(start, endInput));
    sEl.value = String(start);
    eEl.value = String(end);
    return { start, end };
  }

  function orderedEntries(data) {
    const out = [];
    const seen = new Set();
    for (const k of selected) {
      if (data[k]) {
        out.push(data[k]);
        seen.add(k);
      }
    }
    for (const [k, v] of Object.entries(data)) {
      if (!seen.has(k) && v) out.push(v);
    }
    return out;
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
    const entries = orderedEntries(data);
    let html = `${workspaceHeaderMarkup()}<div class="mushaf-page"><div class="mushaf-body">`;
    for (let ayah = start; ayah <= end; ayah++) {
      const cards = entries.map(entry => buildEntryCard(entry, ayah)).join('');
      html += `<section class="ayah-block">
        <div class="ayah-master"><span>الآية</span><span class="ayah-badge">${ayah}</span></div>
        <div class="cards-row">${cards}</div>
      </section>`;
    }
    html += '</div></div>';
    return html;
  }

  function renderCompareTranslations(data, start, end) {
    const entries = orderedEntries(data);
    const cols = Math.min(entries.length || 1, 3);
    let html = `${workspaceHeaderMarkup()}<div class="compare-grid" data-cols="${cols}" style="--cmp-cols:${cols}">`;

    entries.forEach(entry => {
      html += `<div class="cmp-col">
        <div class="cmp-head">
          <div class="cmp-head-name">
            ${escHtml(entryLabel(entry))}
          </div>
        </div>
        <div class="cmp-body">`;

      if (entry.fetch_status === 'error') {
        html += `<div class="cmp-ayah"><div style="flex:1;min-width:0"><div class="cmp-text">تعذر الجلب: ${escHtml(entry.error || '')}</div></div></div>`;
      } else {
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
    stopAll();
    const ticket = ++loadTicket;
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
      if (ticket !== loadTicket) return;
      renderPayload(payload);
    } catch (err) {
      if (ticket !== loadTicket) return;
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
  window.clearCatalogSearch = clearCatalogSearch;
  window.filterByLang = filterByLang;
  window.toggleAudioOnly = toggleAudioOnly;
  window.openPicker = openPicker;
  window.togglePicker = togglePicker;
  window.removeSelected = removeSelected;
  window.resetSelected = resetSelected;
  window.setAutoPlay = setAutoPlay;
  window.setPlaybackSpeed = setPlaybackSpeed;

  (async function boot() {
    initTheme();
    initResponsiveShell();
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
