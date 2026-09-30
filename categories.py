"""
Kategori taksonomisi ve otomatik sınıflandırma.

Eşleştirme kelime sınırına göre yapılır; "printable" içindeki "table" veya
"card" içindeki "car" gibi yanlış eşleşmeler oluşmaz. Türkçe karakterler ASCII'ye
katlanır (ı→i, ş→s ...), camelCase ve "v2" gibi sürüm ekleri ayrıştırılır.
"""

import html
import re
import unicodedata

OTHER = 'other'

# key, etiket, ikon (static sprite içindeki sembol adı)
CATEGORY_DEFS = [
    ('printer', '3D Yazıcı & Atölye', 'printer'),
    ('keychain', 'Anahtarlık & Aksesuar', 'key-round'),
    ('vehicle', 'Araç & Taşıt', 'car'),
    ('miniature', 'Bebek Evi & Minyatür', 'armchair'),
    ('puzzle', 'Bulmaca & Oyun', 'puzzle'),
    ('decor', 'Dekorasyon & Sanat', 'palette'),
    ('tech', 'Elektronik & Teknoloji', 'cpu'),
    ('home', 'Ev & Yaşam', 'house'),
    ('fidget', 'Fidget & Oyuncak', 'orbit'),
    ('figure', 'Figür & Karakter', 'person-standing'),
    ('letters', 'Harf & Yazı', 'type'),
    ('storage', 'Kutu & Düzenleme', 'package'),
    ('desk', 'Masaüstü & Ofis', 'monitor'),
    ('mechanical', 'Mekanik & Dişli', 'cog'),
    ('music', 'Müzik', 'music'),
    ('fun', 'Şaka & Eğlence', 'laugh'),
    ('seasonal', 'Yılbaşı & Özel Gün', 'gift'),
    (OTHER, 'Diğer', 'shapes'),
]

CATEGORY_KEYS = [key for key, _, _ in CATEGORY_DEFS]
CATEGORY_LABELS = {key: label for key, label, _ in CATEGORY_DEFS}

# Eşit puanda hangi kategorinin kazanacağı (daha özgül olan önce).
TIE_PRIORITY = [
    'seasonal', 'miniature', 'fun', 'music', 'puzzle', 'fidget', 'vehicle', 'figure',
    'keychain', 'letters', 'mechanical', 'printer', 'tech', 'desk', 'storage', 'home',
    'decor', OTHER,
]

