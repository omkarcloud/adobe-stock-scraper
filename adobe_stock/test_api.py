"""Offline tests for adobe_stock/api.py: which upstream each endpoint
asks, what it does past the end of a list, and what happens when one
upstream fails. The fetch functions are replaced by ones that answer the
fixtures; the cache is not involved (the uncached functions are called).

    python -m pytest adobe_stock/test_api.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from adobe_stock import api, queries, schemas  # noqa: E402
from adobe_stock.fetch import AdobeStockBadRequest, AdobeStockBlocked, AdobeStockNotFound, AdobeStockUpstreamError  # noqa: E402
from schema_fields import load_query  # noqa: E402
from scraper_utils import pictures  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


def query(schema, **params):
    data, error = load_query(schema, {k: str(v) for k, v in params.items()})
    assert error is None, error
    return data


class Upstreams:
    """Stand-ins for the fetch functions: each answers what the test set and records how it was asked."""

    def __init__(self, monkeypatch):
        self.search_calls, self.asset_calls, self.graphql_calls = [], [], []
        self.search = self.assets = self.graphql = None
        monkeypatch.setattr(api, "fetch_search", self._search)
        monkeypatch.setattr(api, "fetch_assets", self._assets)
        monkeypatch.setattr(api, "fetch_graphql_search", self._graphql)

    @staticmethod
    def _answer(what, *args):
        if isinstance(what, Exception):
            raise what
        return what(*args) if callable(what) else what

    def _search(self, pairs, label, not_found=()):
        params = dict((k, v) for k, v in pairs if k != "result_columns[]")
        self.search_calls.append({"params": params, "pairs": pairs, "label": label, "not_found": not_found})
        return self._answer(self.search, params)

    def _assets(self, asset_ids, locale="en_US"):
        self.asset_calls.append((list(asset_ids), locale))
        return self._answer(self.assets, asset_ids)

    def _graphql(self, filters, page, limit, sort, locale, referer):
        self.graphql_calls.append({"filters": filters, "page": page, "limit": limit, "sort": sort, "locale": locale,
                                   "referer": referer})
        return self._answer(self.graphql, filters)


@pytest.fixture
def up(monkeypatch):
    return Upstreams(monkeypatch)


def rows_of(name):
    return load(name)["data"]["getAssetDetails"]


# ---- assets/search -------------------------------------------------------------------

def test_search(up):
    up.search = load("search_coffee.json")
    out = api._assets_search(**query(schemas.AssetsSearchSchema, query="coffee", limit=8))
    assert list(out) == ["query", "type", "sort", "locale", "results", "pagination"]
    assert (out["query"], out["type"], out["sort"], out["locale"]) == ("coffee", [], "relevance", "en_US")
    assert len(out["results"]) == 8 and out["results"][0]["id"] == 94143804
    assert out["pagination"] == {"page": 1, "items_per_page": 8, "total_count": 16014776, "total_pages": 1250}
    sent = up.search_calls[0]["params"]
    assert sent["search_parameters[words]"] == "coffee" and sent["search_parameters[limit]"] == 8
    assert "search_parameters[offset]" not in sent and len(up.search_calls) == 1 and not up.graphql_calls


def test_search_page_two_asks_for_its_offset(up):
    up.search = load("search_coffee_page2.json")
    out = api._assets_search(**query(schemas.AssetsSearchSchema, query="coffee", limit=8, page=2, sort="downloads"))
    sent = up.search_calls[0]["params"]
    assert sent["search_parameters[offset]"] == 8 and sent["search_parameters[order]"] == "nb_downloads"
    assert out["sort"] == "downloads" and out["pagination"]["page"] == 2


def test_a_page_past_the_reachable_results_is_empty_and_costs_a_count(up):
    up.search = load("search_count_only.json")
    out = api._assets_search(**query(schemas.AssetsSearchSchema, query="coffee", limit=100, page=101))
    assert out["results"] == []
    assert out["pagination"] == {"page": 101, "items_per_page": 100, "total_count": 16014485, "total_pages": 100}
    call = up.search_calls[0]
    assert call["params"]["search_parameters[limit]"] == 1
    assert [v for k, v in call["pairs"] if k == "result_columns[]"] == ["nb_results", "id"]


def test_the_last_reachable_page_is_cut_at_ten_thousand(up):
    up.search = load("search_coffee.json")
    api._assets_search(**query(schemas.AssetsSearchSchema, query="coffee", limit=37, page=271))
    sent = up.search_calls[0]["params"]
    assert (sent["search_parameters[offset]"], sent["search_parameters[limit]"]) == (9990, 10)


def test_a_page_past_the_end_of_a_short_list_is_empty(up):
    up.search = load("search_past_end.json")
    out = api._assets_search(**query(schemas.AssetsSearchSchema, query="chair", three_d_type="model", limit=5, page=121))
    assert out["results"] == [] and out["pagination"]["total_count"] == 482 and out["type"] == ["3d"]
    # the site repeats its last rows past the end of some lists: they are dropped
    up.search = {"nb_results": 3, "files": load("search_coffee.json")["files"][:3]}
    assert api._assets_search(**query(schemas.AssetsSearchSchema, query="x", limit=3, page=2))["results"] == []


def test_filters_reach_the_search_api_with_their_type(up):
    up.search = load("search_motion_template.json")
    out = api._assets_search(**query(schemas.AssetsSearchSchema, query="title", template_app="premiere_pro", limit=2))
    sent = up.search_calls[0]["params"]
    assert sent["search_parameters[filters][content_type:template]"] == 1
    assert sent["search_parameters[filters][template_type_id][]"] == 6 and out["type"] == ["template"]
    up.search = load("search_premium.json")
    out = api._assets_search(**query(schemas.AssetsSearchSchema, query="coffee", premium="only", limit=2))
    sent = up.search_calls[1]["params"]
    assert sent["search_parameters[filters][premium]"] == "true"
    assert out["type"] == ["photo", "illustration", "vector"] and "search_parameters[filters][content_type:video]" not in sent
    assert all(r["is_premium"] for r in out["results"])


def test_search_falls_back_to_the_sites_own_search(up):
    up.search = AdobeStockUpstreamError("HTTP 500 for search")
    up.graphql = load("graphql_search_coffee.json")["data"]["getSearchResults"]
    out = api._assets_search(**query(schemas.AssetsSearchSchema, query="coffee", limit=8))
    assert [r["id"] for r in out["results"]][:3] == [94143804, 224982353, 129973255] and len(out["results"]) == 8
    assert out["pagination"]["total_count"] == 16080415
    call = up.graphql_calls[0]
    assert call["filters"] == [{"name": "ASSET_TYPE", "selections": ["IMAGE", "VIDEO"]}, {"name": "KEYWORDS", "text": "coffee"}]
    assert (call["page"], call["limit"], call["sort"]) == (1, 8, "RELEVANCE")


def test_the_fallback_drops_the_window_the_site_repeats_past_the_end(up):
    up.search = AdobeStockUpstreamError("HTTP 500 for search")
    up.graphql = {**load("graphql_search_coffee.json")["data"]["getSearchResults"], "metadata": {"numberOfResults": 5}}
    out = api._assets_search(**query(schemas.AssetsSearchSchema, query="coffee", page=3, limit=5))
    assert out["results"] == [] and out["pagination"] == {"page": 3, "items_per_page": 5, "total_count": 5, "total_pages": 1}
    assert len(api._assets_search(**query(schemas.AssetsSearchSchema, query="coffee", page=1, limit=5))["results"]) == 5


def test_no_fallback_for_what_only_the_search_api_has(up):
    up.search = AdobeStockBlocked("HTTP 403 for search")
    up.graphql = load("graphql_search_coffee.json")["data"]["getSearchResults"]
    with pytest.raises(AdobeStockBlocked):
        api._assets_search(**query(schemas.AssetsSearchSchema, query="coffee", added_within="1w"))
    assert not up.graphql_calls


def test_the_fallback_can_be_switched_off(up, monkeypatch):
    monkeypatch.setattr(config, "ADOBE_STOCK_GRAPHQL_FALLBACK", False)
    up.search = AdobeStockUpstreamError("HTTP 500")
    with pytest.raises(AdobeStockUpstreamError):
        api._assets_search(**query(schemas.AssetsSearchSchema, query="coffee"))
    assert not up.graphql_calls


def test_a_final_error_is_not_sent_to_the_fallback(up):
    up.search = AdobeStockBadRequest("colors filter value is invalid")
    with pytest.raises(AdobeStockBadRequest):
        api._assets_search(**query(schemas.AssetsSearchSchema, query="coffee"))
    assert not up.graphql_calls


def test_stats_switch(up, monkeypatch):
    up.search = load("search_coffee.json")
    monkeypatch.setattr(config, "ADOBE_STOCK_SHOW_STATS", False)
    out = api._assets_search(**query(schemas.AssetsSearchSchema, query="coffee", limit=8))
    assert all(r["stats"] == {"downloads": None, "views": None} for r in out["results"])


# ---- assets/similar ------------------------------------------------------------------

def test_similar_to_an_asset(up):
    up.search = load("search_similar.json")
    out = api._assets_similar(**query(schemas.AssetsSimilarSchema, asset="94143804", limit=5))
    assert list(out) == ["asset", "asset_link", "image", "type", "locale", "results", "pagination"]
    assert (out["asset"], out["asset_link"], out["image"]) == (94143804, "https://stock.adobe.com/94143804", None)
    assert out["results"][0]["id"] == 94144339
    call = up.search_calls[0]
    assert call["params"]["search_parameters[similar]"] == "94143804" and call["not_found"] == ("not supported contentId",)


def test_similar_to_a_picture(up):
    up.search = load("search_similar_image.json")
    link = "https://example.com/a.jpg"
    out = api._assets_similar(**query(schemas.AssetsSimilarSchema, image=link, type="photo", limit=3))
    assert (out["asset"], out["image"], out["type"]) == (None, link, ["photo"]) and len(out["results"]) == 3
    assert up.search_calls[0]["params"]["search_parameters[similar_url]"] == link


def test_a_picture_nobody_can_read_is_the_callers_mistake(up, monkeypatch):
    up.search = AdobeStockUpstreamError("HTTP 500 for the picture: Internal Server Error")

    def refuse(link, **kw):
        raise pictures.PictureError("image could not be used: the link is a web page, not a picture")
    monkeypatch.setattr(pictures, "download", refuse)
    with pytest.raises(ValueError) as e:
        api._assets_similar(**query(schemas.AssetsSimilarSchema, image="https://example.com/page"))
    assert str(e.value).startswith("image could not be used")
    # a picture we can read ourselves: the failure is the site's
    monkeypatch.setattr(pictures, "download", lambda link, **kw: b"\xff\xd8\xff")
    with pytest.raises(AdobeStockUpstreamError):
        api._assets_similar(**query(schemas.AssetsSimilarSchema, image="https://example.com/a.jpg"))


# ---- contributors/assets -------------------------------------------------------------

def test_portfolio(up):
    up.search = load("search_contributor.json")
    out = api._contributors_assets(**query(schemas.ContributorsAssetsSchema, contributor="203434592", limit=5))
    assert list(out) == ["contributor", "query", "type", "sort", "locale", "results", "pagination"]
    assert out["contributor"] == {"id": 203434592, "name": "chayathon2000", "country": "Thailand",
                                  "link": "https://stock.adobe.com/contributor/203434592/chayathon2000"}
    assert out["pagination"]["total_count"] == 14817 and len(up.search_calls) == 1
    assert up.search_calls[0]["not_found"] == ("Invalid creator_id",)


def test_portfolio_search_with_no_match_still_names_the_contributor(up, monkeypatch):
    monkeypatch.setattr(api, "cached_call", lambda namespace, data, fn, ttl: fn(**data))
    up.search = lambda params: (load("search_no_result.json") if "search_parameters[words]" in params
                                else load("search_contributor_first_row.json"))
    out = api._contributors_assets(**query(schemas.ContributorsAssetsSchema, contributor="203434592", query="zxqv"))
    assert out["results"] == [] and out["contributor"]["name"] == "chayathon2000" and len(up.search_calls) == 2


def test_unknown_contributor(up):
    up.search = AdobeStockNotFound("contributor 999999999999 not found")
    with pytest.raises(AdobeStockNotFound):
        api._contributors_assets(**query(schemas.ContributorsAssetsSchema, contributor="999999999999"))


# ---- assets/details ------------------------------------------------------------------

def test_details_joins_the_record_and_the_search_row(up):
    up.assets = rows_of("assets_photo_841165203.json")
    up.search = load("search_asset_841165203.json")
    out = api._asset_details("841165203", "en_US")
    assert out["id"] == 841165203 and len(out["sizes"]) == 7                 # from the record
    assert out["file_size_bytes"] == 7128031 and out["stock_id"] and out["watermarked_previews"]     # from the row
    assert up.asset_calls == [(["841165203"], "en_US")]
    sent = up.search_calls[0]["params"]
    assert sent["search_parameters[media_id]"] == "841165203"
    assert all(sent[f"search_parameters[filters][content_type:{t}]"] == 1 for t in queries.ALL_TYPES)


def test_details_of_a_track_asks_the_record_only(up):
    up.assets = rows_of("assets_audio_2250132122.json")
    out = api._asset_details("2250132122", "en_US")
    assert out["type"] == "audio" and out["audio"]["tempo_bpm"] == 121 and not up.search_calls


def test_details_without_a_search_row(up):
    up.assets = rows_of("assets_editorial_use_644781013.json")
    up.search = load("search_asset_editorial_use_no_row.json")
    out = api._asset_details("644781013", "en_US")
    assert out["id"] == 644781013 and out["is_editorial_use_only"] is True and out["file_size_bytes"] is None
    up.search = AdobeStockUpstreamError("HTTP 500")
    assert api._asset_details("644781013", "en_US")["id"] == 644781013        # the row only adds to the record


def test_details_unknown_asset(up):
    up.assets = []
    up.search = load("search_asset_not_found.json")
    with pytest.raises(AdobeStockNotFound):
        api._asset_details("999999999999", "en_US")
    assert not up.search_calls            # the details call's "no such id" is final


def test_details_from_the_search_api_when_the_record_fails(up):
    up.assets = AdobeStockUpstreamError("HTTP 503 for assets")
    up.search = load("search_asset_841165203.json")
    out = api._asset_details("841165203", "en_US")
    assert out["id"] == 841165203 and out["file_size_bytes"] == 7128031 and out["sizes"] is None
    up.search = load("search_asset_not_found.json")
    with pytest.raises(AdobeStockUpstreamError):
        api._asset_details("841165203", "en_US")
    up.search = AdobeStockBlocked("HTTP 403")
    with pytest.raises(AdobeStockUpstreamError):
        api._asset_details("841165203", "en_US")


def test_details_when_the_site_answers_the_id_without_a_record(up):
    up.assets = rows_of("assets_unserved_locale.json")
    up.search = load("search_coffee.json")
    out = api._asset_details("94143804", "en_US")
    assert out["id"] == 94143804 and out["sizes"] is None
    up.search = load("search_asset_not_found.json")
    with pytest.raises(AdobeStockNotFound):
        api._asset_details("94143804", "en_US")


def test_details_record_only_when_the_row_is_switched_off(up, monkeypatch):
    monkeypatch.setattr(config, "ADOBE_STOCK_DETAILS_SEARCH_API_ROW", False)
    up.assets = rows_of("assets_photo_841165203.json")
    out = api._asset_details("841165203", "en_US")
    assert out["file_size_bytes"] is None and not up.search_calls
    up.assets = AdobeStockUpstreamError("HTTP 503")
    with pytest.raises(AdobeStockUpstreamError):
        api._asset_details("841165203", "en_US")


# ---- assets/bulk ---------------------------------------------------------------------

def test_bulk(up):
    up.assets = rows_of("assets_mixed_found_and_unknown.json")
    wanted = ["94143804", "999999999999", "481358641", "2250132122"]
    out = api._assets_bulk(wanted, "en_US")
    assert list(out) == ["locale", "requested_count", "found_count", "not_found", "assets"]
    assert (out["requested_count"], out["found_count"], out["not_found"]) == (4, 3, [999999999999])
    assert [a["type"] for a in out["assets"]] == ["photo", "video", "audio"]
    assert up.asset_calls == [(wanted, "en_US")] and not up.search_calls
    up.assets = []
    assert api._assets_bulk(["999999999999"], "en_US")["assets"] == []


# ---- categories/list -----------------------------------------------------------------

def test_categories(monkeypatch):
    monkeypatch.setattr(api, "fetch_category_children", lambda parent, locale: load(
        "categories_1043.json" if parent else "categories_root.json"))
    monkeypatch.setattr(api, "fetch_category", lambda parent, locale: {"id": 1043, "link": "/category/travel/1043", "name": "Travel"})
    top = api._categories_list(None, "en_US")
    assert list(top) == ["parent", "locale", "count", "categories"] and top["parent"] is None and top["count"] == 21
    under = api._categories_list("1043", "en_US")
    assert under["parent"] == {"id": 1043, "name": "Travel", "link": "https://stock.adobe.com/category/travel/1043"}
    assert under["count"] == 12


# ---- audio/search --------------------------------------------------------------------

def test_audio_search(up):
    up.graphql = load("graphql_search_audio_filters.json")["data"]["getSearchResults"]
    out = api._audio_search(**query(schemas.AudioSearchSchema, query="piano", type="music", genres="jazz,classical/romantic",
                                    moods="relaxing", vocals="without", sort="downloads", limit=3))
    assert list(out) == ["query", "type", "genres", "moods", "vocals", "sort", "locale", "results", "pagination"]
    assert (out["type"], out["genres"], out["moods"], out["vocals"], out["sort"]) == (
        "music", ["Jazz", "Classical/Romantic"], ["Relaxing"], "without", "downloads")
    assert len(out["results"]) == 3 and out["pagination"]["total_count"] == 249
    call = up.graphql_calls[0]
    assert (call["page"], call["limit"], call["sort"], call["referer"]) == (1, 3, "DOWNLOADS", "https://stock.adobe.com/search/audio")
    assert {"name": "GENRES", "selections": ["Jazz", "Classical|Romantic"]} in call["filters"]


def test_audio_past_the_reachable_results(up):
    up.graphql = load("graphql_search_audio_piano.json")["data"]["getSearchResults"]
    out = api._audio_search(**query(schemas.AudioSearchSchema, query="piano", page=101, limit=100))
    assert out["results"] == [] and out["pagination"] == {"page": 101, "items_per_page": 100, "total_count": 29484,
                                                           "total_pages": 100}
    assert (up.graphql_calls[0]["page"], up.graphql_calls[0]["limit"]) == (1, 1)
    # past the end of a short list the site repeats its last window: dropped
    up.graphql = {**load("graphql_search_audio_piano.json")["data"]["getSearchResults"], "metadata": {"numberOfResults": 5}}
    assert api._audio_search(**query(schemas.AudioSearchSchema, query="piano", page=3, limit=5))["results"] == []


# ---- assets/suggestions --------------------------------------------------------------

def test_suggestions(monkeypatch):
    monkeypatch.setattr(api, "fetch_typeahead", lambda q: {"hits": [{"term": "coffee"}, {"term": "coffee cup"}]})
    monkeypatch.setattr(api, "fetch_related_searches", lambda q: ["coffee beans", "morning coffee"])
    assert api._assets_suggestions("cof") == {"query": "cof", "count": 2, "suggestions": ["coffee", "coffee cup"],
                                              "related_searches": ["coffee beans", "morning coffee"]}

    def fail(q):
        raise AdobeStockBlocked("HTTP 403")
    monkeypatch.setattr(api, "fetch_related_searches", fail)
    assert api._assets_suggestions("cof")["related_searches"] == []        # they only add to the typeahead
    monkeypatch.setattr(api, "fetch_typeahead", fail)
    with pytest.raises(AdobeStockBlocked):
        api._assets_suggestions("cof")
