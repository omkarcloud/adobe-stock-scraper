"""What is sent to the two upstreams, built from the validated request
(pure functions, no I/O).

  * the search API   stock.adobe.io/Rest/Media/1/Search/Files: a query
                     string of search_parameters[...] and result_columns[]
  * the GraphQL API  stock.adobe.com/graphql: the documents below, with
                     their `SearchInput` filters

The GraphQL field list (2026-11-20). The server has introspection off; the
fields were mapped from its validation errors, one type at a time. Two
fields are left out on purpose:
  * Asset.isLicensable   answers "Required param contentId is missing"
                         for a visitor who is not signed in;
  * metadata.id          a template or audio row answers "Internal server
                         error" on it and loses its whole metadata. `_id`
                         carries the same value.
"""
from adobe_stock import refs

# ---- the search API ------------------------------------------------------------------

# Every column the search API answers for every kind of asset (an unknown
# one is refused by name: "Unsupported result columns"). Left out:
# thumbnail_html_tag, the thumbnail link wrapped in an <img> tag, and the
# columns that exist for one kind only and fail the whole call on a row of
# another kind (3d_type_id: HTTP 500 "No property available" on a photo).
RESULT_COLUMNS = (
    "nb_results", "id", "title", "creator_name", "creator_id", "country_name", "width", "height",
    "thumbnail_url", "thumbnail_width", "thumbnail_height",
    "thumbnail_110_url", "thumbnail_110_width", "thumbnail_110_height",
    "thumbnail_160_url", "thumbnail_160_width", "thumbnail_160_height",
    "thumbnail_220_url", "thumbnail_220_width", "thumbnail_220_height",
    "thumbnail_240_url", "thumbnail_240_width", "thumbnail_240_height",
    "thumbnail_500_url", "thumbnail_500_width", "thumbnail_500_height",
    "thumbnail_1000_url", "thumbnail_1000_width", "thumbnail_1000_height",
    "media_type_id", "category", "category_hierarchy", "nb_views", "nb_downloads", "creation_date", "keywords",
    "has_releases", "comp_url", "comp_width", "comp_height", "vector_type", "content_type", "framerate",
    "duration", "comps", "template_type_id", "template_category_ids", "marketing_text", "description",
    "size_bytes", "premium_level_id", "is_premium", "licenses",
    "video_preview_url", "video_preview_width", "video_preview_height", "video_preview_content_length",
    "video_preview_content_type", "video_small_preview_url", "video_small_preview_width",
    "video_small_preview_height", "video_small_preview_content_length", "video_small_preview_content_type",
    "is_gentech", "is_loop", "is_transparent", "is_editorial", "stock_id", "is_illustrative",
    "prompt", "icon_option",
)


def _span(low, high):
    """(25, None) -> '25-', (None, 2) -> '-2', (5, 10) -> '5-10', (None, None) -> None."""
    if low is None and high is None:
        return None
    return f"{_number(low)}-{_number(high)}"


def _number(value):
    if value is None:
        return ""
    return str(int(value)) if float(value) == int(value) else str(value)


def window(page, limit):
    """(offset, rows) of a page inside the 10,000 results the search
    reaches; rows is 0 for a page past them (the search would answer its
    last window again)."""
    offset = (page - 1) * limit
    if offset >= refs.MAX_RESULTS:
        return offset, 0
    return offset, min(limit, refs.MAX_RESULTS - offset)


