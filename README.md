[![CI](https://github.com/mosakrm0/thetenqiraaat/actions/workflows/action.yaml/badge.svg)](https://github.com/mosakrm0/thetenqiraaat/actions/workflows/action.yaml)

# Thetenqiraaat - القراءات العشر والترجمات القرآنية

A Flask + vanilla JS web application for comparing all **20 canonical riwayat (the Ten Qiraat)** and **multi-language Quran translations** side-by-side, with KFGQPC Uthmanic fonts, word-level difference highlighting, scholarly variant & ayah-counting annotations, and 4-tier ayah-by-ayah audio playback.

## Key Features

### Ten Qiraat Comparison (`/readings`)
- **All 20 Riwayat across the 10 Imams:**
  - **8 full KFGQPC digital editions** with dedicated KFGQPC Uthmanic fonts (`warsh10`, `qaloon10`, `bazzi7`, `qumbul7`, `doori9`, `soosi9`, `shouba8`) + Hafs (`quran-uthmani`).
  - **12 annotated riwayat** (`hisham`, `ibn_dhakwan`, `khalaf_hamzah`, `khallad`, `harith`, `douri_kisai`, `wardan`, `ibn_jammaz`, `ruways`, `rawh`, `ishaq`, `idris`) displaying Hafs baseline text alongside curated/structured *farsh*, *usul*, and ayah-counting boundary notes (`qiraat_variants` and `ayah_count_notes` tables).
- **Word-level Diff Highlighting:** Toggleable comparison against Hafs.
- **4-Tier Ayah-by-Ayah Audio Resolver (`/api/audio/surah-map`):**
  1. Per-ayah MP3s (EveryAyah dynamic `recitations.js` & QuranCDN/QDC public API)
  2. MP3Quran v3 full-surah MP3 + `ayat_timing` verse-level slicing (`timed-surah`)
  3. Quran.com / QDC chapter audio + verse timestamps (`timed-surah`)
  4. MP3Quran full-surah fallback (`surah`)
- **Reciter selector, continuous auto-play, playback speed (`0.75x / 1x / 1.25x`), and URL deep-linking.**

### Translations Comparison (`/translations`)
- Searchable catalog of AlQuran Cloud + Fawaz GitHub editions across dozens of languages, with an optional **"With audio only" (`مع صوت فقط`)** filter for EveryAyah-backed tracks and support for comparing multiple editions in the same language.

## Project Structure

```text
thetenqiraaat/
├── app.py                   # Flask entrypoint & HTTP routes
├── config.py                # Canonical 20 riwayat, Imams, API & cache config
├── db.py                    # SQLite connection, schema & seed loaders
├── seed_db.py               # CLI seeder (caches KFGQPC JSONs once per run)
├── quran.db                 # Local SQLite database
├── data/
│   ├── qiraat_variants_seed.json
│   └── ayah_count_notes_seed.json
├── services/
│   ├── http_client.py       # Shared HTTP session, diskcache & SSRF guard
│   ├── qiraat.py            # Qiraat text, variants & ayah-counting service
│   ├── audio.py             # 4-tier audio resolver & reciter discovery
│   └── translations.py      # Concurrent translations catalog & fetcher
├── templates/               # Jinja2 templates
├── static/                  # common.js, script.js, translations.js, feedback.js, style.css
├── tests/                   # Offline unit & integration tests (unittest / pytest)
├── Dockerfile
└── requirements.txt
```

## Setup & Usage

```bash
pip install -r requirements.txt
python seed_db.py --seed-variants
python app.py
```

### Seeder Options
```bash
python seed_db.py --start-surah 1 --end-surah 114   # Seed all surahs (downloads each KFGQPC JSON once)
python seed_db.py --qiraat warsh,qaloon             # Seed specific riwayat
python seed_db.py --seed-variants                   # Re-import local variant & ayah-count seeds
python seed_db.py --sync-ayah-map                   # Sync quranpedia/qiraat-ayah-map from GitHub
```

### Running Tests
```bash
pytest -v
# or
python -m unittest discover -s tests -v
```
