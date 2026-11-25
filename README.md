[![CI](https://github.com/mosakrm0/thetenqiraaat/actions/workflows/action.yaml/badge.svg)](https://github.com/mosakrm0/thetenqiraaat/actions/workflows/action.yaml)

# Thetenqiraaat - القراءات العشر والترجمات القرآنية

A Flask + vanilla JS web application with a **Vintage 90s Desktop OS** UI (`#008080` teal & `#C0C0C0` silver-gray, zero emojis) for comparing all **20 canonical riwayat (the Ten Qiraat)** and **multi-language Quran translations** side-by-side, with KFGQPC Uthmanic fonts, word-level difference highlighting, 604-page *Shatibiyyah & Durrah* annotations, canonical ayah-counting notes, and per-ayah audio playback for all 20 riwayat.

## Key Features

### Ten Qiraat Comparison (`/readings`)
- **All 20 Riwayat across the 10 Imams:**
  - **8 full digital Mushafs (all 114 surahs pre-seeded in `quran.db`):** Hafs (`quran-uthmani`) plus 7 KFGQPC editions (`warsh`, `qaloon`, `bazzi`, `qumbul`, `douri`, `susi`, `shouba`) with dedicated KFGQPC Uthmanic fonts (`warsh10`, `qaloon10`, `bazzi7`, `qumbul7`, `doori9`, `soosi9`, `shouba8`).
  - **12 annotated riwayat** (`hisham`, `ibn_dhakwan`, `khalaf_hamzah`, `khallad`, `harith`, `douri_kisai`, `wardan`, `ibn_jammaz`, `ruways`, `rawh`, `ishaq`, `idris`) displaying Hafs baseline text alongside **20,000+** per-ayah *Farsh* and *Usul* annotations (`qiraat_variants`) and **710** canonical ayah-counting boundary notes (`ayah_count_notes`).
- **4-Tier Ayah-by-Ayah Audio Resolver (`/api/audio/surah-map` & `/api/audio/reciters`):**
  1. Per-ayah MP3s across **all 20 riwayat** via Quranpedia (`files.quranpedia.net`), EveryAyah (`recitations.js`), and QuranCDN/QDC public API.
  2. MP3Quran v3 full-surah MP3 + `ayat_timing` verse-level slicing (`timed-surah`).
  3. Quran.com / QDC chapter audio + verse timestamps (`timed-surah`).
  4. MP3Quran full-surah fallback (`surah`).
- **Word-level diff highlighting, Al-Fatiha verse alignment, reciter selector, continuous auto-play, playback speed (`0.75x / 1x / 1.25x`), and URL deep-linking.**

### Translations Comparison (`/translations`)
- Deduplicated, popularity-ordered catalog of AlQuran Cloud + Fawaz GitHub editions with language dropdown, Arabic/English search, `"With audio only"` (`مع صوت فقط`) filter, selected-pills strip, and collapsible Vintage listbox.

### Local Surah Index (`/api/surahs`)
- All 114 canonical Surahs (6,236 ayahs) are stored locally in `data/surahs.json`, server-rendered into `#surah-list` on first paint, and exposed at `GET /api/surahs`.

## Project Structure

```text
thetenqiraaat/
├── app.py                   # Flask entrypoint & HTTP routes
├── config.py                # Canonical 20 riwayat, Imams, API & cache config
├── db.py                    # SQLite connection, schema & seed loaders
├── seed_db.py               # CLI seeder (caches KFGQPC JSONs once per run)
├── quran.db                 # Local SQLite database
├── data/
│   ├── surahs.json          # 114 canonical Surahs metadata
│   ├── qiraat_variants_seed.json
│   └── ayah_count_notes_seed.json
├── services/
│   ├── http_client.py       # Shared HTTP session, diskcache & SSRF guard
│   ├── qiraat.py            # Qiraat text, 604-page Farsh/Usul & ayah-counting service
│   ├── audio.py             # 4-tier audio resolver & reciter discovery
│   └── translations.py      # Concurrent deduplicated translations catalog & fetcher
├── templates/               # Jinja2 templates (index, readings, translations, feedback)
├── static/                  # common.js, script.js, translations.js, feedback.js, style.css
├── tests/                   # Offline unit & integration tests (unittest / pytest)
├── Dockerfile
└── requirements.txt
```

## Setup & Usage

```bash
pip install -r requirements.txt
python app.py
```

### Environment Variables
- `RATELIMIT_STORAGE_URI` — Flask-Limiter storage backend (defaults to `memory://`; set a shared store like Redis for multi-worker Gunicorn).
- `QURAN_API_TIMEOUT` / `QURAN_API_RETRIES` — upstream request timeout (default `12s`) and retry count (default `2`).
- `QF_CLIENT_ID`, `QF_CLIENT_SECRET`, `QF_ENV`, `QF_QIRAAT_ENABLED` — optional Quran Foundation OAuth2 integration.

### Seeder Options
```bash
python seed_db.py --start-surah 1 --end-surah 114   # Seed all surahs (downloads each KFGQPC JSON once)
python seed_db.py --qiraat warsh,qaloon             # Seed specific riwayat
python seed_db.py --seed-variants                   # Re-import local variant & ayah-count seeds
python seed_db.py --sync-ayah-map                   # Sync quranpedia/qiraat-ayah-map from GitHub
python seed_db.py --sync-qiraat-notes               # Sync 604-page Ten-Qiraat Farsh/Usul notes
python seed_db.py --skip-ayahs --sync-qiraat-notes  # Sync annotations without touching ayahs
```

### Running Tests
```bash
pytest -v
# or
python -m unittest discover -s tests -v
```
