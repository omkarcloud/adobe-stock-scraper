"""Raw search-API / GraphQL JSON -> clean dicts. Pure functions, no I/O;
every parser tolerates a partial payload.

Fixtures (fixtures/, captured 2026-11-20 from stock.adobe.io and
stock.adobe.com through fetch.py, untrimmed):
  search_*.json          search API pages: a keyword search and its page 2,
                         no result, past the end, one page per kind (video,
                         looping video, vector, icon, illustration,
                         template, motion template, 3D, premium), a
                         category, a series, a portfolio, similar assets
                         (by asset, by picture), German, a count-only call
  search_asset_*.json    the search API's row of one asset (the row that
                         completes assets/details): found, and the cases
                         with no row (unknown id, a template asked for
                         without its type, a track, an editorial-use asset)
  search_error_*.json    the search API's error bodies (unknown contributor,
                         unknown similar id, a picture it cannot read, an
                         unsupported column)
  assets_*.json          GraphQL getAssetDetails answers: one of every kind,
                         free, premium, editorial use, German, a record
                         with one failed field, a batch with an unknown id,
                         none found, a locale the site cannot serve
  graphql_search_*.json  GraphQL getSearchResults answers: audio (plain,
                         filtered, sound effects, no result, a page of 37),
                         the keyword-search fallback, two refused filters
  categories_*.json      the category tree calls; category_*.json one category
  related_*.json, typeahead_*.js   the two suggestion calls

One asset shape for both upstreams (parse_search_row, parse_graphql_asset):
a key the answering upstream does not carry is null. The search API has
the file size, the watermarked previews and the site's stock id; the
GraphQL record has the size ladder (XS ... XXL with dpi and credits), a
video's renditions and everything about a track.

Units (2026-11-20):
  * created_at   the search API prints Paris wall-clock time
                 ("2022-01-19 12:11:26" is 11:11:26 UTC), the GraphQL
                 record epoch seconds as text; both come out as UTC.
  * duration     milliseconds upstream, seconds here.
  * credits      a size's price in the site's credits, not money.
  * premium_level  0 standard, 1 free, 2 and up premium.
"""
import re

from adobe_stock import refs
from scraper_utils.dates import epoch_utc, wall_clock_utc
from scraper_utils.text import clean, text_list
from scraper_utils.values import as_dict, as_list, bool_or_none, count, g, num, number, to_int, to_int_round

SITE_ZONE = "Europe/Paris"      # the clock the search API prints creation dates in

# media_type_id (search API) / assetTypeId (GraphQL) -> the public type
MEDIA_TYPES = {1: "photo", 2: "illustration", 3: "vector", 4: "video", 6: "3d", 7: "template", 9: "audio"}
_GRAPHQL_TYPES = {"image": "photo", "photo": "photo", "illustration": "illustration", "vector": "vector",
                  "video": "video", "template": "template", "3d": "3d", "audio": "audio"}
_GRAPHQL_KINDS = {"ImageMetadata": "photo", "VectorMetadata": "vector", "VideoMetadata": "video",
                  "TemplateMetadata": "template", "MogrtMetadata": "template", "ThreeDMetadata": "3d",
                  "AudioMetadata": "audio"}
_THUMBNAIL_SIZES = (110, 160, 220, 240, 360, 500, 1000)
# A 3D row's kind, read from its content type (the search API's 3d_type_id
# column fails the whole call on a row that is not 3D, so it is not asked):
# application/vnd.adobe.obj.3d+zip, ...ibl.light+zip, ...mdl.material+zip
_THREE_D_MIME_MARKS = ((".obj.3d", "model"), (".ibl.light", "light"), (".mdl.material", "material"))
_HEADING_RE = re.compile(r"^\s*#{1,6}\s*", re.M)
_BULLET_RE = re.compile(r"^\s*\*\s+", re.M)


# ---- small helpers -------------------------------------------------------------------

def _flag(value):
    """True / False as they are, 1 / 0 (the search API's has_releases) as
    booleans; anything else -> None."""
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    return None