# Anahtar kelimeler ASCII'ye katlanmış ve küçük harflidir.
#   "kelime"      → tam kelime eşleşmesi
#   "kelime*"     → önek eşleşmesi (anahtar* → anahtarlik, anahtarlikv...)
#   "iki kelime"  → ardışık kelime öbeği
KEYWORDS = {
    'seasonal': {
        'christmas': 5, 'xmas': 5, 'noel': 5, 'yilbasi': 5, 'santa': 5, 'rudolf': 5, 'rudolph': 5,
        'reindeer': 4, 'grinch*': 5, 'bauble': 5, 'baubles': 5, 'ornament': 4, 'ornaments': 4,
        'snowman': 4, 'snowflake': 4, 'gingerbread': 5, 'gingy': 5, 'elf': 3, 'halloween': 5,
        'pumpkin': 4, 'ghost': 3, 'easter': 5, 'paskalya': 4, 'valentine': 5, 'valentines': 5,
        'sevgililer': 4, 'heart': 1.5, 'kalp': 1.5, 'cake topper': 4, 'topper': 2, 'birthday': 4,
        'dogum gunu': 4, 'party': 3, 'wedding': 4, 'dugun': 4, 'gift': 2, 'hediye': 2,
        'anneler gunu': 4, 'babalar gunu': 4, 'bayram': 4, 'ramazan': 4, 'new year': 4,
        'advent': 4, 'nativity': 4, 'candy cane': 4,
    },
    'miniature': {
        'barbie': 6, 'polly': 6, 'doll': 5, 'dolls': 5, 'dollhouse': 5, 'doll house': 5,
        'dreamhouse': 5, 'bebek': 4, 'minyatur': 4, 'miniature': 4, 'miniatures': 4, 'h0': 3,
        'ho scale': 4, 'diorama': 4, 'ranza': 3, 'bunk': 2, 'mesa': 1.5, 'silla': 2, 'amaca': 2,
        'tabla': 1, 'toilet': 1.5, 'furniture': 2, 'mobilya': 2, 'playground': 2, 'slide': 1.5,
        'kaydirak': 2, 'oyun alani': 4, 'swing': 2, 'salincak': 2, 'sylvanian': 5, 'lol surprise': 5,
    },
    'fun': {
        'prank': 5, 'saka': 5, 'joke': 5, 'funny': 4, 'komik': 4, 'eglence': 3, 'eglenceli': 3,
        'nah': 4, 'middle finger': 5, 'surpriz': 4, 'surprise': 3, 'gag': 4, 'troll': 4,
        'meme': 4, 'fart': 4,
    },
    'music': {
        'music': 5, 'muzik': 5, 'flute': 5, 'flut': 5, 'whistle': 5, 'duduk': 5, 'pan flute': 5,
        'ocarina': 5, 'guitar': 5, 'gitar': 5, 'guitar pick': 5, 'drum': 4, 'davul': 4, 'piano': 4,
        'piyano': 4, 'violin': 5, 'keman': 4, 'harmonica': 5, 'kazoo': 5, 'ukulele': 5, 'saz': 3,
        'recorder': 3, 'kalimba': 5,
    },
    'puzzle': {
        'puzzle': 5, 'puzzles': 5, 'bulmaca': 5, 'maze': 5, 'labirent': 5, 'labyrinth': 5,
        'game': 4, 'games': 4, 'oyun': 3, 'chess': 5, 'satranc': 5, 'dice': 5, 'die': 2, 'zar': 3,
        'd6': 4, 'd12': 4, 'd20': 5, 'd30': 5,
        'board game': 5, 'tangram': 5, 'sudoku': 5, 'tic tac toe': 5, 'domino': 5, 'rubik': 5,
        'brain teaser': 5, 'cryptex': 5, 'riddle': 3, 'checkers': 5, 'dama': 3, 'tavla': 5,
        'backgammon': 5, 'okey': 4, 'jenga': 5, 'mancala': 5,
    },
    'fidget': {
        'fidget': 5, 'fidgets': 5, 'spinner': 4, 'spinners': 4, 'twisty': 3, 'passthrough': 3,
        'spiral': 1, 'hourglass': 2, 'toy': 2, 'toys': 2, 'oyuncak': 3, 'kipir': 4,
        'stress': 2, 'clicker': 3, 'infinity cube': 4, 'gyro': 3, 'yoyo': 3, 'yo yo': 3,
        'slinky': 3, 'popit': 3, 'pop it': 3, 'snake': 1.5, 'shape snake': 4, 'matryoshka': 4,
        'print in place': 1, 'flexi': 1.5, 'articulated': 1.5, 'spinning top': 4, 'topac': 4,
        '608': 1, 'bearing': 1,
    },
    'vehicle': {
        'car': 4, 'cars': 4, 'araba': 4, 'jeep': 5, 'willys': 5, 'vehicle': 4, 'vehicles': 4,
        'arac': 3, 'nissan': 5, '240z': 5, 'delorean': 5, 'dmc': 4, 'truck': 4, 'kamyon': 4,
        'bus': 3, 'otobus': 3, 'plane': 4, 'airplane': 4, 'aeroplane': 4, 'ucak': 4,
        'aircraft': 4, 'helicopter': 4, 'helikopter': 4, 'boat': 4, 'tekne': 4, 'ship': 3,
        'gemi': 3, 'tractor': 4, 'traktor': 4, 'motorcycle': 4, 'motosiklet': 4, 'bike': 3,
        'bisiklet': 3, 'kit card': 4, 'kitcard': 5, 'gift card': 2, 'wind up': 1, 'rc': 2,
        'train': 3, 'tren': 3, 'locomotive': 4, 'rocket': 3, 'roket': 3, 'tank': 2,
        'ferrari': 5, 'porsche': 5, 'lamborghini': 5, 'bmw': 4, 'toyota': 4, 'mustang': 4,
        'formula': 3, 'f1': 3, 'race car': 5,
    },
    'figure': {
        'figure': 4, 'figures': 4, 'figur': 4, 'figurine': 4, 'statue': 4, 'heykel': 4,
        'bust': 4, 'sculpture': 4, 'character': 3, 'karakter': 3, 'pokemon': 5, 'pikachu': 5,
        'moana': 5, 'disney': 3, 'calcifer': 5, 'kalcifer': 5, 'masha': 4, 'urso': 4,
        'bear': 3, 'bar': 1, 'animal': 2, 'animals': 2, 'hayvan': 2, 'cat': 3, 'kedi': 3,
        'dog': 3, 'kopek': 3, 'dragon': 3, 'ejderha': 3, 'dinosaur': 3, 'dino': 3, 'owl': 2,
        'baykus': 2, 'shark': 3, 'kopekbaligi': 3, 'fish': 2, 'balik': 2, 'bird': 2, 'kus': 2,
        'unicorn': 4, 'woman': 3, 'kadin': 3, 'girl': 2, 'boy': 2, 'man': 2, 'anime': 4,
        'naruto': 4, 'goku': 4, 'mario': 4, 'yoda': 4, 'grogu': 4, 'marvel': 4, 'batman': 4,
        'spiderman': 4, 'groot': 4, 'minion': 4, 'sonic': 4, 'mandalorian': 4, 'stitch': 4,
        'kitty': 3, 'penguin': 3, 'turtle': 3, 'elephant': 3, 'lion': 3, 'fox': 3, 'frog': 3,
        'octopus': 3, 'axolotl': 3, 'totoro': 5, 'ghibli': 5, 'superhero': 4, 'warrior': 3,
        'knight': 3, 'wizard': 3, 'skull': 2, 'kafatasi': 2,
    },
    'keychain': {
        'keychain': 5, 'keychains': 5, 'keyring': 5, 'key chain': 5, 'key ring': 5,
        'key cover': 5, 'keycover': 5, 'key holder': 5, 'key hanger': 5, 'anahtar*': 5,
        'llavero': 5, 'porta chiavi': 5, 'portachiavi': 5, 'chiavi': 4, 'key': 2, 'keys': 2,
        'kwikset': 4, 'schlage': 4, 'jewelry': 4, 'jewellery': 4, 'taki': 4, 'bracelet': 4,
        'bileklik': 4, 'necklace': 4, 'kolye': 4, 'earring': 4, 'earrings': 4, 'kupe': 3,
        'pendant': 3, 'wearable': 3, 'giyilebilir': 3, 'glasses': 3, 'gozluk': 3,
        'sunglasses': 3, 'pinhole': 4, 'wallet': 4, 'cuzdan': 4, 'watch band': 4, 'strap': 2,
        'hair clip': 4, 'toka': 3, 'ring': 1, 'yuzuk': 4, 'badge': 2, 'rozet': 3,
    },
    'letters': {
        'letter': 4, 'letters': 4, 'harf': 5, 'harfler': 5, 'alphabet*': 5, 'alfabe': 5,
        'abecedario': 5, 'letras': 5, 'abc': 5, 'a b c': 5, 'a z': 3, 'text': 3, 'yazi': 4,
        'name': 3, 'isim': 4, 'name tag': 4, 'sign': 3, 'tabela': 4, 'nameplate': 4, 'logo': 2,
        'number': 3, 'numbers': 3, 'rakam': 4, 'rakamlar': 4, 'font': 3, 'monogram': 4,
        'initials': 4, 'lettering': 4, 'isaret*': 1,
    },
    'mechanical': {
        'gear': 4, 'gears': 4, 'disli': 4, 'gearbox': 4, 'planetary': 3, 'helical': 3,
        'helical gear': 4, 'nautilus': 2, 'mechanism': 4, 'mekanizma': 4, 'mechanical': 4,
        'mekanik': 4, 'ratchet': 3, 'ratcheted': 3, 'hinge': 3, 'mentese': 3, 'spring': 3,
        'yay': 2, 'linkage': 3, 'cam': 2, 'crank': 3, 'pulley': 4, 'kasnak': 4,
        'gear cube': 4, 'screwless cube': 3, 'robot': 3, 'robotic': 3, 'mechanical hand': 5,
        'prosthetic': 4, 'protez': 4, 'geneva': 4, 'differential': 4, 'actuator': 4,
    },
    'printer': {
        'printer': 5, 'yazici': 5, '3d printer': 5, 'ender': 6, 'creality': 3, 'prusa': 6,
        'bambu': 4, 'bambu lab': 6, 'voron': 6, 'anycubic': 6, 'elegoo': 5, 'spool': 5,
        'makara': 4, 'filament': 4, 'nozzle': 5, 'hotend': 5, 'extruder': 5, 'bed level': 5,
        'print bed': 5, 'calibration': 4, 'kalibrasyon': 4, 'benchy': 5, 'test print': 4,
        'tool': 2, 'tools': 2, 'alet': 3, 'atolye': 4, 'workshop': 4, 'glue gun': 5, 'glue': 2,
        'screwdriver': 4, 'tornavida': 4, 'wrench': 4, 'anahtar takimi': 4, 'drill': 4,
        'matkap': 4, 'clamp': 3, 'mengene': 3, 'vise': 3, 'jig': 3, 'bit holder': 4,
        'spool stop': 5, 'endcap': 2, 'ams': 3, 'ptfe': 3,
    },
    'tech': {
        'battery': 5, 'batteries': 5, 'batt': 4, 'pil': 5, 'aaa': 3, 'aa': 2, '18650': 5,
        'usb': 5, 'sd': 4, 'usd': 3, 'microsd': 5, 'micro sd': 5, 'sd card': 5, 'ssd': 5,
        'hdd': 5, 'hard drive': 5, 'nvme': 5, 'electronics': 5, 'electronic': 5,
        'elektronik': 5, 'arduino': 5, 'raspberry': 5, 'raspberry pi': 5, 'esp32': 5,
        'esp8266': 5, 'pcb': 4, 'sensor': 3, 'charger': 4, 'charging': 4, 'sarj': 4,
        'cable': 3, 'cables': 3, 'kablo': 3, 'cable clip': 5, 'cable organizer': 5,
        'cable management': 5, 'adapter': 3, 'adaptor': 3, 'router': 4, 'modem': 4,
        'camera': 4, 'kamera': 4, 'lens': 4, 'lens hood': 5, 'canon': 4, 'nikon': 4,
        'sony': 3, 'gopro': 5, 'tripod': 4, 'remote': 3, 'kumanda': 3, 'speaker': 3,
        'hoparlor': 3, 'lightning': 3, 'port': 1, 'usb c': 4, 'type c': 4, 'phone case': 4,
        'airpods': 4, 'controller': 3, 'joystick': 4, 'gamepad': 4, 'ps5': 4, 'xbox': 4,
        'switch': 2, 'hdmi': 4, 'ethernet': 4, 'led strip': 4,
    },
    'desk': {
        'desk': 4, 'masa*': 2, 'office': 4, 'ofis': 4, 'monitor': 3, 'laptop': 3, 'keyboard': 4,
        'klavye': 4, 'mouse': 2, 'pen': 3, 'pens': 3, 'pencil': 3, 'kalem': 4, 'kalemlik': 5,
        'kalem kutusu': 5, 'pencil case': 5, 'stationery': 5, 'kirtasiye': 5, 'notebook': 2,
        'stapler': 4, 'phone': 3, 'telefon': 3, 'tablet': 3, 'ipad': 3, 'headphone': 4,
        'headphones': 4, 'headset': 4, 'kulaklik': 4, 'phone stand': 5, 'phone holder': 5,
        'stand': 2, 'standi': 2, 'tutucu': 1, 'desk organizer': 5, 'business card': 4,
        'bookend': 4, 'bookmark': 4, 'ayrac': 3,
    },
    'storage': {
        'box': 3, 'boxes': 3, 'kutu': 4, 'kutusu': 4, 'storage': 4, 'organizer': 4,
        'organiser': 4, 'duzenleyici': 4, 'drawer': 4, 'drawers': 4, 'cekmece': 4, 'tray': 3,
        'bin': 3, 'bins': 3, 'container': 4, 'caddy': 3, 'crate': 4, 'basket': 3, 'sepet': 3,
        'shelf': 3, 'raf': 3, 'storage box': 3, 'tool box': 4, 'toolbox': 4, 'gridfinity': 5,
        'case': 2, 'holder': 1, 'rack': 1.5, 'jar': 3, 'kavanoz': 3, 'canister': 3,
    },
    'home': {
        'kitchen': 4, 'mutfak': 4, 'bathroom': 4, 'banyo': 4, 'towel': 3, 'havlu': 3,
        'paper towel': 4, 'clip': 2, 'clips': 2, 'bag clip': 5, 'mandal': 4, 'hook': 3,
        'hooks': 3, 'kanca': 3, 'hanger': 3, 'aski': 3, 'squeezer': 4, 'toothpaste': 5,
        'tube squeezer': 5, 'cleaning': 4, 'temizleme': 4, 'temizlik': 4, 'brush': 2,
        'firca': 2, 'sponge': 3, 'sunger': 3, 'soap': 4, 'sabun': 4, 'coaster': 4,
        'bardak altligi': 4, 'cup': 1, 'bowl': 2, 'kase': 2, 'spoon': 3, 'kasik': 3,
        'garden': 3, 'bahce': 3, 'door stop': 4, 'door stopper': 4, 'kapi': 1, 'curtain': 3,
        'perde': 3, 'cushion': 4, 'cushions': 4, 'couch': 4, 'sofa': 4, 'koltuk': 3,
        'trash': 2, 'cop': 2, 'clipper': 3, 'razor': 3, 'tiras': 3, 'plant': 2, 'bitki': 2,
        'pet': 2, 'feeder': 3, 'wall mount': 2, 'duvar': 1, 'chair leg': 3, 'lint': 1,
    },
    'decor': {
        'decor': 4, 'decoration': 3, 'decorations': 3, 'dekor': 4, 'dekorasyon': 4,
        'art': 3, 'artdeco': 2, 'art deco': 2, 'shadow': 2, 'shadow art': 5, 'lamp': 4,
        'lamba': 4, 'lampshade': 5, 'abajur': 5, 'lithophane': 5, 'litofan': 5, 'vase': 5,
        'vazo': 5, 'planter': 4, 'saksi': 4, 'pot': 2, 'flower': 3, 'cicek': 3, 'flower box': 5,
        'moon': 3, 'ay lambasi': 5, 'star': 1.5, 'yildiz': 1.5, 'tensegrity': 5, 'wall art': 4,
        'mandala': 4, 'celtic': 2, 'candle': 4, 'mum': 3, 'candle holder': 5, 'tea light': 4,
        'photo frame': 4, 'frame': 2, 'cerceve': 3, 'clock': 3, 'saat': 2, 'voronoi': 3,
        'geometric': 2, 'triacontahedron': 3, 'sculptural': 3, 'ornamental': 3,
        'optical illusion': 5,
    },
}

