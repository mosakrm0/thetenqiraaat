# Thetenqiraaat - القراءات والترجمات القرآنية

A comprehensive web application for comparing Islamic Quranic readings (qiraat) and translations side-by-side, with support for multiple qiraat variants, editions, and audio recitations.

**Live Demo:** (thetenqiraaat.web.app)

## Features

### 📖 Quranic Readings Comparison
- Compare Islamic Quranic readings across **14 different qiraat variants**:
  - Hafs (حفص)
  - Warsh (ورش)
  - Shouba (شعبة)
  - Qaloon (قالون)
  - Bazzi (البزي)
  - Qumbul (قنبل)
  - Douri (الدوري)
  - Susi (السوسي)
  - Hisham (هشام)
  - Khallad (خلاد)
  - Harith (الحارث)
  - Wardan (وردان)
  - Ruways (رويس)
  - Ishaq (إسحاق)

- **Two viewing modes:**
  - 📖 Mushaf View: Sequential reading through all verses
  - ⚖️ Side-by-side Comparison: Compare qiraat variants directly

### 🌐 Translation Comparison
- Compare **translations from multiple sources** including:
  - AlQuran Cloud API translations (multiple languages and scholars)
  - EveryAyah translation tracks (Arabic, English, Urdu, Persian, Bosnian, Azerbaijani)
  - Fawaz editions API

- **Similar viewing modes:**
  - 📖 Mushaf View: Read translations sequentially
  - ⚖️ Side-by-side Comparison: Compare multiple translations

### 🔊 Audio Support
- **Integrated audio recitations** from multiple sources:
  - Quran Foundation (QF) API - Per-ayah audio
  - EveryAyah - Translation audio tracks
  - mp3quran.net - Audio fallback for various qiraat

- **One-click audio playback** for each verse with source selection

### 🎨 User Interface Features
- 🌓 **Dark/Light theme support** with local storage persistence
- 📱 **Fully responsive design** (mobile, tablet, desktop)
- 🇾🇪 **Right-to-Left (RTL) interface** optimized for Arabic
- ⚡ **Fast local text rendering** - All Quranic text loaded locally
- 🔍 **Surah search** - Quick navigation with filtering
- ♾️ **Infinite scroll** with smooth transitions
- 📊 **Organized UI** with collapsible controls

### 💾 Performance & Reliability
- SQLite database for local Quranic text caching
- **Request retries** with exponential backoff for external APIs
- **Multi-session connection pooling** for HTTP requests
- **TTL-based caching** for API responses (12-24 hours depending on source)
- Audio proxy with **50 MB safety cap**
- 12-second timeout with 2 retries on external requests

## Technology Stack

### Backend
- **Framework:** Flask 3.0.0
- **Language:** Python 3.13
- **Database:** SQLite3
- **HTTP Client:** Requests 2.31.0

### Frontend
- **HTML5** with RTL support
- **CSS3** with CSS custom properties for theming
- **JavaScript** (ES6+) - Vanilla (no frameworks)

### DevOps
- **Containerization:** Docker (Alpine Linux base)

## Project Structure

```
thetenqiraaat/
├── app.py                 # Main Flask application
├── seed_db.py            # Database initialization script
├── quran.db              # SQLite database (Quranic text)
├── requirements.txt      # Python dependencies
├── Dockerfile            # Docker containerization
├── index.html            # Static landing page
├── templates/            # Jinja2 templates
│   ├── index.html       # Landing page template
│   ├── readings.html    # Qiraat comparison interface
│   ├── translations.html # Translation comparison interface
│   └── feedback.html    # Feedback form
└── static/              # Static assets
    ├── style.css        # Main stylesheet
    ├── script.js        # Readings page logic
    ├── translations.js  # Translations page logic
    └── feedback.js      # Feedback form logic
```

## Installation & Usage

### Local Development

#### Prerequisites
- Python 3.13+
- pip or conda

#### Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/thetenqiraaat.git
   cd thetenqiraaat
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Initialize the database** (optional - will auto-init on first run)
   ```bash
   python seed_db.py
   ```

4. **Run the application**
   ```bash
   python -c "from app import app, init_db; init_db(); app.run(debug=True)"
   ```

   The application will start at `http://localhost:5000`

### Docker Deployment

1. **Build the Docker image**
   ```bash
   docker build -t thetenqiraaat .
   ```

2. **Run the container**
   ```bash
   docker run -p 7860:7860 thetenqiraaat
   ```

   Access the application at `http://localhost:7860`

### Environment Variables

Configure optional integrations via environment variables:

```bash
# Quran Foundation API (optional, for private API access)
QF_CLIENT_ID=your_client_id
QF_CLIENT_SECRET=your_client_secret
QF_ENV=production              # or 'prelive' for testing

# API Timeouts
QURAN_API_TIMEOUT=12          # seconds
QURAN_API_RETRIES=2           # retry count
```

## API Endpoints

### Main Pages
- `GET /` - Landing page with navigation
- `GET /readings` - Qiraat comparison interface
- `GET /translations` - Translation comparison interface
- `GET /feedback` - Feedback form page

### Qiraat API
- `GET /api/qiraat` - List all available qiraat variants
- `GET /api/surah/<surah_id>` - Get all verses of a surah with all qiraat
- `GET /api/audio/surah-map` - Get audio URL map for a surah and qiraa
- `GET /api/audio/ayah` - Get audio URL for a specific ayah
- `GET /api/audio-proxy` - Proxy audio file with safety checks

### Translation Queries
- `GET /api/translations/catalog` - Get available translations
- `GET /api/translations/surah/<surah_id>` - Get surah verses with translations
- `GET /api/translations/everyayah` - Get EveryAyah translation tracks
- `GET /api/translations/everyayah/ayah` - Get EveryAyah audio for ayah
- `GET /api/translations/everyayah/surah-map` - Get EveryAyah surah audio map