def _seconds(milliseconds):
    value = num(milliseconds)
    if value is None or value <= 0:
        return None
    return number(round(value / 1000, 3))


def _text_block(value):
    """A description the site writes in light markdown ("##### Details",
    "* A4 size") -> plain lines: heading marks dropped, bullets as dashes."""
    if not isinstance(value, str):
        return None
    text = _HEADING_RE.sub("", value.replace("\r\n", "\n"))
    text = _BULLET_RE.sub("- ", text)
    lines = [clean(line) for line in text.split("\n")]
    out, blank = [], False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif out and not blank:
            out.append("")
            blank = True
    while out and not out[-1]:
        out.pop()
    return "\n".join(out) or None


def _category(raw):
    raw = as_dict(raw)
    category_id, name = to_int(raw.get("id")), clean(raw.get("name"))
    if category_id is None and name is None:
        return None
    return {"id": category_id, "name": name}


def _category_path(raw):
    return [c for c in (_category(item) for item in as_list(raw)) if c]


def _contributor(contributor_id, name, country):
    contributor_id, name = to_int(contributor_id), clean(name)
    return {
        "id": contributor_id,
        "name": name,
        "country": clean(country),
        "link": refs.contributor_link(contributor_id, name),
    }


def _stats(downloads, views, with_stats):
    if not with_stats:
        return {"downloads": None, "views": None}
    return {"downloads": count(downloads), "views": count(views)}


def _premium(level, is_premium=None):
    level = to_int(level)
    premium = is_premium if isinstance(is_premium, bool) else (level >= 2 if level is not None else None)
    return {
        "is_premium": premium,
        "is_free": (level == 1) if level is not None else None,
        "premium_level": level,
    }


def _empty_asset():
    """Every key of an asset, in order, with nothing in it."""
    return {
        "id": None, "title": None, "link": None, "type": None, "format": None, "mime_type": None,
        "file_extension": None, "description": None, "keywords": [],
        "category": None, "category_path": [],
        "contributor": _contributor(None, None, None),
        "created_at": None,
        "dimensions": {"width": None, "height": None},
        "file_size_bytes": None,
        "stats": {"downloads": None, "views": None},
        "is_ai_generated": None, "ai_prompt": None,
        "is_premium": None, "is_free": None, "premium_level": None,
        "is_editorial": None, "is_editorial_use_only": None, "is_transparent": None,
        "has_releases": None, "is_available_with_subscription": None,
        "thumbnail": None, "thumbnails": [],
        "watermarked_previews": None,
        "sizes": None, "licenses": None,
        "stock_id": None,
        "video": None, "vector_type": None, "icon_type": None, "template": None, "three_d_type": None, "audio": None,
    }


# ---- the search API's row ------------------------------------------------------------

def _row_thumbnails(row):
    thumbs = []
    for size in _THUMBNAIL_SIZES:
        link = clean(row.get(f"thumbnail_{size}_url"))
        if link:
            # the site prints a scaled side as a fraction (360.9022...)
            thumbs.append({"size": size, "link": link, "width": to_int_round(row.get(f"thumbnail_{size}_width")),
                           "height": to_int_round(row.get(f"thumbnail_{size}_height"))})
    return thumbs


def _row_previews(row):
    """The watermarked files anyone may download: an image's comp, a
    video's HD and 4K comps."""
    previews = []
    for name, comp in as_dict(row.get("comps")).items():
        comp = as_dict(comp)
        link = clean(comp.get("url"))
        if link:
            previews.append({"name": clean(name), "link": link, "width": to_int(comp.get("width")),
                             "height": to_int(comp.get("height"))})
    comp = clean(row.get("comp_url"))
    if comp and comp not in [p["link"] for p in previews]:
        previews.append({"name": "Preview", "link": comp, "width": to_int(row.get("comp_width")),
                         "height": to_int(row.get("comp_height"))})
    return previews


def _row_licenses(row):
    """The license kinds the asset is sold under, with the size each one
    delivers (the download itself needs a signed-in, licensed account)."""
    out = []
    for name, lic in as_dict(row.get("licenses")).items():
        lic = as_dict(lic)
        out.append({"name": clean(name), "width": to_int(lic.get("width")), "height": to_int(lic.get("height"))})
    return out