# Kategori dışı ikincil etiketler.
AUTO_TAG_RULES = [
    ('Print-in-place', ['print in place', 'printinplace', 'print inplace']),
    ('Desteksiz', ['no support', 'no supports', 'nosupport', 'nosupports', 'without supports',
                   'supportless', 'support free', 'desteksiz', 'no supports required']),
    ('Kit kart', ['kit card', 'kitcard', 'gift card']),
    ('Eklemli / Flexi', ['flexi', 'articulated', 'eklemli']),
    ('Çok renkli', ['multicolor', 'multi color', 'multicolour', 'dual color', 'two color',
                    'multi material', 'ams']),
    ('Polly Pocket', ['polly']),
    ('Barbie', ['barbie']),
    ('Pokémon', ['pokemon', 'pikachu']),
    ('Disney', ['moana', 'disney', 'frozen', 'mickey', 'stitch']),
    ('Studio Ghibli', ['calcifer', 'kalcifer', 'totoro', 'ghibli']),
    ('H0 ölçek', ['h0', 'ho scale']),
    ('Eğitici', ['education', 'educational', 'egitici', 'stem']),
]

# Yetişkin içerik işaretleri: bu modeller varsayılan olarak ziyaretçilerden gizlenir.
NSFW_KEYWORDS = [
    'nude', 'nudes', 'naked', 'sexy', 'sex', 'erotic', 'erotica', 'nsfw', 'porn', 'porno', 'xxx',
    'hentai', 'boobs', 'boob', 'tits', 'nipple', 'nipples', 'lingerie', 'fetish', 'bdsm',
    'bondage', 'stripper', 'playboy', 'bombshell', 'onknees', 'on knees', 'mia khalifa',
    'ciplak', 'seksi', 'erotik', 'mustehcen', 'yetiskin', 'adult only', '18 plus',
]
CHILD_BRAND_TAGS = {'Polly Pocket', 'Barbie', 'Pokémon', 'Disney', 'Studio Ghibli'}