### Quran Foundation Integration
- `GET /api/qf/source` - Get QF data source info
- `GET /api/qf/ayah-url` - Get QF ayah audio URL (requires OAuth)

## Data Sources

### Quranic Text
- **Primary:** AlQuran Cloud API (`api.alquran.cloud`)
- **Variants:** KFGQPC GitHub repositories (Warsh, Qaloon, Bazzi, Douri, Susi, Shouba, Qumbul)
- **Fallback:** Uthmani text for variants without dedicated digital editions

### Translations
- **AlQuran Cloud:** Multiple translations in various languages
- **Fawaz Editions API:** Community-managed translation editions
- **EveryAyah:** Specialized translation tracks (audio and text)

### Audio
- **Quran Foundation:** Per-ayah recitations with QF Recitations API
- **EveryAyah:** Translation track audio (MP3)
- **mp3quran.net:** Backup recitations for various qiraat

### Caching Strategy
- **Quranic text:** Persistent in SQLite (no expiry)
- **QF data:** 3-6 hours TTL
- **Translation editions:** 12 hours TTL
- **EveryAyah recitations:** 24 hours TTL
- **Audio URLs:** Cached per request with format safety checks

## Database Schema

### ayahs Table
```sql
CREATE TABLE ayahs (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    surah INTEGER,
    ayah  INTEGER,
    qiraa TEXT,
    text  TEXT,
    UNIQUE(surah, ayah, qiraa)
);

CREATE INDEX idx_ayahs_surah_qiraa ON ayahs(surah, qiraa);
```

## Features in Detail

### Dynamic Content Loading
- **Client-side rendering:** All UI updates happen in the browser
- **Lazy loading:** Verses loaded on-demand as user scrolls
- **Optimized API calls:** Grouped requests to minimize server load

### Responsive Design
- **Mobile-first approach** with breakpoints for tablets and desktops
- **Touch-friendly controls** for mobile devices
- **Collapsible sidebar** for better space utilization

### Accessibility
- **ARIA labels** for screen readers
- **Semantic HTML** structure
- **Keyboard navigation** support
- **Theme contrast** compliance

### Theme System
- **Light theme (default):** Easy on the eyes for daytime reading
- **Dark theme:** Reduced eye strain in low-light environments
- **Persistent preference:** Theme choice saved in localStorage

## Performance Optimizations

### Backend
- Connection pooling for HTTP requests (20 max connections)
- Request batching to reduce API calls
- TTL-based caching with automatic expiration
- Thread-safe token management for OAuth flows

### Frontend
- Minimal dependencies (vanilla JavaScript)
- CSS optimized with custom properties
- Event delegation for dynamic content
- Local text rendering (no external font CDNs)

## Browser Support

- Chrome/Chromium 90+
- Firefox 88+
- Safari 14+
- Edge 90+
- Mobile browsers (iOS Safari, Chrome Android)

## Configuration Options

### Quran Foundation Integration
The application supports optional integration with the Quran Foundation's private API for premium audio recitations. Set `QF_CLIENT_ID` and `QF_CLIENT_SECRET` environment variables to enable:

- Higher-quality audio streams
- Additional recitation variants
- Detailed metadata and styling

Without these credentials, the app falls back to public APIs automatically.

### API Timeout Settings
- **Default timeout:** 12 seconds
- **Retries:** 2 attempts with exponential backoff (0.5s backoff factor)
- **Audio proxy limit:** 50 MB per file (security safeguard)

## Troubleshooting

### Database Issues
- If `quran.db` is missing, run `python seed_db.py` to initialize
- Database corruption can be fixed by deleting and recreating: `rm quran.db && python seed_db.py`

### API Connection Issues
- Check internet connectivity
- Verify firewall allows outbound HTTPS connections
- Check API timeout settings in environment variables
- Verify API endpoints are accessible (`api.alquran.cloud`, `everyayah.com`, etc.)

### Audio Playback Issues
- Browser may block autoplay - configure audio settings
- Check if audio hosts are whitelisted in `ALLOWED_AUDIO_HOSTS`
- Verify VPN/proxy doesn't block audio CDNs

### Performance Issues
- Clear browser cache and reload
- Check database size: `ls -lh quran.db`
- Monitor API response times in browser Network tab

## Contributing

Contributions are welcome! Areas for improvement:

- Additional qiraat variants or translations
- UI/UX enhancements
- Performance optimizations
- Bug fixes and testing
- Accessibility improvements

## License

[Specify your license here - e.g., MIT, GPL-3.0, etc.]

## Support & Feedback

- **Issues:** Report bugs via GitHub Issues
- **Feedback form:** Use the in-app feedback form
- **Contact:** [Your contact information]

## Acknowledgments

This project would not be possible without:

- **Quran Foundation** - QF API and CDN for audio
- **AlQuran Cloud** - Translation and text APIs
- **EveryAyah** - Translation tracks and resources
- **KFGQPC** - Quranic variant text sources
- **mp3quran.net** - Audio recitations

## Additional Resources

- [Al-Qur'an al-Karim Information](https://quran.com)
- [Quran Foundation Documentation](https://quranica.quran.foundation/)
- [Qiraat al-Ashra](https://en.wikipedia.org/wiki/Ten_Qira%27at)
- [Arabic RTL Web Standards](https://www.w3.org/International/questions/qa-html-dir)

## Changelog

### Version 1.0.0
- Initial release
- Support for 14 qiraat variants
- Translation comparison across multiple sources
- Audio recitation support
- Dark/light theme toggle
- Mobile-responsive interface

---

**Last Updated:** March 2026

For more information or questions, please open an issue on GitHub or use the in-app feedback form.

---