def _row_video(row):
    return {
        "duration_seconds": _seconds(row.get("duration")),
        "frame_rate": number(row.get("framerate")),
        "codec": None,
        "container": None,
        "is_loop": bool_or_none(row.get("is_loop")),
        "preview_link": clean(row.get("video_preview_url")),
        "small_preview_link": clean(row.get("video_small_preview_url")),
        "renditions": [r for r in (
            _rendition("preview", row.get("video_preview_url"), row.get("video_preview_width"),
                       row.get("video_preview_height"), row.get("video_preview_content_length"),
                       mime_type=row.get("video_preview_content_type")),
            _rendition("small_preview", row.get("video_small_preview_url"), row.get("video_small_preview_width"),
                       row.get("video_small_preview_height"), row.get("video_small_preview_content_length"),
                       mime_type=row.get("video_small_preview_content_type")),
        ) if r["link"]],
    }


def _rendition(name, link, width, height, size, bitrate=None, codec=None, mime_type=None):
    return {"name": clean(name), "link": clean(link), "width": to_int(width), "height": to_int(height),
            "size_bytes": to_int(size), "bitrate_kbps": to_int(bitrate), "codec": clean(codec),
            "mime_type": clean(mime_type)}


def _row_template(row):
    type_id = to_int(row.get("template_type_id"))
    return {
        "app": refs.TEMPLATE_APP_NAMES.get(type_id),
        "categories": [{"id": cid, "name": refs.TEMPLATE_CATEGORY_NAMES.get(cid)}
                       for cid in (to_int(c) for c in as_list(row.get("template_category_ids"))) if cid is not None],
        "preview_images": None,
        "preview_videos": None,
    }


def parse_search_row(row, with_stats=True):
    """One row of the search API -> an asset."""
    row = as_dict(row)
    asset = _empty_asset()
    asset_id = to_int(row.get("id"))
    kind = MEDIA_TYPES.get(to_int(row.get("media_type_id")))
    mime = clean(row.get("content_type"))
    asset.update({
        "id": asset_id,
        "title": clean(row.get("title")),
        "link": refs.asset_link(asset_id),
        "type": kind,
        "format": mime.split("/")[-1] if mime and kind in ("photo", "illustration", "video") else None,
        "mime_type": mime,
        "description": _text_block(row.get("description")) or _text_block(row.get("marketing_text")),
        "keywords": text_list([g(k, "name", default=None) for k in as_list(row.get("keywords"))]),
        "category": _category(row.get("category")),
        "category_path": _category_path(row.get("category_hierarchy")),
        "contributor": _contributor(row.get("creator_id"), row.get("creator_name"), row.get("country_name")),
        "created_at": wall_clock_utc(row.get("creation_date"), SITE_ZONE),
        "dimensions": {"width": to_int(row.get("width")), "height": to_int(row.get("height"))},
        "file_size_bytes": to_int(row.get("size_bytes")),
        "stats": _stats(row.get("nb_downloads"), row.get("nb_views"), with_stats),
        "is_ai_generated": bool_or_none(row.get("is_gentech")),
        "ai_prompt": clean(row.get("prompt")),
        **_premium(row.get("premium_level_id"), row.get("is_premium")),
        "is_editorial": bool_or_none(row.get("is_editorial")),
        "is_editorial_use_only": bool_or_none(row.get("is_illustrative")),
        "is_transparent": bool_or_none(row.get("is_transparent")),
        "has_releases": _flag(row.get("has_releases")),
        "thumbnail": clean(row.get("thumbnail_url")) or clean(row.get("thumbnail_500_url")),
        "thumbnails": _row_thumbnails(row),
        "watermarked_previews": _row_previews(row),
        "licenses": _row_licenses(row),
        "stock_id": clean(row.get("stock_id")),
        "vector_type": clean(row.get("vector_type")) if kind == "vector" else None,
        "icon_type": {"single_icon": "single", "icon_sheet": "sheet"}.get(clean(row.get("icon_option"))),
    })
    if kind == "video":
        asset["video"] = _row_video(row)
    elif kind == "template":
        asset["template"] = _row_template(row)
    elif kind == "3d":
        asset["three_d_type"] = next((kind for mark, kind in _THREE_D_MIME_MARKS if mark in (mime or "")), None)
    return asset