def search_params(data, offset=0, limit=refs.MAX_LIMIT, locale=refs.DEFAULT_LOCALE, columns=RESULT_COLUMNS):
    """The validated request -> the search API's query pairs. `data` may
    carry: query, types, sort, orientation, premium, ai, releases,
    isolated, transparent, copy_space, loop, icon, colors, the megapixel /
    width / height bounds, added_within, video_duration, template_apps,
    template_category, three_d_type, category, series, contributor,
    similar, similar_image, asset."""
    pairs = [("locale", locale)]

    def param(name, value):
        if value is not None:
            pairs.append((f"search_parameters[{name}]", value))

    def flt(name, value):
        if value is not None:
            pairs.append((f"search_parameters[filters][{name}]", value))

    param("words", data.get("query"))
    param("creator_id", data.get("contributor"))
    param("similar", data.get("similar"))
    param("similar_url", data.get("similar_image"))
    param("media_id", data.get("asset"))
    param("category", data.get("category"))
    param("serie_id", data.get("series"))
    param("limit", limit)
    if offset:
        param("offset", offset)
    sort = data.get("sort")
    if sort and sort != "relevance":
        param("order", sort)

    for kind in data.get("types") or ():
        flt(f"content_type:{kind}", 1)
    flt("orientation", data.get("orientation"))
    flt("premium", data.get("premium"))
    flt("gentech", data.get("ai"))
    flt("has_releases", data.get("releases"))
    if data.get("isolated"):
        flt("isolated:on", 1)
    if data.get("transparent"):
        flt("transparent", "true")
    if data.get("copy_space"):
        flt("copy_space", 1)
    if data.get("loop"):
        flt("is_loop", 1)
    flt("icon_option", data.get("icon"))
    if data.get("colors"):
        flt("colors", ",".join(data["colors"]))
    flt("area_m_pixels", _span(data.get("min_megapixels"), data.get("max_megapixels")))
    flt("image_width", _span(data.get("min_width"), data.get("max_width")))
    flt("image_height", _span(data.get("min_height"), data.get("max_height")))
    flt("age", data.get("added_within"))
    flt("video_duration", data.get("video_duration"))
    for app in data.get("template_apps") or ():
        pairs.append(("search_parameters[filters][template_type_id][]", app))
    if data.get("template_category"):
        pairs.append(("search_parameters[filters][template_category_id][]", data["template_category"]))
    if data.get("three_d_type"):
        pairs.append(("search_parameters[filters][3d_type_id][]", data["three_d_type"]))

    pairs += [("result_columns[]", column) for column in columns]
    return pairs


# media_id finds an asset of any kind only when every type is asked for
# (the default search leaves templates and 3D out). Audio is not in the
# search API at all.
ALL_TYPES = ("photo", "illustration", "vector", "video", "template", "3d")


PICTURE_TYPES = ("photo", "illustration", "vector")


def implied_types(data):
    """The types a search must ask for by name.
      * A template or 3D filter selects nothing unless its type is in the
        search (the default search leaves templates and 3D out).
      * The `premium` filter is about pictures: the site counts every
        video as premium (premium=true answers standard videos,
        premium=false drops all of them), so a premium search is a search
        of photos, illustrations and vectors."""
    types = list(data.get("types") or ())
    if (data.get("template_apps") or data.get("template_category")) and "template" not in types:
        types.append("template")
    if data.get("three_d_type") and "3d" not in types:
        types.append("3d")
    if (data.get("video_duration") or data.get("loop")) and not types:
        types.append("video")
    if data.get("premium") and not types:
        types = list(PICTURE_TYPES)
    return types


# ---- the GraphQL API -----------------------------------------------------------------

def graphql_locale(locale):
    """'de_DE' -> ('de-DE', 'DE'): the locale and country the GraphQL
    metadata field takes."""
    return locale.replace("_", "-"), locale.split("_")[-1]