GENERIC_DIR_TOKENS = {
    'files', 'file', 'stl', 'stls', '3mf', 'obj', 'step', 'stp', 'models', 'model', 'mesh',
    'meshes', 'parts', 'part', 'print', 'prints', 'printable', 'singles', 'single', 'parametric',
    'updates', 'update', 'updated', 'version', 'versions', 'images', 'image', 'img', 'imgs',
    'pics', 'pictures', 'photos', 'photo', 'renders', 'render', 'source', 'sources', 'cad',
    'gcode', 'plates', 'plate', 'extras', 'extra', 'alt', 'alternative', 'alternatives',
    'optional', 'options', 'supports', 'support', 'remix', 'remixes', 'old', 'new', 'final',
    'assembly', 'assemblies', 'v', 'docs', 'doc', 'documentation', 'instructions', 'original',
    'originals', 'fixed', 'modified', 'mod', 'mods', 'scaled', 'bonus', 'misc', 'variants',
    'variant', 'spare', 'spares', 'and', 'with', 'for', 'the',
}

_FOLD_EXTRA = str.maketrans({'ı': 'i', 'İ': 'i', 'ß': 'ss', 'ø': 'o', 'Ø': 'o', 'æ': 'ae', 'Æ': 'ae',
                             'đ': 'd', 'Đ': 'd', 'ł': 'l', 'Ł': 'l', 'œ': 'oe', 'Œ': 'oe'})