def parse_search_page(payload, page, limit, with_stats=True):
    """A search API answer -> {"results", "pagination"}. The total is the
    site's own; the pages stop at the 10,000 results the search reaches."""
    payload = as_dict(payload)
    rows = [parse_search_row(row, with_stats) for row in as_list(payload.get("files"))]
    total = count(payload.get("nb_results")) or 0
    reachable = min(total, refs.MAX_RESULTS)
    return {
        "results": rows,
        "pagination": {"page": page, "items_per_page": limit, "total_count": total,
                       "total_pages": -(-reachable // limit) if reachable else 0},
    }


def empty_page(page, limit, total=0):
    """A page past the end (or past the 10,000 results the search reaches)."""
    reachable = min(total, refs.MAX_RESULTS)
    return {"results": [], "pagination": {"page": page, "items_per_page": limit, "total_count": total,
                                          "total_pages": -(-reachable // limit) if reachable else 0}}


def first_contributor(rows):
    """The contributor of a portfolio's rows (every row carries the same one)."""
    for row in rows:
        if g(row, "contributor", "id", default=None):
            return dict(row["contributor"])
    return None


# ---- the GraphQL record --------------------------------------------------------------

def _graphql_type(meta):
    kind = _GRAPHQL_TYPES.get((clean(meta.get("assetType")) or "").lower())
    typed = _GRAPHQL_KINDS.get(meta.get("__typename"))
    if typed and typed != "photo":
        return typed
    return kind or MEDIA_TYPES.get(to_int(meta.get("assetTypeId"))) or typed


def _graphql_thumbnails(meta):
    thumbs = []
    for size in _THUMBNAIL_SIZES:
        thumb = as_dict(meta.get(f"thumbnail{size}"))
        link = clean(thumb.get("url"))
        if link:
            thumbs.append({"size": size, "link": link, "width": to_int(g(thumb, "dimension", "width", default=None)),
                           "height": to_int(g(thumb, "dimension", "height", default=None))})
    original = clean(meta.get("originalUrl"))           # a template's 400 px thumbnail
    if original and original not in [t["link"] for t in thumbs]:
        thumbs.append({"size": 400, "link": original, "width": None, "height": None})
        thumbs.sort(key=lambda t: t["size"])
    return thumbs


def _graphql_sizes(meta):
    """The sizes the asset is sold in (XS ... XXL for a picture, one entry
    for a video, template, 3D asset or track), with the credits each costs."""
    sizes = []
    for item in as_list(meta.get("licenses")):
        item = as_dict(item)
        sizes.append({
            "name": clean(item.get("name")),
            "width": to_int(g(item, "dimension", "width", default=None)),
            "height": to_int(g(item, "dimension", "height", default=None)),
            "dpi": to_int(item.get("dpi")),
            "credits": number(item.get("price")),
        })
    return sizes


def _graphql_video(meta, unmarked_preview=False):
    """A video's block. The record's `videoUrl` is the 700 px preview
    without the "_ST" mark that the preview file of the site's own page
    carries: it is passed on (as unmarked_preview_link) only when the
    config switch asks for it."""
    renditions = []
    for item in as_list(meta.get("formats")):
        item = as_dict(item)
        renditions.append(_rendition(item.get("formatName"), item.get("url"),
                                     g(item, "dimension", "width", default=None),
                                     g(item, "dimension", "height", default=None), item.get("contentLength"),
                                     item.get("videoBitrateInKbps"), item.get("videoCodec")))
    by_name = {r["name"]: r["link"] for r in renditions if r["link"]}
    return {
        "duration_seconds": _seconds(meta.get("duration")),
        "frame_rate": number(meta.get("framerate")),
        "codec": clean(meta.get("videoCodec")),
        "container": clean(meta.get("format")),
        "is_loop": None,
        "preview_link": by_name.get("700px"),
        "small_preview_link": by_name.get("240px"),
        "renditions": renditions,
        **({"unmarked_preview_link": clean(meta.get("videoUrl"))} if unmarked_preview else {}),
    }


def _graphql_template(meta):
    images = []
    for item in as_list(meta.get("previewImages")):
        item = as_dict(item)
        link = clean(item.get("url"))
        if link:
            images.append({"link": link, "width": to_int(g(item, "dimension", "width", default=None)),
                           "height": to_int(g(item, "dimension", "height", default=None))})
    for link in text_list(as_list(meta.get("thumbnailData"))) or []:
        if link not in [i["link"] for i in images]:
            images.append({"link": link, "width": None, "height": None})
    videos = [{"name": clean(f.get("formatName")), "link": clean(f.get("url"))}
              for f in (as_dict(x) for x in as_list(meta.get("formats"))) if clean(f.get("url"))]
    return {
        "app": clean(meta.get("templateTypeName")),
        "categories": None,
        "preview_images": images,
        "preview_videos": videos,
    }


def _graphql_audio(meta):
    return {
        "artist": clean(meta.get("artistName")),
        "album": clean(meta.get("album")),
        "partner": clean(meta.get("partnerName")),
        "duration_seconds": _seconds(meta.get("durationMilliseconds")),
        "tempo_bpm": to_int(meta.get("tempo")),
        "genres": text_list(as_list(meta.get("genres"))) or [],
        "subgenres": text_list(as_list(meta.get("subgenres"))) or [],
        "moods": text_list(as_list(meta.get("moods"))) or [],
        "is_instrumental": bool_or_none(meta.get("isInstrumental")),
        "is_loop": bool_or_none(meta.get("isLoop")),
        "preview_link": clean(g(meta, "renditionPreview", "metadata", "url", default=None)),
        "waveform_link": clean(g(meta, "waveformData1000", "metadata", "url", default=None)),
    }


def parse_graphql_asset(raw, with_stats=True, unmarked_preview=False):
    """One GraphQL asset ({_id, metadata}) -> an asset; None when the site
    answered the id without a record (a locale it cannot serve, a row
    whose metadata failed)."""
    raw = as_dict(raw)
    meta = raw.get("metadata")
    if not isinstance(meta, dict):
        return None
    asset = _empty_asset()
    asset_id = to_int(raw.get("_id")) or to_int(meta.get("_id"))
    kind = _graphql_type(meta)
    thumbs = _graphql_thumbnails(meta)
    by_size = {t["size"]: t["link"] for t in thumbs}
    asset.update({
        "id": asset_id,
        "title": clean(meta.get("title")),
        "link": refs.asset_link(asset_id),
        "type": kind,
        "format": clean(meta.get("assetFormat")),
        "mime_type": clean(meta.get("mimeType")),
        "file_extension": clean(meta.get("fileExtension")) if meta.get("fileExtension") != "video" else None,
        "description": _text_block(meta.get("description")),
        "keywords": text_list(as_list(meta.get("keywords"))) or [],
        "category": _category(meta.get("category")),
        "category_path": _category_path(meta.get("categoryHierarchy")),
        "contributor": _contributor(g(meta, "contributor", "id", default=None), g(meta, "contributor", "name", default=None),
                                    g(meta, "country", "name", default=None)),
        "created_at": epoch_utc(num(meta.get("creationDate"))),
        "dimensions": {"width": to_int(g(meta, "dimension", "width", default=None)),
                       "height": to_int(g(meta, "dimension", "height", default=None))},
        "stats": _stats(g(meta, "metrics", "downloads", default=None), g(meta, "metrics", "views", default=None), with_stats),
        "is_ai_generated": bool(meta.get("isGentech")) if "isGentech" in meta else None,
        "ai_prompt": clean(meta.get("prompt")),
        **_premium(meta.get("premiumLevelId")),
        "is_editorial": bool_or_none(meta.get("isEditorial")),
        "is_editorial_use_only": bool(meta.get("isIllustrative")) if "isIllustrative" in meta else None,
        "is_transparent": bool(meta.get("isTransparent")) if "isTransparent" in meta else None,
        "has_releases": bool_or_none(meta.get("hasReleases")),
        "is_available_with_subscription": _flag(meta.get("availableForSubscription")),
        "thumbnail": by_size.get(500) or by_size.get(360) or by_size.get(1000) or (thumbs[-1]["link"] if thumbs else None),
        "thumbnails": thumbs,
        "sizes": _graphql_sizes(meta),
        "vector_type": clean(meta.get("vectorType")) if kind == "vector" else None,
    })
    if kind == "video":
        asset["video"] = _graphql_video(meta, unmarked_preview)
    elif kind == "template":
        asset["template"] = _graphql_template(meta)
        if asset["thumbnail"] is None:
            asset["thumbnail"] = clean(meta.get("originalUrl"))
    elif kind == "3d":
        asset["three_d_type"] = (clean(meta.get("threedTypeName")) or "").lower() or None
    elif kind == "audio":
        asset["audio"] = _graphql_audio(meta)
        asset["dimensions"] = {"width": None, "height": None}
        asset["sizes"] = [{**s, "width": None, "height": None, "dpi": None} for s in asset["sizes"]]
    return asset


def parse_graphql_assets(rows, wanted, with_stats=True, unmarked_preview=False):
    """The rows of a details call -> {"assets", "not_found"}: the assets in
    the order asked, and the ids the site does not know."""
    by_id = {}
    for raw in as_list(rows):
        asset = parse_graphql_asset(raw, with_stats, unmarked_preview)
        if asset and asset["id"] is not None:
            by_id[str(asset["id"])] = asset
    wanted = [str(w) for w in wanted]
    return {"assets": [by_id[w] for w in wanted if w in by_id], "not_found": [w for w in wanted if w not in by_id]}


def parse_graphql_search(result, page, limit, with_stats=True, unmarked_preview=False):
    """A getSearchResults object -> {"results", "pagination"}."""
    result = as_dict(result)
    rows = [a for a in (parse_graphql_asset(raw, with_stats, unmarked_preview) for raw in as_list(result.get("assets"))) if a]
    total = count(g(result, "metadata", "numberOfResults", default=0)) or 0
    reachable = min(total, refs.MAX_RESULTS)
    return {
        "results": rows,
        "pagination": {"page": page, "items_per_page": limit, "total_count": total,
                       "total_pages": -(-reachable // limit) if reachable else 0},
    }


def merge_asset(record, row):
    """The GraphQL record of an asset, completed with what only its search
    API row carries: the file size, the watermarked previews, the license
    kinds, the stock id, a video's loop flag, a template's categories."""
    if not row:
        return record
    merged = dict(record)
    for key in ("file_size_bytes", "watermarked_previews", "licenses", "stock_id", "icon_type", "description",
                "category", "ai_prompt"):
        if merged.get(key) is None:
            merged[key] = row.get(key)
    if not merged.get("category_path"):
        merged["category_path"] = row.get("category_path") or []
    if merged.get("video") and row.get("video"):
        merged["video"] = {**merged["video"], "is_loop": row["video"].get("is_loop")}
    if merged.get("template") and row.get("template"):
        merged["template"] = {**merged["template"], "categories": row["template"].get("categories")}
    return merged


# ---- categories ----------------------------------------------------------------------

def parse_category(raw):
    raw = as_dict(raw)
    return {"id": to_int(raw.get("id")), "name": clean(raw.get("name")), "link": refs.category_link(raw.get("link"))}


def parse_categories(payload):
    return [c for c in (parse_category(item) for item in as_list(payload)) if c["id"] is not None]


# ---- suggestions ---------------------------------------------------------------------

def parse_typeahead(payload):
    """The typeahead's hits -> the terms, best first, repeats dropped."""
    return text_list([g(hit, "term", default=None) for hit in as_list(as_dict(payload).get("hits"))]) or []


def parse_related_searches(payload):
    return text_list(as_list(payload)) or []