ASSET_FIELDS = """
fragment Thumb on Thumbnail { url dimension { width height } }
fragment Common on AssetMetadata {
  __typename _id title assetType assetTypeId assetFormat mimeType fileExtension premiumLevelId
  artistName attribution partnerName availableForSubscription creationDate keywords prompt
  hasReleases isEditorial isGentech
  metrics { downloads views }
  contributor { id name }
  country { id name }
  category { id name }
  licenses { name price dpi dimension { width height unit } }
}
fragment AssetFull on Asset {
  _id
  metadata(locale: $locale, countryCode: $countryCode) {
    ...Common
    ... on ImageMetadata {
      isIllustrative isTransparent categoryHierarchy { id name } dimension { width height }
      thumbnail110 { ...Thumb } thumbnail160 { ...Thumb } thumbnail220 { ...Thumb } thumbnail240 { ...Thumb }
      thumbnail360 { ...Thumb } thumbnail500 { ...Thumb } thumbnail1000 { ...Thumb }
    }
    ... on VectorMetadata {
      isIllustrative isTransparent vectorType dimension { width height }
      thumbnail220 { ...Thumb } thumbnail240 { ...Thumb } thumbnail360 { ...Thumb } thumbnail500 { ...Thumb }
      thumbnail1000 { ...Thumb }
    }
    ... on VideoMetadata {
      categoryHierarchy { id name } dimension { width height } duration framerate format videoCodec videoUrl
      formats { url formatName contentLength dimension { width height } videoBitrateInKbps videoCodec }
      thumbnail110 { ...Thumb } thumbnail160 { ...Thumb } thumbnail220 { ...Thumb } thumbnail240 { ...Thumb }
      thumbnail360 { ...Thumb } thumbnail500 { ...Thumb } thumbnail1000 { ...Thumb }
    }
    ... on TemplateMetadata {
      categoryHierarchy { id name } description dimension { width height } originalUrl resolution units
      templateTypeId templateTypeName thumbnailData previewImages { url dimension { width height unit } }
      thumbnail110 { ...Thumb } thumbnail220 { ...Thumb } thumbnail240 { ...Thumb } thumbnail360 { ...Thumb }
      thumbnail500 { ...Thumb } thumbnail1000 { ...Thumb }
    }
    ... on MogrtMetadata {
      categoryHierarchy { id name } description dimension { width height } duration originalUrl resolution units
      type templateTypeId templateTypeName thumbnailData previewImages { url dimension { width height unit } }
      typeDimension { width height unit } formats { url formatName }
      thumbnail110 { ...Thumb } thumbnail220 { ...Thumb } thumbnail240 { ...Thumb } thumbnail360 { ...Thumb }
      thumbnail500 { ...Thumb } thumbnail1000 { ...Thumb }
    }
    ... on ThreeDMetadata {
      categoryHierarchy { id name } description dimension { width height } threedTypeId threedTypeName
      thumbnail110 { ...Thumb } thumbnail220 { ...Thumb } thumbnail240 { ...Thumb } thumbnail360 { ...Thumb }
      thumbnail500 { ...Thumb } thumbnail1000 { ...Thumb }
    }
    ... on AudioMetadata {
      categoryHierarchy { id name } album description durationMilliseconds genres subgenres moods tempo
      isInstrumental isLoop renditionPreview { metadata { url } } waveformData1000 { metadata { url } }
    }
  }
}
"""

DETAILS_QUERY = """query getAssetDetailsFull($_ids: [ID!]!, $locale: String, $countryCode: String) {
  getAssetDetails(_ids: $_ids) { ...AssetFull }
}
""" + ASSET_FIELDS

SEARCH_QUERY = """query getSearchResultsFull($params: SearchInput, $locale: String, $countryCode: String) {
  getSearchResults(params: $params) {
    metadata { numberOfResults }
    pagination { currentPage pageLimit totalNumberOfPages }
    assets { ...AssetFull }
  }
}
""" + ASSET_FIELDS


def details_body(asset_ids, locale=refs.DEFAULT_LOCALE):
    tag, country = graphql_locale(locale)
    return {"query": DETAILS_QUERY, "variables": {"_ids": [str(i) for i in asset_ids], "locale": tag, "countryCode": country}}


def _selection(name, *values):
    return {"name": name, "selections": list(values)}


def _text(name, text):
    return {"name": name, "text": text}


def _range(name, low, high):
    return {"name": name, "selectedMin": low, "selectedMax": high}


def search_body(filters, page, limit, sort="RELEVANCE", locale=refs.DEFAULT_LOCALE):
    tag, country = graphql_locale(locale)
    params = {"filters": filters, "pagination": {"currentPage": page, "pageLimit": limit},
              "order": {"selection": sort}, "locale": tag, "useFacets": False}
    return {"query": SEARCH_QUERY, "variables": {"params": params, "locale": tag, "countryCode": country}}


def audio_filters(data):
    """The audio search's filters. ASSET_TYPE is required by the server
    for every search; a range needs both of its ends."""
    filters = [_selection("ASSET_TYPE", "AUDIO")]
    if data.get("query"):
        filters.append(_text("KEYWORDS", data["query"]))
    if data.get("type"):
        filters.append(_selection("AUDIO_TYPE", data["type"]))
    if data.get("genres"):
        filters.append(_selection("GENRES", *data["genres"]))
    if data.get("moods"):
        filters.append(_selection("MOODS", *data["moods"]))
    if data.get("vocals"):
        filters.append(_selection("INSTRUMENTAL", data["vocals"]))
    if data.get("loop"):
        filters.append({"name": "LOOP", "enabled": True})
    low, high = data.get("min_tempo"), data.get("max_tempo")
    if low is not None or high is not None:
        filters.append(_range("TEMPO", refs.MIN_TEMPO if low is None else low, refs.MAX_TEMPO if high is None else high))
    low, high = data.get("min_duration"), data.get("max_duration")
    if low is not None or high is not None:
        filters.append(_range("DURATION", 0 if low is None else int(low * 1000),
                              (refs.MAX_AUDIO_SECONDS if high is None else high) * 1000))
    return filters


