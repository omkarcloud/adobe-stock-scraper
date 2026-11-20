"""The /adobe-stock/* endpoint functions (route_glue's route_table calls
them with the schema's loaded kwargs).

Which upstream answers what (fetch.py):

  assets/search, assets/similar, contributors/assets, categories/list
      the search API. A keyword search it fails on is asked from the
      site's own GraphQL search instead, when the request uses only what
      that search has (config.ADOBE_STOCK_GRAPHQL_FALLBACK).
  assets/details, assets/bulk
      the GraphQL details call (every kind of asset, many ids in one
      call). assets/details adds the asset's search API row to it (file
      size, watermarked previews, license kinds, stock id), and either
      upstream alone still answers the asset.
  audio/search
      the GraphQL search (the search API has no audio).
  assets/suggestions
      the search box's typeahead plus the search page's related searches.

A page is answered from inside the 10,000 results the site's search
reaches: a page past them (or past the end) is an empty page with the
total, never the site's repeated last window.

Caching (cache.cached_call) sits here, keyed on the validated params.
"""
import config
from adobe_stock import cache_config as ttl
from adobe_stock import parsers, queries, refs
from adobe_stock.fetch import (AdobeStockNotFound, AdobeStockUpstreamError, fetch_assets, fetch_category,
                               fetch_category_children, fetch_graphql_search, fetch_related_searches, fetch_search,
                               fetch_typeahead)
from cache import cached_call
from scraper_utils import fanout, pictures

_SORT_NAMES = {token: name for name, token in refs.SORTS.items()}
_AUDIO_SORT_NAMES = {token: name for name, token in refs.AUDIO_SORTS.items()}
_AUDIO_TYPE_NAMES = {token: name for name, token in refs.AUDIO_TYPES.items()}
_VOCALS_NAMES = {token: name for name, token in refs.VOCALS.items()}
_COUNT_COLUMNS = ("nb_results", "id")

_UNKNOWN_CONTRIBUTOR = ("Invalid creator_id",)
_UNKNOWN_SIMILAR = ("not supported contentId",)
SIMILAR_IMAGE_MAX_BYTES = 10 * 1024 * 1024      # the picture is downloaded only to explain a refusal


def _with_stats():
    return bool(config.ADOBE_STOCK_SHOW_STATS)


def _unmarked():
    return bool(config.ADOBE_STOCK_UNMARKED_VIDEO_PREVIEW)


# ---- listings (the search API) -------------------------------------------------------

def _total(request, locale, label, not_found):
    """How many results a request has (one row asked, no columns but the id)."""
    payload = fetch_search(queries.search_params(request, 0, 1, locale, _COUNT_COLUMNS), label, not_found)
    return parsers.parse_search_page(payload, 1, 1)["pagination"]["total_count"]


def _graphql_page(request, page, limit, locale):
    """The same page from the site's own search, or None when the request
    uses something only the search API has."""
    filters = queries.graphql_search_filters(request)
    if filters is None:
        return None
    sort = queries.graphql_sort(request.get("sort"))
    referer = f"{refs.SITE}/search"
    offset, rows = queries.window(page, limit)
    if rows == 0:
        total = parsers.parse_graphql_search(fetch_graphql_search(filters, 1, 1, sort, locale, referer), 1, 1)
        return parsers.empty_page(page, limit, total["pagination"]["total_count"])
    listing = parsers.parse_graphql_search(fetch_graphql_search(filters, page, limit, sort, locale, referer),
                                           page, limit, _with_stats(), _unmarked())
    if offset >= listing["pagination"]["total_count"]:
        listing["results"] = []             # past the end the site repeats its last window
    listing["results"] = listing["results"][:rows]
    return listing


def _listing(request, page, limit, locale, label, not_found=()):
    """One page of a search API listing -> {"results", "pagination"}."""
    request = {**request, "types": queries.implied_types(request)}
    offset, rows = queries.window(page, limit)
    try:
        if rows == 0:
            return parsers.empty_page(page, limit, _total(request, locale, label, not_found))
        payload = fetch_search(queries.search_params(request, offset, rows, locale), label, not_found)
        listing = parsers.parse_search_page(payload, page, limit, _with_stats())
        if offset >= listing["pagination"]["total_count"]:
            listing["results"] = []         # past the end the site repeats its last rows
        return listing
    except AdobeStockUpstreamError as e:
        if not config.ADOBE_STOCK_GRAPHQL_FALLBACK:
            raise
        listing = _graphql_page(request, page, limit, locale)
        if listing is None:
            raise
        print(f"adobe-stock: {label} answered by the site's own search after the search API failed: "
              f"{type(e).__name__}: {e}")
        return listing


def _types_echo(data):
    return list(data.get("type") or [])


