"""Offline tests for adobe_stock/fetch.py: how each upstream's answers,
captured in fixtures/, are read into the scraper error taxonomy. No
network: the thread's session is replaced by one that answers a fixture.

    python -m pytest adobe_stock/test_fetch.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
from adobe_stock import fetch, queries  # noqa: E402
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def raw(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


class Answer:
    def __init__(self, status, text, content_type="application/json"):
        self.status_code, self.text = status, text
        self.headers = {"content-type": content_type}

    def json(self):
        return json.loads(self.text)


class Session:
    """Answers the queued answers in order (the last one again after that) and records each request."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        answer = self.answers[min(len(self.calls), len(self.answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def site(monkeypatch):
    """site(answer, ...) installs a session that gives those answers."""
    monkeypatch.setattr(config, "RETRY_BACKOFF", 0)
    monkeypatch.setattr(fetch, "_drop_session", lambda: None)

    def install(*answers):
        session = Session(*answers)
        monkeypatch.setattr(fetch, "_session", lambda: session)
        return session
    return install


def ok(name):
    return Answer(200, raw(name))


PAIRS = queries.search_params({"query": "coffee"}, 0, 8)


# ---- the search API ------------------------------------------------------------------

def test_search_request_as_it_is_sent(site):
    session = site(ok("search_coffee.json"))
    payload = fetch.fetch_search(PAIRS, "search 'coffee'")
    assert payload["nb_results"] == 16014776 and len(payload["files"]) == 8
    method, url, kw = session.calls[0]
    assert (method, url) == ("GET", "https://stock.adobe.io/Rest/Media/1/Search/Files")
    assert kw["headers"] == {"accept": "application/json", "origin": "https://stock.adobe.com",
                             "referer": "https://stock.adobe.com/", "x-product": "AdobeStock/1.0",
                             "x-api-key": "AdobeStockClient2"}
    assert ("search_parameters[words]", "coffee") in kw["params"] and len(session.calls) == 1


def test_search_no_result_is_an_empty_answer(site):
    site(ok("search_no_result.json"))
    assert fetch.fetch_search(PAIRS, "search") == {"nb_results": 0, "files": []}


@pytest.mark.parametrize("fixture, status, not_found, error", [
    ("search_error_contributor.json", 400, ("Invalid creator_id",), NotFound),
    ("search_error_similar.json", 400, ("not supported contentId",), NotFound),
    ("search_error_contributor.json", 400, (), BadRequest),
    ("search_error_columns.json", 400, (), BadRequest),
])
def test_search_errors_that_are_final(site, fixture, status, not_found, error):
    session = site(Answer(status, raw(fixture)))
    with pytest.raises(error):
        fetch.fetch_search(PAIRS, "the record", not_found)
    assert len(session.calls) == 1          # never retried


def test_the_sites_message_reaches_the_caller(site):
    site(Answer(400, raw("search_error_columns.json")))
    with pytest.raises(BadRequest) as e:
        fetch.fetch_search(PAIRS, "search")
    assert "Unsupported result columns" in str(e.value)


def test_a_server_error_is_retried(site):
    session = site(Answer(500, raw("search_error_similar_image.json")))
    with pytest.raises(UpstreamError) as e:
        fetch.fetch_search(PAIRS, "the picture")
    assert not isinstance(e.value, Blocked) and "Internal Server Error" in str(e.value)
    assert len(session.calls) == config.MAX_RETRIES
    session = site(Answer(500, raw("search_error_similar_image.json")), ok("search_coffee.json"))
    assert len(fetch.fetch_search(PAIRS, "search")["files"]) == 8 and len(session.calls) == 2


@pytest.mark.parametrize("answer", [
    Answer(403, "<html>blocked</html>", "text/html"), Answer(429, "{}"), Answer(401, '{"error":"x"}'),
    Answer(200, "<html>please verify</html>", "text/html"),
])
def test_a_refusal_is_blocked(site, answer):
    site(answer)
    with pytest.raises(Blocked):
        fetch.fetch_search(PAIRS, "search")


