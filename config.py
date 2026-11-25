import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / 'quran.db'
DATA_DIR = BASE_DIR / 'data'
CACHE_DIR = BASE_DIR / '.cache'

REQUEST_TIMEOUT = float(os.getenv('QURAN_API_TIMEOUT', '12'))
REQUEST_RETRIES = int(os.getenv('QURAN_API_RETRIES', '2'))
MAX_AUDIO_PROXY_BYTES = 50 * 1024 * 1024  # 50 MB safety cap

KFGQPC_CACHE_TTL_SEC = 60 * 60 * 12
EVERYAYAH_RECITATIONS_URL = 'https://everyayah.com/data/recitations.js'
EVERYAYAH_CACHE_TTL_SEC = 60 * 60 * 24
ALQURAN_TRANSLATIONS_URL = 'https://api.alquran.cloud/v1/edition?format=text&type=translation'
FAWAZ_EDITIONS_URL = 'https://raw.githubusercontent.com/fawazahmed0/quran-api/refs/heads/1/editions.json'
TRANSLATIONS_CACHE_TTL_SEC = 60 * 60 * 12

MP3QURAN_API_BASE = 'https://www.mp3quran.net/api/v3'
MP3QURAN_CACHE_TTL_SEC = 60 * 60 * 24
MP3QURAN_TIMING_EMPTY_TTL_SEC = 60 * 60 * 6

QURANPEDIA_API_BASE = 'https://api.quranpedia.net/v1'
QURANPEDIA_CACHE_TTL_SEC = 60 * 60 * 24

QIRAAT10_API_BASE = os.getenv('QIRAAT10_API_BASE', 'https://qiraat10.com/api/v1').strip().rstrip('/')
QIRAAT_NOTES_URL = 'https://raw.githubusercontent.com/QZTA/qiraat-api/main/data/qiraat-notes.json'
QURAN_DATA_PAGES_URL = 'https://raw.githubusercontent.com/QZTA/qiraat-api/main/data/quran-data.json'
QIRAAT_AYAH_MAP_URL = (
    'https://raw.githubusercontent.com/quranpedia/qiraat-ayah-map/main/data/book-boundary-primitives.json'
)

KFGQPC_JSON_URLS = {
    'warsh':  'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/warsh/data/warshData_v10.json',
    'qaloon': 'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/qaloon/data/QaloonData_v10.json',
    'bazzi':  'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/bazzi/data/BazziData_v07.json',
    'douri':  'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/doori/data/DooriData_v09.json',
    'susi':   'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/soosi/data/SoosiData09.json',
    'shouba': 'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/shouba/data/ShoubaData08.json',
    'qumbul': 'https://raw.githubusercontent.com/thetruetruth/quran-data-kfgqpc/main/qumbul/data/QumbulData_v07.json',
}

KFGQPC_FONT_FAMILIES = {
    'warsh':  "'warsh10', 'Amiri Quran', 'Amiri', serif",
    'qaloon': "'qaloon10', 'Amiri Quran', 'Amiri', serif",
    'bazzi':  "'bazzi7', 'Amiri Quran', 'Amiri', serif",
    'douri':  "'doori9', 'Amiri Quran', 'Amiri', serif",
    'susi':   "'soosi9', 'Amiri Quran', 'Amiri', serif",
    'shouba': "'shouba8', 'Amiri Quran', 'Amiri', serif",
    'qumbul': "'qumbul7', 'Amiri Quran', 'Amiri', serif",
}

COUNTING_SYSTEMS = {
    'kufi':         'العد الكوفي',
    'madani-first': 'العد المدني الأول',
    'madani-last':  'العد المدني الأخير',
    'makki':        'العد المكي',
    'basri':        'العد البصري',
    'dimashqi':     'العد الدمشقي (الشامي)',
}