# What the GraphQL search can answer in place of the search API (the
# keyword-search fallback): the same engine, asked through the site's own
# call. It has no contributor, similar or added-within search, so a
# request that needs one of those has no fallback.
_GRAPHQL_SORTS = {"relevance": "RELEVANCE", "creation": "CREATION", "nb_downloads": "DOWNLOADS",
                  "popularity": "POPULARITY", "undiscovered": "UNDISCOVERED"}
_GRAPHQL_ONLY_SEARCH_API = ("contributor", "similar", "similar_image", "asset", "added_within", "releases",
                            "copy_space", "video_duration", "template_apps", "template_category",
                            "max_megapixels", "max_width", "max_height", "loop")
_MAX_PIXELS = 9999          # the GraphQL size filters' own upper end
_MAX_MEGAPIXELS = 100


def graphql_search_filters(data):
    """The search request as GraphQL filters, or None when the request
    uses something only the search API has."""
    if any(data.get(name) for name in _GRAPHQL_ONLY_SEARCH_API) or data.get("max_megapixels") is not None:
        return None                 # max_megapixels=0 is a bound too
    if any((data.get(name) or 0) > top for name, top in (("min_megapixels", _MAX_MEGAPIXELS), ("min_width", _MAX_PIXELS),
                                                         ("min_height", _MAX_PIXELS))):
        return None                 # a minimum past the GraphQL filter's own upper end: the range would be upside down
    types = data.get("types") or ("photo", "illustration", "vector", "video")
    asset_types, image_kinds = [], []
    for kind in types:
        if kind in ("photo", "illustration", "vector"):
            image_kinds.append({"photo": "photo", "illustration": "illustration", "vector": "vectors"}[kind])
            if "IMAGE" not in asset_types:
                asset_types.append("IMAGE")
        else:
            asset_types.append({"video": "VIDEO", "template": "TEMPLATE", "3d": "3D"}[kind])
    filters = [_selection("ASSET_TYPE", *asset_types)]
    if 0 < len(image_kinds) < 3:
        if len(asset_types) > 1:
            return None         # the image-kind filter would also drop the videos of a mixed search
        filters.append(_selection("SUBCATEGORIES_IMAGE", *image_kinds))
    if data.get("query"):
        filters.append(_text("KEYWORDS", data["query"]))
    if data.get("category"):
        filters.append(_text("CATEGORY_2013", str(data["category"])))
    if data.get("series"):
        filters.append(_text("FROM_THIS_SERIES", str(data["series"])))
    if data.get("orientation"):
        filters.append(_selection("ORIENTATION", data["orientation"]))
    if data.get("premium"):
        filters.append(_selection("PRICE_LEVEL", "premium") if data["premium"] == "true"
                       else _selection("PRICE_LEVEL", "free", "core"))
    if data.get("ai"):
        filters.append(_selection("GENERATIVE_AI", "+gentech" if data["ai"] == "true" else "-gentech"))
    if data.get("isolated"):
        filters.append({"name": "ISOLATED", "enabled": True})
    if data.get("transparent"):
        filters.append({"name": "TRANSPARENT", "enabled": True})
    if data.get("icon"):
        filters.append(_selection("ICON", data["icon"]))
    if data.get("colors"):
        if len(data["colors"]) > 1:
            return None
        filters.append(_text("COLOR", "#" + data["colors"][0]))
    if data.get("min_megapixels") is not None:
        filters.append(_range("SIZE", data["min_megapixels"], _MAX_MEGAPIXELS))
    if data.get("min_width") is not None:
        filters.append(_range("SIZE_WIDTH", data["min_width"], _MAX_PIXELS))
    if data.get("min_height") is not None:
        filters.append(_range("SIZE_HEIGHT", data["min_height"], _MAX_PIXELS))
    if data.get("three_d_type"):
        filters.append(_selection("SUBCATEGORIES_3D", {1: "model", 2: "light", 3: "material"}[data["three_d_type"]]))
    return filters


def graphql_sort(sort):
    return _GRAPHQL_SORTS.get(sort or "relevance", "RELEVANCE")