def test_a_transport_failure_and_an_unexpected_body(site):
    site(ConnectionError("reset"))
    with pytest.raises(UpstreamError) as e:
        fetch.fetch_search(PAIRS, "search")
    assert "ConnectionError" in str(e.value)
    site(Answer(200, '{"nb_results": 5}'))
    with pytest.raises(UpstreamError):
        fetch.fetch_search(PAIRS, "search")
    site(Answer(502, "Bad Gateway", "text/plain"))
    with pytest.raises(UpstreamError):
        fetch.fetch_search(PAIRS, "search")


def test_categories(site):
    session = site(ok("categories_root.json"))
    assert len(fetch.fetch_category_children()) == 21
    assert session.calls[0][1].endswith("/Search/CategoryTree") and session.calls[0][2]["params"] == [("locale", "en_US")]
    session = site(ok("categories_1043.json"))
    assert len(fetch.fetch_category_children("1043", "de_DE")) == 12
    assert session.calls[0][2]["params"] == [("locale", "de_DE"), ("category_id", "1043")]
    site(ok("category_596.json"))
    assert fetch.fetch_category("596")["name"] == "Landscapes"


def test_an_unknown_category_is_not_found_whatever_the_status(site):
    # the same message comes with HTTP 400 from the tree and HTTP 500 from the record
    session = site(Answer(400, raw("categories_error_unknown.json")))
    with pytest.raises(NotFound):
        fetch.fetch_category_children("99999999")
    session2 = site(Answer(500, raw("category_error_unknown.json")))
    with pytest.raises(NotFound):
        fetch.fetch_category("99999999")
    assert len(session.calls) == 1 and len(session2.calls) == 1


# ---- the GraphQL API -----------------------------------------------------------------

def test_details_request_as_it_is_sent(site):
    session = site(ok("assets_photo_841165203.json"))
    rows = fetch.fetch_assets(["841165203"])
    assert [r["_id"] for r in rows] == ["841165203"]
    method, url, kw = session.calls[0]
    assert (method, url) == ("POST", "https://stock.adobe.com/graphql")
    assert kw["headers"] == {
        "accept": "*/*", "apollographql-client-name": "stock-search-app", "content-type": "application/json",
        "origin": "https://stock.adobe.com", "priority": "u=1, i", "sec-ch-prefers-color-scheme": "light",
        "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin",
        "referer": "https://stock.adobe.com/841165203", "x-api-key": "AdobeStockClient2"}
    body = json.loads(kw["data"])
    assert body["variables"] == {"_ids": ["841165203"], "locale": "en-US", "countryCode": "US"}


def test_headers_the_session_sets_are_left_to_it():
    for headers in (fetch.SEARCH_API_HEADERS, fetch.GRAPHQL_HEADERS, fetch.RELATED_HEADERS, fetch.TYPEAHEAD_HEADERS):
        assert not {"user-agent", "accept-language", "accept-encoding", "cookie", "sec-ch-ua"} & set(headers)


def test_unknown_ids_are_absent(site):
    site(ok("assets_not_found.json"))
    assert fetch.fetch_assets(["999999999999"]) == []
    site(ok("assets_mixed_found_and_unknown.json"))
    assert [r["_id"] for r in fetch.fetch_assets(["94143804", "999999999999", "481358641", "2250132122"])] == [
        "94143804", "481358641", "2250132122"]


def test_a_field_error_next_to_the_data_keeps_the_rows(site):
    session = site(ok("assets_template_field_error_222533946.json"))
    rows = fetch.fetch_assets(["222533946"])
    assert rows[0]["metadata"]["templateTypeName"] == "InDesign" and len(session.calls) == 1


def test_graphql_search(site):
    session = site(ok("graphql_search_audio_piano.json"))
    result = fetch.fetch_graphql_search(queries.audio_filters({"query": "piano"}), 1, 5, "RELEVANCE", "en_US",
                                        "https://stock.adobe.com/search/audio")
    assert result["metadata"]["numberOfResults"] == 29484 and len(result["assets"]) == 5
    assert session.calls[0][2]["headers"]["referer"] == "https://stock.adobe.com/search/audio"