QF_CLIENT_ID     = os.getenv('QF_CLIENT_ID', '').strip()
QF_CLIENT_SECRET = os.getenv('QF_CLIENT_SECRET', '').strip()
QF_ENV           = os.getenv('QF_ENV', 'production').strip().lower()
QF_QIRAAT_ENABLED = os.getenv('QF_QIRAAT_ENABLED', 'false').strip().lower() in ('1', 'true', 'yes')

QF_AUTH_BASES = {
    'prelive':    'https://prelive-oauth2.quran.foundation',
    'production': 'https://oauth2.quran.foundation',
}
QF_API_BASES = {
    'prelive':    'https://apis-prelive.quran.foundation/content/api/v4',
    'production': 'https://apis.quran.foundation/content/api/v4',
}

QF_PUBLIC_API_BASE       = 'https://api.qurancdn.com/api/qdc'
QURAN_COM_V4_API_BASE    = 'https://api.quran.com/api/v4'
QF_AUDIO_CDN_BASE        = 'https://verses.quran.foundation/'
QF_SCOPE                 = 'content'
QF_TOKEN_BUFFER_SEC      = 30
QF_RESCACHE_TTL_SEC      = 60 * 60 * 6
QF_CHAPTER_CACHE_TTL_SEC = 60 * 60 * 3
QF_PUBLIC_AUDIO_TTL_SEC  = 60 * 60 * 6

RATELIMIT_STORAGE_URI = os.getenv('RATELIMIT_STORAGE_URI', 'memory://').strip() or 'memory://'

IMAMS = [
    {'key': 'nafi',         'name': 'نافع المدني',        'order': 1},
    {'key': 'ibn_kathir',   'name': 'ابن كثير المكي',     'order': 2},
    {'key': 'abu_amr',      'name': 'أبو عمرو البصري',    'order': 3},
    {'key': 'ibn_amir',     'name': 'ابن عامر الشامي',    'order': 4},
    {'key': 'asim',         'name': 'عاصم الكوفي',        'order': 5},
    {'key': 'hamzah',       'name': 'حمزة الكوفي',        'order': 6},
    {'key': 'kisai',        'name': 'الكسائي الكوفي',     'order': 7},
    {'key': 'abu_jafar',    'name': 'أبو جعفر المدني',    'order': 8},
    {'key': 'yaqub',        'name': 'يعقوب الحضرمي',      'order': 9},
    {'key': 'khalaf_ashir', 'name': 'خلف العاشر',         'order': 10},
]

