"""Reference resolvers, link builders and the choice tables for /adobe-stock/*.

ONE param per input: `asset` accepts an asset id OR any stock.adobe.com
asset link (or one of its preview files on ftcdn.net); `contributor` a
contributor id OR a contributor link; `category` a category id OR a
category link. Resolvers raise ValueError with a user-facing message
(RefField turns it into a 400).

Identifier shapes (stock.adobe.com, 2026-11-20):
  * asset        digits only, one id space for every kind (photo 94143804,
                 video 481358641, template 2244142596, audio 2250132122).
                 The id is the last path segment of an asset link:
                 /images/<slug>/<id>, /video/<slug>/<id>, /<id>, with or
                 without a country prefix (/in/images/...). A preview file
                 carries it too: .../500_F_<id>_<stock id>.jpg.
  * contributor  digits (203434592): /contributor/<id>/<name>. The site's
                 search takes the number only; a name is not a key.
  * category     digits (596): /category/<slug>/<id>. 21 root categories,
                 each with children.

The choice tables hold the public value of every filter next to the token
the site's search takes for it; each one was seen changing an answer on
2026-11-20 (the saved comparisons are in the research folder).
"""
import re
from urllib.parse import parse_qs, quote, urlparse

SITE = "https://stock.adobe.com"
HOSTS = ("stock.adobe.com",)
PREVIEW_HOSTS = ("ftcdn.net",)

ASSET_ID_RE = re.compile(r"^[0-9]{1,12}$")
_PREVIEW_FILE_RE = re.compile(r"_F_([0-9]{1,12})_[A-Za-z0-9]+")      # 500_F_94143804_QFuK...jpg
_AUDIO_FILE_RE = re.compile(r"/(?:48K|1000)_([0-9]{1,12})\.[a-z0-9]+$")   # audios.ftcdn.net/.../48K_2250132122.m4a
_CONTRIBUTOR_PATH_RE = re.compile(r"/contributor/([0-9]{1,12})(?:/|$)")
_CATEGORY_PATH_RE = re.compile(r"/category/(?:[^/]+/)?([0-9]{1,9})/?$")
_TRAILING_ID_RE = re.compile(r"/([0-9]{1,12})/?$")
_HEX_RE = re.compile(r"^[0-9a-f]{6}$")

MAX_BULK_ASSETS = 100       # one details call answered 500 ids in 4.5 s (1.4 MB) on 2026-11-20; 100 keeps an answer near 300 KB
MAX_COLORS = 3              # three colors in one search answered (304 results for red, blue, green)

_ASSET_HELP = ("Must be an Adobe Stock asset id (94143804) or a stock.adobe.com asset link "
               "(https://stock.adobe.com/images/cup-of-coffee-latte-in-coffee-shop/94143804).")
_CONTRIBUTOR_HELP = ("Must be an Adobe Stock contributor id (203434592) or a stock.adobe.com contributor link "
                     "(https://stock.adobe.com/contributor/203434592/chayathon2000).")
_CATEGORY_HELP = ("Must be an Adobe Stock category id (596) or a stock.adobe.com category link "
                  "(https://stock.adobe.com/category/landscapes/596).")


def _parsed_link(value, hosts):
    """A link (or a bare host/path) on one of `hosts` -> its parsed URL;
    None when the value is not a link at all. A link to another site
    raises ValueError."""
    if value.startswith("//"):
        value = "https:" + value
    elif not value.startswith(("http://", "https://")):
        head = value.split("/", 1)[0].lower()
        if "." not in head or "/" not in value:
            return None
        value = "https://" + value
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in hosts):
        raise ValueError("Must be a stock.adobe.com link.")
    return parsed


def resolve_asset(value):
    """Asset id or asset link -> the id, as text."""
    value = (value or "").strip()
    if ASSET_ID_RE.match(value):
        return value.lstrip("0") or "0"
    try:
        parsed = _parsed_link(value, HOSTS + PREVIEW_HOSTS)
    except ValueError:
        raise ValueError(_ASSET_HELP)
    if parsed is None:
        raise ValueError(_ASSET_HELP)
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    if host.endswith("ftcdn.net"):
        match = _PREVIEW_FILE_RE.search(path) or _AUDIO_FILE_RE.search(path)
        if match:
            return match.group(1)
        raise ValueError(_ASSET_HELP)
    if _CONTRIBUTOR_PATH_RE.search(path) or "/category/" in path:
        raise ValueError(_ASSET_HELP)
    query = parse_qs(parsed.query)
    for key in ("asset_id", "similar_content_id"):
        picked = (query.get(key) or [""])[0]
        if ASSET_ID_RE.match(picked):
            return picked
    match = _TRAILING_ID_RE.search(path)
    if match:
        return match.group(1)
    raise ValueError(_ASSET_HELP)