@pytest.mark.parametrize("fixture, text", [
    ("graphql_search_error_filter.json", "GENRES"), ("graphql_search_error_no_type.json", "ASSET_TYPE"),
])
def test_a_refused_filter_is_a_bad_request(site, fixture, text):
    session = site(ok(fixture))
    with pytest.raises(BadRequest) as e:
        fetch.fetch_graphql_search([], 1, 5, "RELEVANCE", "en_US", "https://stock.adobe.com/search")
    assert text in str(e.value) and len(session.calls) == 1


@pytest.mark.parametrize("answer, error", [
    (Answer(403, '{"url":"https://geo.captcha-delivery.com/interstitial/"}'), Blocked),
    (Answer(200, "<html>", "text/html"), Blocked),
    (Answer(200, '{"data": null, "errors": [{"message": "Internal server error"}]}'), UpstreamError),
    (Answer(400, '{"errors": [{"message": "Cannot query field"}]}'), UpstreamError),
    (Answer(503, "unavailable", "text/plain"), UpstreamError),
    # the whole operation failed (its field is null NEXT TO errors): not "none of the ids exist"
    (Answer(200, '{"data": {"getAssetDetails": null}, "errors": [{"message": "Internal server error", '
                 '"path": ["getAssetDetails"]}]}'), UpstreamError),
])
def test_graphql_failures(site, answer, error):
    session = site(answer)
    with pytest.raises(error):
        fetch.fetch_assets(["94143804"])
    assert len(session.calls) == config.MAX_RETRIES         # each of them is retried


# ---- suggestions ---------------------------------------------------------------------

def test_related_searches(site):
    session = site(ok("related_wedding.json"))
    assert fetch.fetch_related_searches("wedding")[0] == "wedding reception"
    method, url, kw = session.calls[0]
    assert (method, url) == ("POST", "https://stock.adobe.com/QuerySuggestion")
    # the page's whole filter object goes with the keyword: without it the site answers null
    assert json.loads(kw["data"]) == {"filters": fetch.RELATED_FILTERS, "k": "wedding"}
    assert kw["headers"]["x-requested-with"] == "XMLHttpRequest" and "x-api-key" not in kw["headers"]
    site(ok("related_null.json"))
    assert fetch.fetch_related_searches("wedding") == []
    site(Answer(403, '{"url":"https://geo.captcha-delivery.com/interstitial/?x"}'))
    with pytest.raises(Blocked):
        fetch.fetch_related_searches("wedding")
    site(Answer(200, '{"url":"https://geo.captcha-delivery.com/interstitial/?x"}'))
    with pytest.raises(Blocked):
        fetch.fetch_related_searches("wedding")


def test_typeahead(site):
    session = site(Answer(200, raw("typeahead_cof.js"), "application/javascript"))
    assert len(fetch.fetch_typeahead("cof")["hits"]) == 10
    assert session.calls[0][2]["params"] == {"callback": "cb", "language_id": 2, "query": "cof", "ff_1127001950": 1}
    site(Answer(200, raw("typeahead_none.js"), "application/javascript"))
    assert fetch.fetch_typeahead("zxqvjkwp")["hits"] == []
    site(Answer(200, "", "application/javascript"))        # what the site answers without `callback`
    with pytest.raises(UpstreamError):
        fetch.fetch_typeahead("cof")


@pytest.mark.parametrize("text, expected", [
    ('cb({"hits": []})', {"hits": []}), (' cb({"a": 1}); ', {"a": 1}), ("", None), ("cb(", None), ('{"a": 1}', None),
    ("cb(not json)", None), (None, None),
])
def test_unwrap_jsonp(text, expected):
    assert fetch.unwrap_jsonp(text) == expected


def test_error_classes():
    assert issubclass(fetch.AdobeStockBlocked, Blocked) and issubclass(fetch.AdobeStockBlocked, fetch.AdobeStockUpstreamError)
    assert issubclass(fetch.AdobeStockUpstreamError, UpstreamError)
    assert issubclass(fetch.AdobeStockBadRequest, BadRequest) and issubclass(fetch.AdobeStockNotFound, NotFound)
    assert fetch.search_api_error({"error": " x ", "code": "1"}) == "x" and fetch.search_api_error({"files": []}) is None
    assert fetch.search_api_error([{"id": 1}]) is None