def _assets_search(**data):
    request = {
        "query": data.get("query"), "types": data.get("type"), "sort": data.get("sort"),
        "orientation": data.get("orientation"), "premium": data.get("premium"), "ai": data.get("ai"),
        "releases": data.get("releases"), "isolated": data.get("isolated"), "transparent": data.get("transparent"),
        "copy_space": data.get("copy_space"), "loop": data.get("loop"), "icon": data.get("icon"),
        "colors": data.get("colors"), "min_megapixels": data.get("min_megapixels"),
        "max_megapixels": data.get("max_megapixels"), "min_width": data.get("min_width"),
        "max_width": data.get("max_width"), "min_height": data.get("min_height"), "max_height": data.get("max_height"),
        "added_within": data.get("added_within"), "video_duration": data.get("video_duration"),
        "template_apps": data.get("template_app"), "template_category": data.get("template_category"),
        "three_d_type": data.get("three_d_type"), "category": data.get("category"), "series": data.get("series"),
    }
    locale = data["locale"]
    listing = _listing(request, data["page"], data["limit"], locale, f"search {data.get('query')!r}",
                       not_found=_UNKNOWN_SIMILAR)
    return {
        "query": data.get("query"),
        "type": queries.implied_types(request),
        "sort": _SORT_NAMES.get(data.get("sort") or "relevance", "relevance"),
        "locale": locale,
        **listing,
    }


def assets_search(**data):
    return cached_call("adobe_stock.search", data, _assets_search, ttl.LISTING_CACHE)


def _picture_problem(link):
    """Why a picture link cannot be searched by, or None when we can read it ourselves."""
    try:
        pictures.download(link, max_bytes=SIMILAR_IMAGE_MAX_BYTES)
    except pictures.PictureError as e:
        return str(e)
    except Exception as e:
        return f"the picture could not be downloaded ({type(e).__name__})"
    return None


def _assets_similar(**data):
    asset, image, locale = data.get("asset"), data.get("image"), data["locale"]
    request = {"similar": asset, "similar_image": image, "types": data.get("type")}
    if asset:
        listing = _listing(request, data["page"], data["limit"], locale, f"asset {asset}", not_found=_UNKNOWN_SIMILAR)
    else:
        try:
            listing = _listing(request, data["page"], data["limit"], locale, "the picture")
        except AdobeStockUpstreamError:
            # the site answers "Internal Server Error" for a link it cannot
            # read as a picture: say so when we cannot read it either
            problem = _picture_problem(image)
            if problem:
                raise ValueError(problem if problem.startswith("image") else f"image: {problem}")
            raise
    return {
        "asset": int(asset) if asset else None,
        "asset_link": refs.asset_link(asset) if asset else None,
        "image": image,
        "type": _types_echo(data),
        "locale": locale,
        **listing,
    }


def assets_similar(**data):
    return cached_call("adobe_stock.similar", data, _assets_similar, ttl.LISTING_CACHE)


# ---- contributors --------------------------------------------------------------------

def _fetch_contributor(contributor, locale):
    """A contributor's id, name and country, read from the first asset of
    the portfolio. Unknown id -> NotFound."""
    payload = fetch_search(queries.search_params({"contributor": contributor}, 0, 1, locale),
                           f"contributor {contributor}", _UNKNOWN_CONTRIBUTOR)
    rows = parsers.parse_search_page(payload, 1, 1)["results"]
    return parsers.first_contributor(rows) or {"id": int(contributor), "name": None, "country": None,
                                               "link": refs.contributor_link(contributor)}


def _contributor(contributor, locale):
    return cached_call("adobe_stock.contributor", {"contributor": contributor, "locale": locale},
                       _fetch_contributor, ttl.CONTRIBUTOR_CACHE)


def _contributors_assets(**data):
    contributor, locale = data["contributor"], data["locale"]
    request = {"contributor": contributor, "query": data.get("query"), "types": data.get("type"),
               "sort": data.get("sort")}
    listing = _listing(request, data["page"], data["limit"], locale, f"contributor {contributor}",
                       not_found=_UNKNOWN_CONTRIBUTOR)
    return {
        "contributor": parsers.first_contributor(listing["results"]) or _contributor(contributor, locale),
        "query": data.get("query"),
        "type": _types_echo(data),
        "sort": _SORT_NAMES.get(data.get("sort") or "relevance", "relevance"),
        "locale": locale,
        **listing,
    }


def contributors_assets(**data):
    return cached_call("adobe_stock.contributor_assets", data, _contributors_assets, ttl.LISTING_CACHE)


# ---- assets/details, assets/bulk -----------------------------------------------------

def _search_api_row(asset, locale):
    """One asset's row from the search API, or None (an unknown id, a track)."""
    payload = fetch_search(queries.search_params({"asset": asset, "types": queries.ALL_TYPES}, 0, 1, locale),
                           f"asset {asset}")
    rows = parsers.parse_search_page(payload, 1, 1, _with_stats())["results"]
    return rows[0] if rows and str(rows[0]["id"]) == str(asset) else None