def resolve_assets(value):
    """'94143804, 841165203, <link>' -> the ids in the order given, repeats
    dropped. At most MAX_BULK_ASSETS."""
    ids = []
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item:
            continue
        asset = resolve_asset(item)
        if asset not in ids:
            ids.append(asset)
    if not ids:
        raise ValueError(_ASSET_HELP)
    if len(ids) > MAX_BULK_ASSETS:
        raise ValueError(f"At most {MAX_BULK_ASSETS} assets per call.")
    return ids


def resolve_contributor(value):
    """Contributor id or contributor link -> the id, as text. A name alone
    is refused: the site's search would ignore it and answer the whole
    catalog."""
    value = (value or "").strip()
    if ASSET_ID_RE.match(value):
        return value.lstrip("0") or "0"
    try:
        parsed = _parsed_link(value, HOSTS)
    except ValueError:
        raise ValueError(_CONTRIBUTOR_HELP)
    if parsed is None:
        raise ValueError(_CONTRIBUTOR_HELP)
    match = _CONTRIBUTOR_PATH_RE.search(parsed.path or "")
    if match:
        return match.group(1)
    picked = (parse_qs(parsed.query).get("creator_id") or [""])[0]
    if ASSET_ID_RE.match(picked):
        return picked
    raise ValueError(_CONTRIBUTOR_HELP)


def resolve_category(value):
    """Category id or category link -> the id, as text."""
    value = (value or "").strip()
    if re.match(r"^[0-9]{1,9}$", value):
        return value.lstrip("0") or "0"
    try:
        parsed = _parsed_link(value, HOSTS)
    except ValueError:
        raise ValueError(_CATEGORY_HELP)
    if parsed is None:
        raise ValueError(_CATEGORY_HELP)
    match = _CATEGORY_PATH_RE.search(parsed.path or "")
    if match:
        return match.group(1)
    raise ValueError(_CATEGORY_HELP)


def resolve_colors(value):
    """'ff0000, #0000FF' -> ['ff0000', '0000ff'] (at most MAX_COLORS)."""
    colors = []
    for raw in str(value or "").split(","):
        item = raw.strip().lstrip("#").lower()
        if not item:
            continue
        if not _HEX_RE.match(item):
            raise ValueError("Each color must be a 6-digit hex code (ff0000 or #ff0000).")
        if item not in colors:
            colors.append(item)
    if not colors:
        raise ValueError("Each color must be a 6-digit hex code (ff0000 or #ff0000).")
    if len(colors) > MAX_COLORS:
        raise ValueError(f"At most {MAX_COLORS} colors.")
    return colors


# ---- links -------------------------------------------------------------------

def asset_link(asset_id):
    """The asset's page. The site redirects the bare id to the full page
    (/images/<slug>/<id>, /video/<slug>/<id>...)."""
    return f"{SITE}/{asset_id}" if asset_id else None


def contributor_link(contributor_id, name=None):
    """A contributor's portfolio page. The site serves /contributor/<id>/<any text>
    and answers 404 without the last segment (2026-11-20), so the name is
    written as a plain slug."""
    if not contributor_id:
        return None
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name or "").strip("-") or "portfolio"
    return f"{SITE}/contributor/{contributor_id}/{slug}"


def category_link(href):
    """A category path the site returns ("/category/animals/1?load_type=category")
    -> the absolute link without its tracking parameter."""
    if not href or not isinstance(href, str):
        return None
    path = href.split("?", 1)[0].strip()
    if not path.startswith("/"):
        return None
    return SITE + quote(path, safe="/-._~")


# ---- locales -----------------------------------------------------------------

# The locales in which BOTH upstreams translate an asset's keywords, its
# category and its contributor's country (each checked on asset 94143804,
# 2026-11-20). The site has more; in those the details call answers no
# record at all (en_GB, zh_CN) or only half a translation.
LOCALES = ("en_US", "de_DE", "fr_FR", "es_ES", "it_IT", "pt_BR", "pt_PT", "nl_NL", "ja_JP", "ko_KR",
           "pl_PL", "ru_RU", "sv_SE")
DEFAULT_LOCALE = "en_US"
_LOCALE_BY_LOWER = {loc.lower(): loc for loc in LOCALES}
_LOCALE_BY_LANGUAGE = {}
for _loc in LOCALES:
    _LOCALE_BY_LANGUAGE.setdefault(_loc.split("_")[0], _loc)