# Single source of truth for all 20 riwayat (the Ten Canonical Qiraat).
QIRAAT = [
    # 1. Nafi'
    {
        'key': 'qaloon', 'textId': 'qaloon', 'source': 'kfgqpc', 'fallback': False,
        'textTier': 'kfgqpc_full', 'fontFamily': KFGQPC_FONT_FAMILIES['qaloon'],
        'countingSystem': 'madani-first', 'imamKey': 'nafi', 'imamName': 'نافع المدني',
        'rawiName': 'قالون', 'displayName': 'نافع - قالون', 'color': '#c9a84c',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['قالون عن نافع', 'qalon', 'qaloon'],
        'qdcHints': ['qaloon', 'qalun'],
        'everyAyahHints': ['qaloon', 'qalun'],
    },
    {
        'key': 'warsh', 'textId': 'warsh', 'source': 'kfgqpc', 'fallback': False,
        'textTier': 'kfgqpc_full', 'fontFamily': KFGQPC_FONT_FAMILIES['warsh'],
        'countingSystem': 'madani-last', 'imamKey': 'nafi', 'imamName': 'نافع المدني',
        'rawiName': 'ورش', 'displayName': 'نافع - ورش', 'color': '#d66a2e',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['ورش عن نافع', 'warsh'],
        'qdcHints': ['warsh'],
        'everyAyahHints': ['warsh'],
    },
    # 2. Ibn Kathir
    {
        'key': 'bazzi', 'textId': 'bazzi', 'source': 'kfgqpc', 'fallback': False,
        'textTier': 'kfgqpc_full', 'fontFamily': KFGQPC_FONT_FAMILIES['bazzi'],
        'countingSystem': 'makki', 'imamKey': 'ibn_kathir', 'imamName': 'ابن كثير المكي',
        'rawiName': 'البزي', 'displayName': 'ابن كثير - البزي', 'color': '#4c9ac9',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['البزي عن ابن كثير', 'بزي', 'bazzi'],
        'qdcHints': ['bazzi'],
        'everyAyahHints': ['bazzi'],
    },
    {
        'key': 'qumbul', 'textId': 'qumbul', 'source': 'kfgqpc', 'fallback': False,
        'textTier': 'kfgqpc_full', 'fontFamily': KFGQPC_FONT_FAMILIES['qumbul'],
        'countingSystem': 'makki', 'imamKey': 'ibn_kathir', 'imamName': 'ابن كثير المكي',
        'rawiName': 'قنبل', 'displayName': 'ابن كثير - قنبل', 'color': '#5f7ad9',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['قنبل عن ابن كثير', 'قنبل', 'qumbul', 'qunbul'],
        'qdcHints': ['qumbul', 'qunbul'],
        'everyAyahHints': ['qumbul', 'qunbul'],
    },
    # 3. Abu Amr
    {
        'key': 'douri', 'textId': 'douri', 'source': 'kfgqpc', 'fallback': False,
        'textTier': 'kfgqpc_full', 'fontFamily': KFGQPC_FONT_FAMILIES['douri'],
        'countingSystem': 'basri', 'imamKey': 'abu_amr', 'imamName': 'أبو عمرو البصري',
        'rawiName': 'الدوري', 'displayName': 'أبو عمرو - الدوري', 'color': '#7aad4c',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['الدوري عن أبي عمرو', 'الدوري عن ابي عمرو', 'doori', 'douri'],
        'qdcHints': ['duri', 'douri', 'doori'],
        'everyAyahHints': ['douri', 'doori', 'duri'],
    },
    {
        'key': 'susi', 'textId': 'susi', 'source': 'kfgqpc', 'fallback': False,
        'textTier': 'kfgqpc_full', 'fontFamily': KFGQPC_FONT_FAMILIES['susi'],
        'countingSystem': 'basri', 'imamKey': 'abu_amr', 'imamName': 'أبو عمرو البصري',
        'rawiName': 'السوسي', 'displayName': 'أبو عمرو - السوسي', 'color': '#5bc0a3',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['السوسي عن أبي عمرو', 'السوسي عن ابي عمرو', 'السوسي', 'susi', 'soosi'],
        'qdcHints': ['susi', 'sousi', 'soosi'],
        'everyAyahHints': ['susi', 'soosi', 'sousi'],
    },
    # 4. Ibn Amir
    {
        'key': 'hisham', 'textId': 'quran-uthmani', 'source': 'alquran', 'fallback': True,
        'textTier': 'annotated_hafs', 'fontFamily': "'Amiri Quran','Amiri',serif",
        'countingSystem': 'dimashqi', 'imamKey': 'ibn_amir', 'imamName': 'ابن عامر الشامي',
        'rawiName': 'هشام', 'displayName': 'ابن عامر - هشام', 'color': '#9c4cc9',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['هشام عن ابن عامر', 'هشام', 'hisham'],
        'qdcHints': ['hisham'],
        'everyAyahHints': ['hisham'],
    },
    {
        'key': 'ibn_dhakwan', 'textId': 'quran-uthmani', 'source': 'alquran', 'fallback': True,
        'textTier': 'annotated_hafs', 'fontFamily': "'Amiri Quran','Amiri',serif",
        'countingSystem': 'dimashqi', 'imamKey': 'ibn_amir', 'imamName': 'ابن عامر الشامي',
        'rawiName': 'ابن ذكوان', 'displayName': 'ابن عامر - ابن ذكوان', 'color': '#b06ad9',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['ابن ذكوان عن ابن عامر', 'ابن ذكوان', 'ذكوان', 'dhakwan'],
        'qdcHints': ['dhakwan'],
        'everyAyahHints': ['dhakwan'],
    },
    # 5. Asim
    {
        'key': 'shouba', 'textId': 'shouba', 'source': 'kfgqpc', 'fallback': False,
        'textTier': 'kfgqpc_full', 'fontFamily': KFGQPC_FONT_FAMILIES['shouba'],
        'countingSystem': 'kufi', 'imamKey': 'asim', 'imamName': 'عاصم الكوفي',
        'rawiName': 'شعبة', 'displayName': 'عاصم - شعبة', 'color': '#f0a23a',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['شعبة عن عاصم', 'شعبة', 'shouba', "shu'bah"],
        'qdcHints': ['shouba', 'shuba', "shu'bah"],
        'everyAyahHints': ['shouba', 'shuba'],
    },
    {
        'key': 'hafs', 'textId': 'quran-uthmani', 'source': 'alquran', 'fallback': False,
        'textTier': 'full', 'fontFamily': "'Amiri Quran','Amiri',serif",
        'countingSystem': 'kufi', 'imamKey': 'asim', 'imamName': 'عاصم الكوفي',
        'rawiName': 'حفص', 'displayName': 'عاصم - حفص', 'color': '#4cc9a0',
        'qfPublicId': 7, 'rewayaId': 1,
        'mp3quranHints': ['حفص عن عاصم', 'hafs'],
        'qdcHints': ['hafs'],
        'everyAyahHints': ['alafasy', 'husary', 'minshawi', 'abdul_basit', 'hafs'],
    },
    # 6. Hamzah
    {
        'key': 'khalaf_hamzah', 'textId': 'quran-uthmani', 'source': 'alquran', 'fallback': True,
        'textTier': 'annotated_hafs', 'fontFamily': "'Amiri Quran','Amiri',serif",
        'countingSystem': 'kufi', 'imamKey': 'hamzah', 'imamName': 'حمزة الكوفي',
        'rawiName': 'خلف', 'displayName': 'حمزة - خلف', 'color': '#d96b6b',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['خلف عن حمزة', 'حمزة', 'khalaf'],
        'qdcHints': ['khalaf'],
        'everyAyahHints': ['khalaf'],
    },
    {
        'key': 'khallad', 'textId': 'quran-uthmani', 'source': 'alquran', 'fallback': True,
        'textTier': 'annotated_hafs', 'fontFamily': "'Amiri Quran','Amiri',serif",
        'countingSystem': 'kufi', 'imamKey': 'hamzah', 'imamName': 'حمزة الكوفي',
        'rawiName': 'خلاد', 'displayName': 'حمزة - خلاد', 'color': '#c94c4c',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['خلاد عن حمزة', 'خلاد', 'khallad'],
        'qdcHints': ['khallad'],
        'everyAyahHints': ['khallad'],
    },
    # 7. Al-Kisa'i
    {
        'key': 'harith', 'textId': 'quran-uthmani', 'source': 'alquran', 'fallback': True,
        'textTier': 'annotated_hafs', 'fontFamily': "'Amiri Quran','Amiri',serif",
        'countingSystem': 'kufi', 'imamKey': 'kisai', 'imamName': 'الكسائي الكوفي',
        'rawiName': 'أبو الحارث', 'displayName': 'الكسائي - أبو الحارث', 'color': '#cc7f2a',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['أبو الحارث عن الكسائي', 'ابو الحارث عن الكسائي', 'الحارث', 'harith'],
        'qdcHints': ['harith'],
        'everyAyahHints': ['harith'],
    },
    {
        'key': 'douri_kisai', 'textId': 'quran-uthmani', 'source': 'alquran', 'fallback': True,
        'textTier': 'annotated_hafs', 'fontFamily': "'Amiri Quran','Amiri',serif",
        'countingSystem': 'kufi', 'imamKey': 'kisai', 'imamName': 'الكسائي الكوفي',
        'rawiName': 'الدوري', 'displayName': 'الكسائي - الدوري', 'color': '#e09a48',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['الدوري عن الكسائي', 'الكسائي', 'kisai'],
        'qdcHints': ['kisai'],
        'everyAyahHints': ['kisai'],
    },
    # 8. Abu Ja'far
    {
        'key': 'wardan', 'textId': 'quran-uthmani', 'source': 'alquran', 'fallback': True,
        'textTier': 'annotated_hafs', 'fontFamily': "'Amiri Quran','Amiri',serif",
        'countingSystem': 'madani-first', 'imamKey': 'abu_jafar', 'imamName': 'أبو جعفر المدني',
        'rawiName': 'ابن وردان', 'displayName': 'أبو جعفر - ابن وردان', 'color': '#2aa2b0',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['ابن وردان عن أبي جعفر', 'ابن وردان عن ابي جعفر', 'وردان', 'wardan'],
        'qdcHints': ['wardan'],
        'everyAyahHints': ['wardan'],
    },
    {
        'key': 'ibn_jammaz', 'textId': 'quran-uthmani', 'source': 'alquran', 'fallback': True,
        'textTier': 'annotated_hafs', 'fontFamily': "'Amiri Quran','Amiri',serif",
        'countingSystem': 'madani-first', 'imamKey': 'abu_jafar', 'imamName': 'أبو جعفر المدني',
        'rawiName': 'ابن جمّاز', 'displayName': 'أبو جعفر - ابن جمّاز', 'color': '#42c2d1',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['ابن جماز عن أبي جعفر', 'ابن جماز عن ابي جعفر', 'جماز', 'jammaz'],
        'qdcHints': ['jammaz'],
        'everyAyahHints': ['jammaz'],
    },
    # 9. Ya'qub
    {
        'key': 'ruways', 'textId': 'quran-uthmani', 'source': 'alquran', 'fallback': True,
        'textTier': 'annotated_hafs', 'fontFamily': "'Amiri Quran','Amiri',serif",
        'countingSystem': 'basri', 'imamKey': 'yaqub', 'imamName': 'يعقوب الحضرمي',
        'rawiName': 'رويس', 'displayName': 'يعقوب - رويس', 'color': '#8cbf26',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['رويس عن يعقوب', 'رويس', 'ruways', 'ruwais'],
        'qdcHints': ['ruways', 'ruwais'],
        'everyAyahHints': ['ruways'],
    },
    {
        'key': 'rawh', 'textId': 'quran-uthmani', 'source': 'alquran', 'fallback': True,
        'textTier': 'annotated_hafs', 'fontFamily': "'Amiri Quran','Amiri',serif",
        'countingSystem': 'basri', 'imamKey': 'yaqub', 'imamName': 'يعقوب الحضرمي',
        'rawiName': 'روح', 'displayName': 'يعقوب - روح', 'color': '#a8d44c',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['روح عن يعقوب', 'روح', 'rawh'],
        'qdcHints': ['rawh'],
        'everyAyahHints': ['rawh'],
    },
    # 10. Khalaf al-'Ashir
    {
        'key': 'ishaq', 'textId': 'quran-uthmani', 'source': 'alquran', 'fallback': True,
        'textTier': 'annotated_hafs', 'fontFamily': "'Amiri Quran','Amiri',serif",
        'countingSystem': 'kufi', 'imamKey': 'khalaf_ashir', 'imamName': 'خلف العاشر',
        'rawiName': 'إسحاق', 'displayName': 'خلف العاشر - إسحاق', 'color': '#d16b8a',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['إسحاق عن خلف', 'اسحاق عن خلف', 'إسحاق', 'اسحاق', 'ishaq'],
        'qdcHints': ['ishaq'],
        'everyAyahHints': ['ishaq'],
    },
    {
        'key': 'idris', 'textId': 'quran-uthmani', 'source': 'alquran', 'fallback': True,
        'textTier': 'annotated_hafs', 'fontFamily': "'Amiri Quran','Amiri',serif",
        'countingSystem': 'kufi', 'imamKey': 'khalaf_ashir', 'imamName': 'خلف العاشر',
        'rawiName': 'إدريس', 'displayName': 'خلف العاشر - إدريس', 'color': '#e38ca7',
        'qfPublicId': None, 'rewayaId': None,
        'mp3quranHints': ['إدريس عن خلف', 'ادريس عن خلف', 'إدريس', 'ادريس', 'idris'],
        'qdcHints': ['idris'],
        'everyAyahHints': ['idris'],
    },
]