def _asset_details(asset, locale):
    """The GraphQL record, completed with the asset's search API row (file
    size, watermarked previews, license kinds, stock id). Either upstream
    alone still answers the asset; both failing fails the call."""
    record, failure = None, None
    try:
        rows = fetch_assets([asset], locale)
        record = (parsers.parse_graphql_assets(rows, [asset], _with_stats(), _unmarked())["assets"] or [None])[0]
        if record is None and not rows:
            raise AdobeStockNotFound(f"asset {asset} not found")
    except AdobeStockUpstreamError as e:
        failure = e
    if record is not None and record["type"] == "audio":
        return record                       # a track has no row in the search API
    if not config.ADOBE_STOCK_DETAILS_SEARCH_API_ROW:
        if record is None:
            raise failure or AdobeStockUpstreamError(f"asset {asset} answered no record")
        return record
    try:
        row = _search_api_row(asset, locale)
    except AdobeStockUpstreamError as e:
        if record is None:
            raise failure or e
        print(f"adobe-stock: asset {asset} answered without its search API row: {type(e).__name__}: {e}")
        return record
    if record is None:
        if row is None:
            if failure is not None:
                raise failure
            raise AdobeStockNotFound(f"asset {asset} not found")
        print(f"adobe-stock: asset {asset} read from the search API alone: {failure or 'no record in the details call'}")
        return row
    return parsers.merge_asset(record, row)


def assets_details(**data):
    return cached_call("adobe_stock.details", data, _asset_details, ttl.ASSET_CACHE)


def _assets_bulk(assets, locale):
    parsed = parsers.parse_graphql_assets(fetch_assets(assets, locale), assets, _with_stats(), _unmarked())
    return {
        "locale": locale,
        "requested_count": len(assets),
        "found_count": len(parsed["assets"]),
        "not_found": [int(a) for a in parsed["not_found"]],
        "assets": parsed["assets"],
    }


def assets_bulk(**data):
    return cached_call("adobe_stock.bulk", data, _assets_bulk, ttl.ASSET_CACHE)


# ---- categories/list -----------------------------------------------------------------

def _categories_list(parent, locale):
    record = parsers.parse_category(fetch_category(parent, locale)) if parent else None
    categories = parsers.parse_categories(fetch_category_children(parent, locale))
    return {"parent": record, "locale": locale, "count": len(categories), "categories": categories}


def categories_list(**data):
    return cached_call("adobe_stock.categories", data, _categories_list, ttl.CATEGORIES_CACHE)


# ---- audio/search --------------------------------------------------------------------

def _audio_search(**data):
    page, limit, locale = data["page"], data["limit"], data["locale"]
    filters = queries.audio_filters(data)
    sort = data.get("sort") or "RELEVANCE"
    referer = f"{refs.SITE}/search/audio"
    _, rows = queries.window(page, limit)
    if rows == 0:
        total = parsers.parse_graphql_search(fetch_graphql_search(filters, 1, 1, sort, locale, referer), 1, 1)
        listing = parsers.empty_page(page, limit, total["pagination"]["total_count"])
    else:
        listing = parsers.parse_graphql_search(fetch_graphql_search(filters, page, limit, sort, locale, referer),
                                               page, limit, _with_stats())
        if (page - 1) * limit >= listing["pagination"]["total_count"]:
            listing["results"] = []
        listing["results"] = listing["results"][:rows]
    return {
        "query": data.get("query"),
        "type": _AUDIO_TYPE_NAMES.get(data.get("type")),
        "genres": [g.replace("|", "/") for g in data.get("genres") or []],
        "moods": list(data.get("moods") or []),
        "vocals": _VOCALS_NAMES.get(data.get("vocals")),
        "sort": _AUDIO_SORT_NAMES.get(sort, "relevance"),
        "locale": locale,
        **listing,
    }


def audio_search(**data):
    return cached_call("adobe_stock.audio", data, _audio_search, ttl.LISTING_CACHE)


# ---- assets/suggestions --------------------------------------------------------------

def _assets_suggestions(query):
    suggestions = parsers.parse_typeahead(fetch_typeahead(query))
    # the related searches only add to the answer: when their call fails
    # the typeahead is answered without them
    related = fanout.soft(lambda: parsers.parse_related_searches(fetch_related_searches(query)), [],
                          (AdobeStockUpstreamError,))()
    return {"query": query, "count": len(suggestions), "suggestions": suggestions, "related_searches": related}


def assets_suggestions(**data):
    return cached_call("adobe_stock.suggestions", data, _assets_suggestions, ttl.SUGGESTIONS_CACHE)