_CAMEL = re.compile(r'(?<=[a-z]{2})(?=[A-Z][a-z])')
_TOKEN = re.compile(r'[a-z0-9]+')


def fold(text):
    """Metni aksanlardan arındırıp küçük harfe çevir (arama ve eşleştirme için)."""
    text = html.unescape(str(text or '')).translate(_FOLD_EXTRA)
    text = unicodedata.normalize('NFKD', text)
    return ''.join(ch for ch in text if not unicodedata.combining(ch)).lower()


def tokenize(text):
    """Dosya/klasör adlarını anlamlı kelimelere böl."""
    raw = html.unescape(str(text or ''))
    raw = _CAMEL.sub(' ', raw)
    folded = fold(raw)
    folded = re.sub(r'(?<=[a-z])v(?=\d)', ' v', folded)
    folded = re.sub(r'\b3d\b', ' 3d ', folded)
    tokens = []
    for token in _TOKEN.findall(folded):
        if token == '3d':
            tokens.append(token)
            continue
        # "anahtarlikv2" → "anahtarlikv", "2"; sayı-harf geçişlerini ayır ama 240z/608/18650 kalsın.
        parts = re.findall(r'[a-z]+|\d+[a-z]?(?![a-z])|\d+', token)
        if len(parts) > 1 and not re.fullmatch(r'\d+[a-z]', token):
            tokens.extend(parts)
            tokens.append(token)
        else:
            tokens.append(token)
    return tokens