QURANPEDIA_RAWI_MAP = {
    'qaloon':        {'rawi_id': 1,  'defaults': [(257, 'محمود خليل الحصري (قالون)', 'https://files.quranpedia.net/recitations/257/')]},
    'warsh':         {'rawi_id': 2,  'defaults': [(262, 'عبد الباسط عبد الصمد (ورش)', 'https://files.quranpedia.net/recitations/262/')]},
    'bazzi':         {'rawi_id': 3,  'defaults': [(268, 'محمد عبد الحكيم (البزي)', 'https://files.quranpedia.net/recitations/268/')]},
    'qumbul':        {'rawi_id': 4,  'defaults': [(269, 'محمد عبد الحكيم (قنبل)', 'https://files.quranpedia.net/recitations/269/')]},
    'douri':         {'rawi_id': 5,  'defaults': [(270, 'محمود خليل الحصري (الدوري عن أبي عمرو)', 'https://files.quranpedia.net/recitations/270/')]},
    'susi':          {'rawi_id': 6,  'defaults': [(272, 'عبد الرشيد صوفي (السوسي)', 'https://files.quranpedia.net/recitations/272/')]},
    'hisham':        {'rawi_id': 7,  'defaults': [(273, 'مفتاح محمد السلطني (هشام)', 'https://files.quranpedia.net/recitations/273/')]},
    'ibn_dhakwan':   {'rawi_id': 8,  'defaults': [(274, 'مفتاح محمد السلطني (ابن ذكوان)', 'https://files.quranpedia.net/recitations/274/')]},
    'shouba':        {'rawi_id': 9,  'defaults': [(275, 'عبد الرشيد صوفي (شعبة)', 'https://files.quranpedia.net/recitations/275/')]},
    'hafs':          {'rawi_id': 10, 'defaults': [(251, 'إبراهيم الأخضر (حفص)', 'https://files.quranpedia.net/recitations/251/')]},
    'khalaf_hamzah': {'rawi_id': 11, 'defaults': [(277, 'عبد الرشيد صوفي (خلف عن حمزة)', 'https://files.quranpedia.net/recitations/277/')]},
    'khallad':       {'rawi_id': 12, 'defaults': [(278, 'مفتاح محمد السلطني (خلاد)', 'https://files.quranpedia.net/recitations/278/')]},
    'harith':        {'rawi_id': 13, 'defaults': [(279, 'عبد الرشيد صوفي (أبو الحارث)', 'https://files.quranpedia.net/recitations/279/')]},
    'douri_kisai':   {'rawi_id': 14, 'defaults': [(280, 'عبد الرشيد صوفي (الدوري عن الكسائي)', 'https://files.quranpedia.net/recitations/280/')]},
    'wardan':        {'rawi_id': 15, 'defaults': [(282, 'مفتاح محمد السلطني (ابن وردان)', 'https://files.quranpedia.net/recitations/282/')]},
    'ibn_jammaz':    {'rawi_id': 16, 'defaults': [(283, 'مفتاح محمد السلطني (ابن جماز)', 'https://files.quranpedia.net/recitations/283/')]},
    'ruways':        {'rawi_id': 17, 'defaults': [(284, 'ياسر المزروعي (رويس)', 'https://files.quranpedia.net/recitations/284/')]},
    'rawh':          {'rawi_id': 18, 'defaults': [(286, 'ياسر المزروعي (روح)', 'https://files.quranpedia.net/recitations/286/')]},
    'ishaq':         {'rawi_id': 19, 'defaults': [(287, 'مفتاح محمد السلطني (إسحاق)', 'https://files.quranpedia.net/recitations/287/')]},
    'idris':         {'rawi_id': 20, 'defaults': [(288, 'مفتاح محمد السلطني (إدريس)', 'https://files.quranpedia.net/recitations/288/')]},
}