def resolve_locale(value):
    """'de_DE' / 'de-de' / 'de' -> 'de_DE'. Unknown -> ValueError listing the locales."""
    value = (value or "").strip().replace("-", "_").lower()
    locale = _LOCALE_BY_LOWER.get(value) or _LOCALE_BY_LANGUAGE.get(value)
    if locale is None:
        raise ValueError("Must be one of: " + ", ".join(LOCALES) + ".")
    return locale


# ---- choice tables: assets ---------------------------------------------------

# public type -> the search's content_type filter. A search without a type
# answers photos, illustrations, vectors and videos; templates and 3D come
# only when asked for.
TYPES = {
    "photo": "photo",
    "illustration": "illustration",
    "vector": "vector",
    "video": "video",
    "template": "template",
    "3d": "3d",
}

# public sort -> the search's `order`
SORTS = {
    "relevance": "relevance",
    "newest": "creation",
    "downloads": "nb_downloads",
    "popularity": "popularity",
    "undiscovered": "undiscovered",
}

ORIENTATIONS = ("horizontal", "vertical", "square", "panoramic")

# public value -> the filter's token ("true" / "false")
ONLY_OR_EXCLUDE = {"only": "true", "exclude": "false"}
WITH_OR_WITHOUT = {"with": "true", "without": "false"}

ICON_TYPES = {"single": "single_icon", "sheet": "icon_sheet"}

# public value -> the search's `age` token (added within the last week ... two years)
ADDED_WITHIN = {"1w": "1w", "1m": "1m", "6m": "6m", "1y": "1y", "2y": "2y"}

# public value -> the search's video_duration token (seconds; "30-" = longer than 30)
VIDEO_DURATIONS = {"up_to_10": "10", "up_to_20": "20", "up_to_30": "30", "over_30": "30-"}

# public app -> template_type_id (each id answered only rows of that kind on
# 2026-11-20: 193,088 / 92,897 / 77,888 / 2,519 / 38,552 / 425 templates)
TEMPLATE_APPS = {
    "photoshop": 1,
    "illustrator": 2,
    "indesign": 3,
    "after_effects": 5,
    "premiere_pro": 6,
    "premiere_rush": 7,
}
TEMPLATE_APP_NAMES = {1: "Photoshop", 2: "Illustrator", 3: "InDesign", 5: "After Effects", 6: "Premiere Pro",
                      7: "Premiere Rush"}

# public category -> template_category_id (the site's own filter list)
TEMPLATE_CATEGORIES = {
    "mobile": 1,
    "web": 2,
    "print": 3,
    "photo": 4,
    "film_video": 5,
    "art_illustration": 6,
    "lower_thirds": 7,
    "titles": 8,
    "transitions": 9,
    "backgrounds": 10,
    "infographics": 11,
    "social_media": 12,
}
TEMPLATE_CATEGORY_NAMES = {1: "Mobile", 2: "Web", 3: "Print", 4: "Photo", 5: "Film & Video", 6: "Art & Illustration",
                           7: "Lower Thirds", 8: "Titles/Text Overlays", 9: "Transitions", 10: "Backgrounds",
                           11: "Infographics", 12: "Social Media"}

# public 3D kind -> 3d_type_id (15,220 models, 565 lights, 1,159 materials)
THREE_D_TYPES = {"model": 1, "light": 2, "material": 3}
THREE_D_TYPE_NAMES = {1: "Model", 2: "Light", 3: "Material"}

# The site's search reaches the first 10,000 results of any query; asked
# for more it answers the last window again.
MAX_RESULTS = 10000
MAX_LIMIT = 100             # a larger page is cut to 100 rows by the search, refused by the details call


# ---- choice tables: audio ----------------------------------------------------

AUDIO_TYPES = {"music": "music", "sfx": "sfx"}

AUDIO_SORTS = {
    "relevance": "RELEVANCE",
    "newest": "CREATION",
    "downloads": "DOWNLOADS",
    "popularity": "POPULARITY",
    "undiscovered": "UNDISCOVERED",
}

VOCALS = {"with": "has-vocals", "without": "no-vocals"}