class _Matcher:
    """Bir metin için kelime, önek ve öbek eşleşmelerini hızlıca kontrol eder."""

    def __init__(self, text):
        self.tokens = tokenize(text)
        self.token_set = set(self.tokens)
        self.joined = ' ' + ' '.join(self.tokens) + ' '

    def hits(self, keyword):
        if keyword.endswith('*'):
            prefix = keyword[:-1]
            return any(token.startswith(prefix) for token in self.token_set)
        if ' ' in keyword:
            return f' {keyword} ' in self.joined
        return keyword in self.token_set

    def score(self, category):
        return sum(weight for keyword, weight in KEYWORDS.get(category, {}).items() if self.hits(keyword))


def classify(sources):
    """
    Ağırlıklı metin kaynaklarından kategori seç.

    sources: [(metin, ağırlık, üst_sınır_or_None), ...]
    Dönüş: (kategori_anahtarı, {kategori: puan})
    """
    totals = {key: 0.0 for key in KEYWORDS}
    for text, weight, cap in sources:
        if not text:
            continue
        matcher = _Matcher(text)
        if not matcher.tokens:
            continue
        for category in KEYWORDS:
            value = matcher.score(category) * weight
            if cap is not None:
                value = min(value, cap)
            totals[category] += value

    ranked = sorted(totals.items(), key=lambda item: (-item[1], TIE_PRIORITY.index(item[0])))
    best, best_score = ranked[0]
    if best_score < 2.0:
        return OTHER, totals
    return best, totals


def auto_tags(texts, extra=()):
    """Metinlerden kategori dışı yardımcı etiketler üret."""
    matchers = [_Matcher(text) for text in texts if text]
    tags = []
    for tag, keywords in AUTO_TAG_RULES:
        if any(matcher.hits(keyword) for matcher in matchers for keyword in keywords):
            tags.append(tag)
    for tag in extra:
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def is_nsfw(texts):
    """Adlarda yetişkin içerik işareti var mı?"""
    matchers = [_Matcher(text) for text in texts if text]
    return any(matcher.hits(keyword) for matcher in matchers for keyword in NSFW_KEYWORDS)


def is_generic_dir_name(name):
    """'files', 'STL SINGLES', 'V2.5', 'UPDATES' gibi yardımcı klasörleri tanı."""
    tokens = tokenize(name)
    if not tokens:
        return True
    return all(token in GENERIC_DIR_TOKENS or token.isdigit() or re.fullmatch(r'v\d+[a-z]?', token)
               for token in tokens)


def category_payload():
    """API için kategori listesi."""
    return [{'key': key, 'label': label, 'icon': icon} for key, label, icon in CATEGORY_DEFS]
