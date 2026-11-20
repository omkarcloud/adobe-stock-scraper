"""Offline tests for the /adobe-stock/* request schemas, the reference
resolvers and the requests built from a validated query.

    python -m pytest adobe_stock/test_schemas.py -q
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adobe_stock import queries, refs, schemas  # noqa: E402
from schema_fields import load_query  # noqa: E402

ASSET_LINK = "https://stock.adobe.com/images/cup-of-coffee-latte-in-coffee-shop/94143804"
CONTRIBUTOR_LINK = "https://stock.adobe.com/contributor/203434592/chayathon2000"

ALL_SCHEMAS = [schemas.AssetsSearchSchema, schemas.AssetsDetailsSchema, schemas.AssetsBulkSchema,
               schemas.AssetsSimilarSchema, schemas.AssetsSuggestionsSchema, schemas.ContributorsAssetsSchema,
               schemas.CategoriesListSchema, schemas.AudioSearchSchema]


def ok(schema, query):
    data, error = load_query(schema, query)
    assert error is None, error
    return data


def bad(schema, query, field):
    data, error = load_query(schema, query)
    assert data is None and field in error["errors"], error
    return " ".join(error["errors"][field])


# ---- refs --------------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("94143804", "94143804"),
    (" 94143804 ", "94143804"),
    ("0094143804", "94143804"),
    (ASSET_LINK, "94143804"),
    (ASSET_LINK + "?prev_url=detail#x", "94143804"),
    ("https://stock.adobe.com/in/images/cup-of-coffee-latte-in-coffee-shop/94143804", "94143804"),
    ("https://stock.adobe.com/94143804", "94143804"),
    ("stock.adobe.com/video/brewed-coffee/481358641", "481358641"),
    ("//stock.adobe.com/de/templates/embroidery-text-effect/2244142596/", "2244142596"),
    ("https://stock.adobe.com/search?similar_content_id=94143804", "94143804"),
    ("https://stock.adobe.com/in/search/audio?asset_id=2250132122", "2250132122"),
    ("https://as1.ftcdn.net/v2/jpg/00/94/14/38/1000_F_94143804_QFuKnDxb29Crj61iuBClT9wQPErPfGsw.jpg", "94143804"),
    ("https://v.ftcdn.net/04/81/35/86/700_F_481358641_4uyOioGYFnr84S6nC5u1XxTGQa8qN2ui_ST.mp4", "481358641"),
    ("https://audios.ftcdn.net/22/50/13/21/48K_2250132122.m4a", "2250132122"),
])
def test_resolve_asset(value, expected):
    assert refs.resolve_asset(value) == expected


@pytest.mark.parametrize("value", [
    "", "abc", "94143804a", "9" * 13, "94143804,841165203", "https://example.com/94143804",
    "https://www.shutterstock.com/image-photo/94143804", "https://stock.adobe.com/", "https://stock.adobe.com/search?k=coffee",
    CONTRIBUTOR_LINK, "https://stock.adobe.com/category/landscapes/596", "https://as1.ftcdn.net/v2/jpg/logo.jpg",
])
def test_resolve_asset_rejects(value):
    with pytest.raises(ValueError) as e:
        refs.resolve_asset(value)
    assert "stock.adobe.com" in str(e.value)


def test_resolve_assets():
    assert refs.resolve_assets(f"94143804, 841165203 ,{ASSET_LINK},,") == ["94143804", "841165203"]
    with pytest.raises(ValueError):
        refs.resolve_assets(" , ")
    with pytest.raises(ValueError):
        refs.resolve_assets("94143804,not an id")
    ids = ",".join(str(100000 + n) for n in range(refs.MAX_BULK_ASSETS))
    assert len(refs.resolve_assets(ids)) == 100
    with pytest.raises(ValueError) as e:
        refs.resolve_assets(ids + ",5")
    assert "At most 100" in str(e.value)


@pytest.mark.parametrize("value, expected", [
    ("203434592", "203434592"),
    (CONTRIBUTOR_LINK, "203434592"),
    ("https://stock.adobe.com/in/contributor/203434592/chayathon2000?load_type=author", "203434592"),
    ("stock.adobe.com/contributor/210481708/x", "210481708"),
    ("https://stock.adobe.com/search?creator_id=203434592", "203434592"),
])
def test_resolve_contributor(value, expected):
    assert refs.resolve_contributor(value) == expected


@pytest.mark.parametrize("value", ["", "chayathon2000", "@chayathon2000", ASSET_LINK, "https://example.com/contributor/1/x"])
def test_resolve_contributor_rejects(value):
    with pytest.raises(ValueError) as e:
        refs.resolve_contributor(value)
    assert "contributor" in str(e.value)


@pytest.mark.parametrize("value, expected", [
    ("596", "596"), ("https://stock.adobe.com/category/landscapes/596", "596"),
    ("https://stock.adobe.com/de/category/tiere/1?load_type=category", "1"), ("stock.adobe.com/category/1043", "1043"),
])
def test_resolve_category(value, expected):
    assert refs.resolve_category(value) == expected


@pytest.mark.parametrize("value", ["", "landscapes", ASSET_LINK, "https://stock.adobe.com/category/landscapes"])
def test_resolve_category_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_category(value)


def test_resolve_colors_genres_moods_locale():
    assert refs.resolve_colors("FF0000, #0000ff,ff0000") == ["ff0000", "0000ff"]
    for value in ("red", "ff00", "#ff0000,00ff00,0000ff,ffffff", ","):
        with pytest.raises(ValueError):
            refs.resolve_colors(value)
    assert refs.resolve_genres("jazz, Rock/Indie, hip hop, r&b, classical|romantic") == [
        "Jazz", "Rock|Indie", "Hip-Hop", "R&B", "Classical|Romantic"]
    for value in ("polka", "Jazz/Indie", ""):
        with pytest.raises(ValueError):
            refs.resolve_genres(value)
    assert refs.resolve_moods("happy, space age,HAPPY") == ["Happy", "Space Age"]
    with pytest.raises(ValueError):
        refs.resolve_moods("grumpy")
    assert [refs.resolve_locale(v) for v in ("de_DE", "de-de", "de", "PT", "pt_pt", "en")] == [
        "de_DE", "de_DE", "de_DE", "pt_BR", "pt_PT", "en_US"]
    for value in ("en_GB", "zh_CN", "xx", ""):
        with pytest.raises(ValueError):
            refs.resolve_locale(value)


def test_links():
    assert refs.asset_link(94143804) == "https://stock.adobe.com/94143804" and refs.asset_link(None) is None
    assert refs.contributor_link(203434592, "chayathon2000") == CONTRIBUTOR_LINK
    # the page needs a last segment (any text): /contributor/<id> alone is a 404
    assert refs.contributor_link(210481708, "Dashing Scherzo/FineTune Music").endswith("/210481708/Dashing-Scherzo-FineTune-Music")
    assert refs.contributor_link(5, None).endswith("/contributor/5/portfolio") and refs.contributor_link(None, "x") is None
    assert refs.category_link("/category/animals/1?load_type=category") == "https://stock.adobe.com/category/animals/1"
    assert refs.category_link(None) is None and refs.category_link("category/x") is None


def test_every_subgenre_and_mood_has_a_token():
    assert len(refs.GENRES) == 20 and sum(len(v) for v in refs.GENRES.values()) == 117 and len(refs.MOODS) == 30
    for genre, subgenres in refs.GENRES.items():
        assert refs.resolve_genres(genre) == [genre]
        for sub in subgenres:
            assert refs.resolve_genres(f"{genre}/{sub}") == [f"{genre}|{sub}"]


# ---- assets/search -----------------------------------------------------------------

def test_search_defaults():
    data = ok(schemas.AssetsSearchSchema, {"query": " coffee  cup "})
    assert data["query"] == "coffee cup" and data["page"] == 1 and data["limit"] == 100 and data["locale"] == "en_US"
    for name in ("type", "sort", "orientation", "premium", "ai", "releases", "isolated", "colors", "category", "series"):
        assert data[name] is None, name
    assert ok(schemas.AssetsSearchSchema, {})["query"] is None           # a search needs no keyword


def test_search_every_choice_maps_to_the_sites_token():
    data = ok(schemas.AssetsSearchSchema, {
        "query": "coffee", "type": "Photo, vector,photo", "sort": "newest", "orientation": "Vertical", "premium": "only",
        "ai": "exclude", "releases": "with", "isolated": "true", "transparent": "1", "copy_space": "yes",
        "icon": "sheet", "colors": "#FF0000,0000ff", "min_megapixels": "10", "max_megapixels": "20.5",
        "min_width": "1000", "max_width": "2000", "min_height": "500", "max_height": "900", "added_within": "6m",
        "category": "https://stock.adobe.com/category/landscapes/596", "series": ASSET_LINK, "locale": "de",
        "page": "3", "limit": "50"})
    assert data["type"] == ["photo", "vector"] and data["sort"] == "creation" and data["orientation"] == "vertical"
    assert (data["premium"], data["ai"], data["releases"]) == ("true", "false", "true")
    assert data["isolated"] is True and data["transparent"] is True and data["copy_space"] is True
    assert data["icon"] == "icon_sheet" and data["colors"] == ["ff0000", "0000ff"]
    assert (data["min_megapixels"], data["max_megapixels"]) == (10.0, 20.5)
    assert (data["added_within"], data["category"], data["series"], data["locale"]) == ("6m", "596", "94143804", "de_DE")
    assert (data["page"], data["limit"]) == (3, 50)
    for sort, token in refs.SORTS.items():
        assert ok(schemas.AssetsSearchSchema, {"sort": sort})["sort"] == token
    for value, token in refs.VIDEO_DURATIONS.items():
        assert ok(schemas.AssetsSearchSchema, {"video_duration": value})["video_duration"] == token
    assert ok(schemas.AssetsSearchSchema, {"template_app": "photoshop, Premiere_Pro"})["template_app"] == [1, 6]
    assert ok(schemas.AssetsSearchSchema, {"template_category": "social_media"})["template_category"] == 12
    assert ok(schemas.AssetsSearchSchema, {"three_d_type": "material"})["three_d_type"] == 3


@pytest.mark.parametrize("query, field", [
    ({"sort": "price"}, "sort"), ({"sort": "featured"}, "sort"), ({"type": "audio"}, "type"), ({"type": "photo,gif"}, "type"),
    ({"orientation": "portrait"}, "orientation"), ({"premium": "true"}, "premium"), ({"ai": "yes"}, "ai"),
    ({"releases": "only"}, "releases"), ({"isolated": "false"}, "isolated"), ({"icon": "all"}, "icon"),
    ({"colors": "red"}, "colors"), ({"colors": "ff0000,00ff00,0000ff,ffffff"}, "colors"),
    ({"min_megapixels": "-1"}, "min_megapixels"), ({"min_megapixels": "30", "max_megapixels": "5"}, "min_megapixels"),
    ({"max_megapixels": "5000"}, "max_megapixels"), ({"min_width": "0"}, "min_width"),
    ({"min_width": "900", "max_width": "100"}, "min_width"), ({"min_height": "9", "max_height": "1"}, "min_height"),
    ({"added_within": "3d"}, "added_within"), ({"video_duration": "10"}, "video_duration"),
    ({"template_app": "word"}, "template_app"), ({"template_category": "13"}, "template_category"),
    ({"three_d_type": "scene"}, "three_d_type"), ({"category": "landscapes"}, "category"), ({"series": "abc"}, "series"),
    ({"locale": "en_GB"}, "locale"), ({"page": "0"}, "page"), ({"page": "10001"}, "page"), ({"limit": "101"}, "limit"),
    ({"limit": "0"}, "limit"), ({"query": "x" * 201}, "query"), ({"creator": "5"}, "creator"),
])
def test_search_rejects(query, field):
    bad(schemas.AssetsSearchSchema, query, field)


def test_a_filter_of_one_type_needs_that_type():
    assert "video" in bad(schemas.AssetsSearchSchema, {"type": "photo", "video_duration": "up_to_10"}, "video_duration")
    bad(schemas.AssetsSearchSchema, {"type": "photo", "loop": "true"}, "loop")
    bad(schemas.AssetsSearchSchema, {"type": "video", "template_app": "photoshop"}, "template_app")
    bad(schemas.AssetsSearchSchema, {"type": "photo,video", "template_category": "web"}, "template_category")
    bad(schemas.AssetsSearchSchema, {"type": "template", "three_d_type": "model"}, "three_d_type")
    ok(schemas.AssetsSearchSchema, {"type": "photo,video", "video_duration": "over_30", "loop": "true"})
    ok(schemas.AssetsSearchSchema, {"type": "template", "template_app": "indesign", "template_category": "print"})
    ok(schemas.AssetsSearchSchema, {"three_d_type": "light"})


def test_premium_is_a_filter_of_pictures():
    ok(schemas.AssetsSearchSchema, {"premium": "only"})
    ok(schemas.AssetsSearchSchema, {"premium": "exclude", "type": "photo,vector,illustration"})
    assert "photos" in bad(schemas.AssetsSearchSchema, {"premium": "only", "type": "video"}, "premium")
    bad(schemas.AssetsSearchSchema, {"premium": "exclude", "type": "photo,template"}, "premium")
    bad(schemas.AssetsSearchSchema, {"premium": "only", "video_duration": "up_to_10"}, "premium")
    bad(schemas.AssetsSearchSchema, {"premium": "only", "three_d_type": "model"}, "premium")


# ---- the other routes --------------------------------------------------------------

def test_details_and_bulk():
    assert ok(schemas.AssetsDetailsSchema, {"asset": ASSET_LINK}) == {"asset": "94143804", "locale": "en_US"}
    assert ok(schemas.AssetsDetailsSchema, {"asset": "94143804", "locale": "ja-JP"})["locale"] == "ja_JP"
    assert "stock.adobe.com" in bad(schemas.AssetsDetailsSchema, {"asset": "abc"}, "asset")
    bad(schemas.AssetsDetailsSchema, {}, "asset")
    bad(schemas.AssetsDetailsSchema, {"asset": ""}, "asset")
    bad(schemas.AssetsDetailsSchema, {"asset": "1", "id": "1"}, "id")
    assert ok(schemas.AssetsBulkSchema, {"assets": f"841165203,{ASSET_LINK}, 841165203"})["assets"] == ["841165203", "94143804"]
    assert "At most 100" in bad(schemas.AssetsBulkSchema, {"assets": ",".join(str(n) for n in range(1, 102))}, "assets")
    bad(schemas.AssetsBulkSchema, {"assets": "94143804;841165203"}, "assets")
    bad(schemas.AssetsBulkSchema, {}, "assets")


def test_similar_takes_an_asset_or_a_picture():
    assert ok(schemas.AssetsSimilarSchema, {"asset": ASSET_LINK})["asset"] == "94143804"
    data = ok(schemas.AssetsSimilarSchema, {"image": "example.com/a.jpg", "type": "video", "limit": "10"})
    assert data["image"] == "https://example.com/a.jpg" and data["asset"] is None and data["type"] == ["video"]
    assert "one of the two" in bad(schemas.AssetsSimilarSchema, {}, "asset")
    bad(schemas.AssetsSimilarSchema, {"asset": "94143804", "image": "https://example.com/a.jpg"}, "asset")
    bad(schemas.AssetsSimilarSchema, {"image": "data:image/png;base64,AAAA"}, "image")
    bad(schemas.AssetsSimilarSchema, {"image": "not a link"}, "image")
    bad(schemas.AssetsSimilarSchema, {"asset": "1", "sort": "newest"}, "sort")


def test_contributor_assets():
    data = ok(schemas.ContributorsAssetsSchema, {"contributor": CONTRIBUTOR_LINK, "type": "video", "sort": "downloads"})
    assert (data["contributor"], data["type"], data["sort"], data["query"]) == ("203434592", ["video"], "nb_downloads", None)
    assert "contributor" in bad(schemas.ContributorsAssetsSchema, {"contributor": "chayathon2000"}, "contributor")
    bad(schemas.ContributorsAssetsSchema, {}, "contributor")
    bad(schemas.ContributorsAssetsSchema, {"contributor": "5", "sort": "oldest"}, "sort")


def test_categories_and_suggestions():
    assert ok(schemas.CategoriesListSchema, {}) == {"parent": None, "locale": "en_US"}
    assert ok(schemas.CategoriesListSchema, {"parent": "https://stock.adobe.com/category/travel/1043"})["parent"] == "1043"
    bad(schemas.CategoriesListSchema, {"parent": "travel"}, "parent")
    assert ok(schemas.AssetsSuggestionsSchema, {"query": " cof "}) == {"query": "cof"}
    bad(schemas.AssetsSuggestionsSchema, {}, "query")
    bad(schemas.AssetsSuggestionsSchema, {"query": "x" * 101}, "query")


def test_audio_search():
    data = ok(schemas.AudioSearchSchema, {
        "query": "piano", "type": "Music", "genres": "jazz, classical/romantic", "moods": "relaxing", "min_tempo": "60",
        "max_tempo": "140", "min_duration": "60", "max_duration": "300", "vocals": "without", "loop": "true",
        "sort": "downloads"})
    assert (data["type"], data["genres"], data["moods"]) == ("music", ["Jazz", "Classical|Romantic"], ["Relaxing"])
    assert (data["vocals"], data["loop"], data["sort"]) == ("no-vocals", True, "DOWNLOADS")
    assert ok(schemas.AudioSearchSchema, {})["query"] is None
    for query, field in (({"type": "podcast"}, "type"), ({"genres": "polka"}, "genres"), ({"moods": "grumpy"}, "moods"),
                         ({"min_tempo": "0"}, "min_tempo"), ({"max_tempo": "301"}, "max_tempo"),
                         ({"min_tempo": "150", "max_tempo": "90"}, "min_tempo"), ({"max_duration": "1201"}, "max_duration"),
                         ({"min_duration": "90", "max_duration": "30"}, "min_duration"), ({"vocals": "yes"}, "vocals"),
                         ({"loop": "false"}, "loop"), ({"sort": "price"}, "sort"), ({"limit": "101"}, "limit")):
        bad(schemas.AudioSearchSchema, query, field)


# ---- empty params (a form that sends every field) ----------------------------------

@pytest.mark.parametrize("schema_cls", ALL_SCHEMAS)
def test_an_empty_optional_param_is_the_absent_param(schema_cls):
    schema = schema_cls()
    required = {name: "94143804" if "asset" in name else "203434592" if name == "contributor" else "coffee"
                for name, field in schema.fields.items() if field.required}
    if schema_cls is schemas.AssetsSimilarSchema:
        required = {"asset": "94143804"}
    plain = ok(schema_cls, dict(required))
    everything_empty = {name: "" for name in schema.fields if name not in required}
    assert ok(schema_cls, {**everything_empty, **required}) == plain
    assert ok(schema_cls, {**{k: "  " for k in everything_empty}, **required}) == plain


@pytest.mark.parametrize("schema_cls", ALL_SCHEMAS)
def test_every_field_says_what_it_takes(schema_cls):
    for name, field in schema_cls().fields.items():
        assert field.metadata.get("description"), f"{schema_cls.__name__}.{name}"


# ---- the requests built from a query -----------------------------------------------

def _pairs(request, offset=0, limit=100, locale="en_US"):
    request = {**request, "types": queries.implied_types(request)}
    return [p for p in queries.search_params(request, offset, limit, locale) if p[0] != "result_columns[]"]


def test_search_api_request():
    assert _pairs({"query": "coffee"}) == [("locale", "en_US"), ("search_parameters[words]", "coffee"),
                                           ("search_parameters[limit]", 100)]
    pairs = _pairs({"query": "coffee", "types": ["photo", "vector"], "sort": "nb_downloads", "orientation": "vertical",
                    "ai": "false", "releases": "true", "isolated": True, "transparent": True, "copy_space": True,
                    "icon": "single_icon", "colors": ["ff0000", "0000ff"], "min_megapixels": 10.0, "max_megapixels": 20.5,
                    "min_width": 1000, "max_height": 900, "added_within": "6m", "category": "596", "series": "94143804"},
                   offset=200, limit=50, locale="de_DE")
    assert pairs == [
        ("locale", "de_DE"), ("search_parameters[words]", "coffee"), ("search_parameters[category]", "596"),
        ("search_parameters[serie_id]", "94143804"), ("search_parameters[limit]", 50), ("search_parameters[offset]", 200),
        ("search_parameters[order]", "nb_downloads"),
        ("search_parameters[filters][content_type:photo]", 1), ("search_parameters[filters][content_type:vector]", 1),
        ("search_parameters[filters][orientation]", "vertical"), ("search_parameters[filters][gentech]", "false"),
        ("search_parameters[filters][has_releases]", "true"), ("search_parameters[filters][isolated:on]", 1),
        ("search_parameters[filters][transparent]", "true"), ("search_parameters[filters][copy_space]", 1),
        ("search_parameters[filters][icon_option]", "single_icon"), ("search_parameters[filters][colors]", "ff0000,0000ff"),
        ("search_parameters[filters][area_m_pixels]", "10-20.5"), ("search_parameters[filters][image_width]", "1000-"),
        ("search_parameters[filters][image_height]", "-900"), ("search_parameters[filters][age]", "6m")]
    assert ("result_columns[]", "nb_downloads") in queries.search_params({"query": "x"})
    assert "thumbnail_html_tag" not in queries.RESULT_COLUMNS and "3d_type_id" not in queries.RESULT_COLUMNS


def test_a_filter_brings_its_type_into_the_search():
    assert queries.implied_types({}) == []
    assert queries.implied_types({"template_apps": [1]}) == ["template"]
    assert queries.implied_types({"types": ["photo"], "template_category": 3}) == ["photo", "template"]
    assert queries.implied_types({"three_d_type": 2}) == ["3d"]
    assert queries.implied_types({"video_duration": "10"}) == ["video"] and queries.implied_types({"loop": True}) == ["video"]
    assert queries.implied_types({"types": ["photo", "video"], "loop": True}) == ["photo", "video"]
    assert queries.implied_types({"premium": "true"}) == ["photo", "illustration", "vector"]
    assert queries.implied_types({"premium": "false", "types": ["vector"]}) == ["vector"]
    pairs = _pairs({"query": "title", "template_apps": [6, 5], "template_category": 8, "three_d_type": None})
    assert ("search_parameters[filters][content_type:template]", 1) in pairs
    assert [p[1] for p in pairs if p[0] == "search_parameters[filters][template_type_id][]"] == [6, 5]
    assert ("search_parameters[filters][template_category_id][]", 8) in pairs
    assert ("search_parameters[filters][3d_type_id][]", 1) in _pairs({"three_d_type": 1})
    assert ("search_parameters[filters][is_loop]", 1) in _pairs({"loop": True})


def test_contributor_similar_and_asset_requests():
    assert ("search_parameters[creator_id]", "203434592") in _pairs({"contributor": "203434592"})
    assert ("search_parameters[similar]", "94143804") in _pairs({"similar": "94143804"})
    assert ("search_parameters[similar_url]", "https://example.com/a.jpg") in _pairs({"similar_image": "https://example.com/a.jpg"})
    pairs = _pairs({"asset": "2244142596", "types": queries.ALL_TYPES}, limit=1)
    assert ("search_parameters[media_id]", "2244142596") in pairs
    assert sum(1 for p in pairs if "content_type:" in p[0]) == 6


@pytest.mark.parametrize("page, limit, expected", [
    (1, 100, (0, 100)), (2, 100, (100, 100)), (100, 100, (9900, 100)), (101, 100, (10000, 0)),
    (3, 37, (74, 37)), (271, 37, (9990, 10)), (272, 37, (10027, 0)), (10000, 1, (9999, 1)),
])
def test_a_page_stays_inside_the_results_the_search_reaches(page, limit, expected):
    assert queries.window(page, limit) == expected


def test_graphql_bodies():
    body = queries.details_body(["94143804", 841165203], "de_DE")
    assert body["variables"] == {"_ids": ["94143804", "841165203"], "locale": "de-DE", "countryCode": "DE"}
    assert "getAssetDetails(_ids: $_ids)" in body["query"]
    # the two fields that fail a visitor's call (queries.py) are never asked for
    assert "isLicensable" not in body["query"] and "__typename _id title assetType" in body["query"]
    search = queries.search_body([{"name": "ASSET_TYPE", "selections": ["AUDIO"]}], 2, 50, "DOWNLOADS", "fr_FR")
    assert search["variables"]["params"] == {
        "filters": [{"name": "ASSET_TYPE", "selections": ["AUDIO"]}], "pagination": {"currentPage": 2, "pageLimit": 50},
        "order": {"selection": "DOWNLOADS"}, "locale": "fr-FR", "useFacets": False}
    assert search["variables"]["countryCode"] == "FR"


def test_audio_filters():
    assert queries.audio_filters({}) == [{"name": "ASSET_TYPE", "selections": ["AUDIO"]}]
    filters = queries.audio_filters({"query": "piano", "type": "music", "genres": ["Jazz", "Classical|Romantic"],
                                     "moods": ["Relaxing"], "vocals": "no-vocals", "loop": True, "min_tempo": 60,
                                     "max_duration": 300})
    assert filters == [
        {"name": "ASSET_TYPE", "selections": ["AUDIO"]}, {"name": "KEYWORDS", "text": "piano"},
        {"name": "AUDIO_TYPE", "selections": ["music"]}, {"name": "GENRES", "selections": ["Jazz", "Classical|Romantic"]},
        {"name": "MOODS", "selections": ["Relaxing"]}, {"name": "INSTRUMENTAL", "selections": ["no-vocals"]},
        {"name": "LOOP", "enabled": True},
        {"name": "TEMPO", "selectedMin": 60, "selectedMax": 300},           # a range needs both ends
        {"name": "DURATION", "selectedMin": 0, "selectedMax": 300000}]       # seconds -> milliseconds
    assert queries.audio_filters({"min_duration": 30})[-1] == {"name": "DURATION", "selectedMin": 30000, "selectedMax": 1200000}


def test_the_fallback_search_takes_only_what_it_has():
    assert queries.graphql_search_filters({"query": "coffee"}) == [
        {"name": "ASSET_TYPE", "selections": ["IMAGE", "VIDEO"]}, {"name": "KEYWORDS", "text": "coffee"}]
    filters = queries.graphql_search_filters({"query": "coffee", "types": ["photo"], "orientation": "vertical", "ai": "false",
                                              "premium": "false", "isolated": True, "transparent": True, "icon": "single_icon",
                                              "colors": ["ffffff"], "min_megapixels": 10, "min_width": 2000, "min_height": 500,
                                              "category": "596", "series": "94143804"})
    assert filters == [
        {"name": "ASSET_TYPE", "selections": ["IMAGE"]}, {"name": "SUBCATEGORIES_IMAGE", "selections": ["photo"]},
        {"name": "KEYWORDS", "text": "coffee"}, {"name": "CATEGORY_2013", "text": "596"},
        {"name": "FROM_THIS_SERIES", "text": "94143804"}, {"name": "ORIENTATION", "selections": ["vertical"]},
        {"name": "PRICE_LEVEL", "selections": ["free", "core"]}, {"name": "GENERATIVE_AI", "selections": ["-gentech"]},
        {"name": "ISOLATED", "enabled": True}, {"name": "TRANSPARENT", "enabled": True},
        {"name": "ICON", "selections": ["single_icon"]}, {"name": "COLOR", "text": "#ffffff"},
        {"name": "SIZE", "selectedMin": 10, "selectedMax": 100}, {"name": "SIZE_WIDTH", "selectedMin": 2000, "selectedMax": 9999},
        {"name": "SIZE_HEIGHT", "selectedMin": 500, "selectedMax": 9999}]
    assert queries.graphql_search_filters({"types": ["3d"], "three_d_type": 3}) == [
        {"name": "ASSET_TYPE", "selections": ["3D"]}, {"name": "SUBCATEGORIES_3D", "selections": ["material"]}]
    assert queries.graphql_search_filters({"types": ["photo", "illustration", "vector"], "premium": "true"}) == [
        {"name": "ASSET_TYPE", "selections": ["IMAGE"]}, {"name": "PRICE_LEVEL", "selections": ["premium"]}]
    # what only the search API has: no fallback
    for request in ({"contributor": "5"}, {"similar": "5"}, {"similar_image": "https://x.com/a.jpg"}, {"added_within": "1w"},
                    {"releases": "true"}, {"copy_space": True}, {"video_duration": "10"}, {"template_apps": [1]},
                    {"max_width": 100}, {"max_megapixels": 0.0}, {"loop": True}, {"colors": ["ff0000", "0000ff"]},
                    {"types": ["photo", "video"]},
                    # a minimum above the GraphQL filter's own upper end (9999 px, 100 megapixels)
                    {"min_width": 12000}, {"min_height": 10000}, {"min_megapixels": 150.0}):
        assert queries.graphql_search_filters({"query": "coffee", **request}) is None, request
    assert [queries.graphql_sort(s) for s in (None, "relevance", "creation", "nb_downloads", "popularity", "undiscovered")] == [
        "RELEVANCE", "RELEVANCE", "CREATION", "DOWNLOADS", "POPULARITY", "UNDISCOVERED"]