# The genres with their subgenres and the moods the audio search accepts,
# as its own validation message lists them (2026-11-20: 20 genres, 117
# subgenres, 30 moods).
GENRES = {
    "Acoustic": ("Folk", "Solo"),
    "Background": ("Ambient", "Drones", "Muzak", "New Age"),
    "Blues": ("Modern Blues", "Traditional Blues"),
    "Brass": ("Marching Band",),
    "Classical": ("Baroque", "Chamber Music", "Classical Period", "Modern Classical", "Medieval", "Opera",
                  "Orchestral", "Original", "Renaissance", "Romantic"),
    "Country": ("Alternative Country", "Modern Country", "Traditional Country"),
    "Dance": ("Breakbeat", "Disco", "Dubstep", "House", "Traditional Dance"),
    "Electronic": ("Industrial", "Rave", "Techno", "Trance"),
    "Film": ("Film",),
    "Hip-Hop": ("Crunk", "Gangsta", "Old School", "Rap", "Trap"),
    "Jazz": ("Acid", "Bebop", "Big Band", "Fusion", "Modern Jazz", "Ragtime", "Smooth", "Swing", "Traditional Jazz"),
    "Latin": ("Cha Cha", "Flamenco", "Mambo", "Merengue", "Rumba", "Salsa", "Samba", "Tango", "Tejano"),
    "Novelty": ("Cartoon", "Children", "Circus", "Comedy"),
    "Occasion": ("Birthday", "Funeral", "Holiday", "Wedding"),
    "Pop": ("Britpop", "Bubblegum", "Electropop", "Europop", "Pop Punk", "Synth Pop"),
    "Reggae": ("Dancehall", "Roots", "Ska"),
    "Religious": ("Christian", "Gospel"),
    "R&B": ("Contemporary", "Doo Wop", "Funk", "Motown", "Soul"),
    "Rock": ("Alternative Rock", "Classic", "Grunge", "Indie", "Metal", "Punk", "Soft", "Southern", "Surf"),
    "World": ("African", "Asian", "Australian", "Balkan", "Bollywood", "Cajun", "Calypso", "Celtic", "Chinese",
              "Cuban", "French", "European", "German", "Hawaiian", "Indian", "Irish", "Island", "Italian",
              "Japanese", "Klezmer", "Korean", "Mexican", "Middle Eastern", "Native American", "Norwegian",
              "Portuguese", "Russian", "Scandinavian", "Spanish"),
}

MOODS = ("Angry", "Atmospheric", "Dramatic", "Dreamy", "Dynamic", "Emotional", "Epic", "Exotic", "Festive",
         "Frantic", "Gritty", "Groovy", "Happy", "Inspiring", "Mellow", "Mysterious", "Neutral", "Nostalgic",
         "Playful", "Powerful", "Quirky", "Relaxing", "Romantic", "Sad", "Scary", "Space Age", "Sexy", "Slow",
         "Sparse", "Suspenseful")

MAX_GENRES = 10
MAX_MOODS = 10
MIN_TEMPO, MAX_TEMPO = 1, 300                   # the audio search's own tempo range, beats per minute
MAX_AUDIO_SECONDS = 1200                        # and its duration range: 0 to 20 minutes


def _key(text):
    """'Hip-Hop' / 'hip hop' / 'R&B' -> a lookup key."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


_GENRE_BY_KEY = {}
for _genre, _subs in GENRES.items():
    _GENRE_BY_KEY[_key(_genre)] = _genre
    for _sub in _subs:
        _GENRE_BY_KEY[_key(_genre) + "/" + _key(_sub)] = f"{_genre}|{_sub}"
_MOOD_BY_KEY = {_key(m): m for m in MOODS}


def resolve_genres(value):
    """'jazz, Rock/Indie, hip hop' -> ['Jazz', 'Rock|Indie', 'Hip-Hop']: a
    genre by its name, a subgenre as Genre/Subgenre."""
    picked = []
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item:
            continue
        genre, sep, sub = item.replace("|", "/").partition("/")
        token = _GENRE_BY_KEY.get(_key(genre) + ("/" + _key(sub) if sep else ""))
        if token is None:
            raise ValueError(f"'{item}' is not a genre. Use one of: {', '.join(GENRES)}; "
                             "a subgenre is written Genre/Subgenre (Jazz/Swing).")
        if token not in picked:
            picked.append(token)
    if not picked:
        raise ValueError(f"Use one of: {', '.join(GENRES)}.")
    if len(picked) > MAX_GENRES:
        raise ValueError(f"At most {MAX_GENRES} genres.")
    return picked


def resolve_moods(value):
    """'happy, space age' -> ['Happy', 'Space Age']."""
    picked = []
    for raw in str(value or "").split(","):
        item = raw.strip()
        if not item:
            continue
        mood = _MOOD_BY_KEY.get(_key(item))
        if mood is None:
            raise ValueError(f"'{item}' is not a mood. Use one of: {', '.join(MOODS)}.")
        if mood not in picked:
            picked.append(mood)
    if not picked:
        raise ValueError(f"Use one of: {', '.join(MOODS)}.")
    if len(picked) > MAX_MOODS:
        raise ValueError(f"At most {MAX_MOODS} moods.")
    return picked