for _q in QIRAAT:
    _qp = QURANPEDIA_RAWI_MAP.get(_q['key'], {})
    _q['quranpediaRawiId'] = _qp.get('rawi_id')
    _q['quranpediaDefaultReciters'] = _qp.get('defaults', [])

QIRAAT_BY_KEY = {q['key']: q for q in QIRAAT}

QF_QIRAA_HINTS = {
    'hafs':          ['حفص', 'hafs', 'asim'],
    'warsh':         ['ورش', 'warsh', 'nafi'],
    'shouba':        ['شعبة', 'shouba', "shu'bah", 'asim', 'عاصم'],
    'qaloon':        ['قالون', 'qaloon', 'qalon', 'nafi'],
    'bazzi':         ['البزي', 'bazzi', 'ibn kathir', 'ابن كثير'],
    'qumbul':        ['قنبل', 'qumbul', 'qunbul', 'ibn kathir', 'ابن كثير'],
    'douri':         ['الدوري', 'doori', 'duri', 'abu amr', 'أبو عمرو'],
    'susi':          ['السوسي', 'susi', 'sousi', 'abu amr', 'أبو عمرو'],
    'hisham':        ['هشام', 'hisham', 'ibn amir', 'ابن عامر'],
    'ibn_dhakwan':   ['ذكوان', 'dhakwan', 'ibn amir', 'ابن عامر'],
    'khalaf_hamzah': ['خلف', 'khalaf', 'hamzah', 'حمزة'],
    'khallad':       ['خلاد', 'khallad', 'hamzah', 'حمزة'],
    'harith':        ['الحارث', 'harith', 'kisai', 'الكسائي'],
    'douri_kisai':   ['الدوري', 'douri', 'kisai', 'الكسائي'],
    'wardan':        ['وردان', 'wardan', 'abu jafar', 'أبو جعفر'],
    'ibn_jammaz':    ['جماز', 'jammaz', 'abu jafar', 'أبو جعفر'],
    'ruways':        ['رويس', 'ruways', 'yaqub', 'يعقوب'],
    'rawh':          ['روح', 'rawh', 'yaqub', 'يعقوب'],
    'ishaq':         ['إسحاق', 'اسحاق', 'ishaq', 'khalaf', 'خلف'],
    'idris':         ['إدريس', 'ادريس', 'idris', 'khalaf', 'خلف'],
}

ALLOWED_AUDIO_HOSTS = {
    'everyayah.com',
    'www.everyayah.com',
    'files.quranpedia.net',
    'verse.mp3quran.net',
    'cdn.islamic.network',
    'verses.quran.foundation',
    'audio.qurancdn.com',
    'download.quranicaudio.com',
    'cdn.mp3quran.net',
    'server6.mp3quran.net',  'server7.mp3quran.net',  'server8.mp3quran.net',
    'server9.mp3quran.net',  'server10.mp3quran.net', 'server11.mp3quran.net',
    'server12.mp3quran.net', 'server13.mp3quran.net', 'server14.mp3quran.net',
    'server15.mp3quran.net', 'server16.mp3quran.net',
}
