"""Adobe Stock transport: plain curl_cffi with chrome TLS on the JSON calls
behind stock.adobe.com. No browser, no login and no cookie. One session
per request thread on the exit config.ADOBE_STOCK_EXIT names (the server's
own IP in production); a retryable failure drops the session, so the retry
rides a fresh connection.

Four upstreams (every surface answered 200 on 2026-11-20). All of them are
called with the website's own client id, `AdobeStockClient2`, which every
visitor's browser sends:

  the search API     GET https://stock.adobe.io/Rest/Media/1/Search/Files
      search_parameters[words|creator_id|similar|similar_url|media_id|
      category|serie_id|limit|offset|order] and [filters][...], with the
      columns to answer in result_columns[]. At most 100 rows a call and
      the first 10,000 results of a query; past them it answers its last
      window again (queries.window keeps a page inside). What it does with
      a wrong value:
        an unknown filter value or sort     ignored: the unfiltered answer
        a creator_id that is not a number   ignored: the whole catalog
        an unknown creator_id               HTTP 400 "Invalid creator_id value."
        an unknown `similar` id             HTTP 400 "... Invalid or not supported contentId"
        an unknown media_id                 HTTP 200, no rows
      so every value is validated before it is sent (schemas.py).
      A search without a content type leaves templates and 3D out, and so
      does media_id: a template or 3D asset is found only with its type.
    GET .../Search/CategoryTree[?category_id=]   the root categories, or a
      category's children. GET .../Search/Category?category_id= one category.

  the GraphQL API    POST https://stock.adobe.com/graphql, the call the
      site's own pages make (DataDome fronts the host; this call passes
      without a cookie)
      getAssetDetails(_ids)      the full record of up to 500 assets in one
                                 call, any kind. An unknown id is simply
                                 absent; none found answers null.
      getSearchResults(params)   the site's search. It is the audio search
                                 (the search API has no audio) and the
                                 fallback for a keyword search.
      An error of one field comes with HTTP 200 next to the data (one
      template's `resolution`): the row is kept. "Invalid Search Input"
      names a filter the server refused.

  related searches   POST https://stock.adobe.com/QuerySuggestion with the
      body the search page sends (its full `filters` object: without it
      the answer is the literal `null`). Five phrases, or null.

  typeahead          GET https://autocomplete.fotolia.com/?callback=...
      JSONP, ten terms. Without `callback` the body is empty.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  AdobeStockUpstreamError  transport failure / 5xx / unexpected body   retryable
  AdobeStockBlocked        401 / 403 / 429 / a challenge page          retryable
  AdobeStockBadRequest     the site rejected the parameters            never retried
  AdobeStockNotFound       unknown asset / contributor / category      never retried
"""
import json
import re
import threading

import config
import egress
from adobe_stock import queries
from adobe_stock.refs import SITE
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from scraper_utils import retry, sessions

IMPERSONATE = "chrome"
API_TIMEOUT = 25
BULK_TIMEOUT = 45           # 100 full records took 1.5 s, 500 took 4.5 s

SEARCH_API = "https://stock.adobe.io/Rest/Media/1/Search"
GRAPHQL = SITE + "/graphql"
RELATED_SEARCHES = SITE + "/QuerySuggestion"
TYPEAHEAD = "https://autocomplete.fotolia.com/"
TYPEAHEAD_LANGUAGE = 2      # the site's own language id for English (autocomplete_language_id in its page config)
TYPEAHEAD_CALLBACK = "cb"

# The search API. No page of the site makes this call for a search; the
# headers are the ones that passed from the pod on every exit (2026-11-20).
SEARCH_API_HEADERS = {
    "accept": "application/json",
    "origin": SITE,
    "referer": SITE + "/",
    "x-product": "AdobeStock/1.0",
}

# The GraphQL call, as the asset page sends it (its referer is the page).
GRAPHQL_HEADERS = {
    "accept": "*/*",
    "apollographql-client-name": "stock-search-app",
    "content-type": "application/json",
    "origin": SITE,
    "priority": "u=1, i",
    "sec-ch-prefers-color-scheme": "light",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

# The related-searches call, as the search page sends it.
RELATED_HEADERS = {
    "accept": "application/json, text/javascript, */*; q=0.01",
    "content-type": "application/json",
    "origin": SITE,
    "priority": "u=1, i",
    "sec-ch-prefers-color-scheme": "light",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "x-requested-with": "XMLHttpRequest",
}

# The `filters` object the search page posts with a related-searches call.
RELATED_FILTERS = {
    "content_type:photo": 1, "content_type:illustration": 1, "content_type:zip_vector": 1,
    "content_type:video": 1, "content_type:template": 1, "content_type:3d": 1, "content_type:audio": 0,
    "include_stock_enterprise": 0, "is_editorial": 0, "content_type:image": 1, "free_collection": 0,
}

TYPEAHEAD_HEADERS = {"accept": "*/*", "referer": SITE + "/"}

_JSONP_RE = re.compile(r"^\s*[A-Za-z_$][\w$]*\((.*)\)\s*;?\s*$", re.S)


class AdobeStockUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unexpected payload — retryable."""


class AdobeStockBlocked(AdobeStockUpstreamError, Blocked):
    """401 / 403 / 429, or a challenge where JSON was expected — retryable."""


class AdobeStockBadRequest(BadRequest):
    """The site rejected the parameters — never retried."""


class AdobeStockNotFound(NotFound):
    """No such asset, contributor or category — never retried."""


# ---- sessions ------------------------------------------------------------------------

# One curl session per request thread (a curl handle must not be shared
# across threads). No call needs a cookie or a token; the session keeps the
# cookies the site sets and sends them back, as a browser does (the 1,250
# calls of the research ran that way without a refusal).
_local = threading.local()


def _session():
    return sessions.thread_session(
        _local, lambda: egress.exit_session(config.ADOBE_STOCK_EXIT, impersonate=IMPERSONATE))


def _drop_session():
    """Close the thread's session so the retry rides a fresh connection / exit."""
    sessions.drop(_local)


def _retrying(fn):
    """fn() under the shared retry policy: only AdobeStockUpstreamError
    (Blocked included) is retried; NotFound and BadRequest surface at once."""
    return retry.run(fn, config, AdobeStockUpstreamError, lambda e: _drop_session())


def _client_headers(headers):
    return {**headers, "x-api-key": config.ADOBE_STOCK_CLIENT_ID}


# ---- one request ---------------------------------------------------------------------

def _send(method, url, label, **kw):
    try:
        resp = _session().request(method, url, **kw)
    except Exception as e:
        raise AdobeStockUpstreamError(f"request failed for {label}: {type(e).__name__}: {e}")
    return resp


def _decoded(resp, label):
    try:
        return resp.json()
    except Exception:
        raise AdobeStockBlocked(f"non-JSON answer for {label}: {resp.text[:120]!r}")


def _refused(resp, label):
    """A status that is the site refusing the caller, not the request."""
    status = resp.status_code
    if status in (401, 403, 429):
        raise AdobeStockBlocked(f"HTTP {status} for {label}")
    if status >= 500:
        raise AdobeStockUpstreamError(f"HTTP {status} for {label}")


# ---- the search API ------------------------------------------------------------------

def search_api_error(payload):
    """The message of the search API's {"error", "code", "case"} body, or None."""
    if isinstance(payload, dict) and isinstance(payload.get("error"), str):
        return payload["error"].strip()[:300]
    return None


def _search_api(path, pairs, label, not_found=()):
    """GET a search API path -> the decoded JSON. `not_found` lists the
    texts of an error message that mean the record does not exist (the
    API says so with HTTP 400 on one path and HTTP 500 on another, so the
    message is read before the status)."""
    def once():
        resp = _send("GET", f"{SEARCH_API}/{path}", label, params=pairs,
                     headers=_client_headers(SEARCH_API_HEADERS), timeout=API_TIMEOUT)
        status = resp.status_code
        if status in (401, 403, 429):
            raise AdobeStockBlocked(f"HTTP {status} for {label}")
        try:
            payload = resp.json()
        except Exception:
            if status >= 500:
                raise AdobeStockUpstreamError(f"HTTP {status} for {label}")
            raise AdobeStockBlocked(f"non-JSON answer for {label}: {resp.text[:120]!r}")
        message = search_api_error(payload)
        if message is not None:
            if any(text in message for text in not_found):
                raise AdobeStockNotFound(f"{label} not found")
            if status == 400:
                raise AdobeStockBadRequest(message)
            raise AdobeStockUpstreamError(f"HTTP {status} for {label}: {message}")
        if status != 200:
            raise AdobeStockUpstreamError(f"HTTP {status} for {label}")
        return payload
    return _retrying(once)


def fetch_search(pairs, label, not_found=()):
    """One call of Search/Files -> {"nb_results", "files"}."""
    payload = _search_api("Files", pairs, label, not_found)
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise AdobeStockUpstreamError(f"{label} answered no rows: {str(payload)[:120]!r}")
    return payload


def fetch_category_children(category=None, locale="en_US"):
    """The root categories, or the children of one -> the raw list."""
    pairs = [("locale", locale)]
    if category:
        pairs.append(("category_id", category))
    payload = _search_api("CategoryTree", pairs, f"categories of {category or 'the root'}",
                          not_found=("Invalid Category",))
    if not isinstance(payload, list):
        raise AdobeStockUpstreamError(f"categories answered no list: {str(payload)[:120]!r}")
    return payload


def fetch_category(category, locale="en_US"):
    """One category's own record ({id, name, link}). Unknown id -> NotFound."""
    payload = _search_api("Category", [("locale", locale), ("category_id", category)], f"category {category}",
                          not_found=("Invalid Category",))
    if not isinstance(payload, dict) or "id" not in payload:
        raise AdobeStockUpstreamError(f"category {category} answered no record: {str(payload)[:120]!r}")
    return payload


# ---- the GraphQL API -----------------------------------------------------------------

def graphql_messages(payload):
    """The messages of a GraphQL answer's errors."""
    errors = payload.get("errors") if isinstance(payload, dict) else None
    return [str(e.get("message") or "") for e in errors or [] if isinstance(e, dict)]


def _graphql(body, label, referer, timeout=API_TIMEOUT):
    """POST one operation -> its `data`. A refused filter is a BadRequest;
    errors of single fields next to the data are left to the parser."""
    def once():
        headers = _client_headers({**GRAPHQL_HEADERS, "referer": referer})
        resp = _send("POST", GRAPHQL, label, data=json.dumps(body), headers=headers, timeout=timeout)
        _refused(resp, label)
        payload = _decoded(resp, label)
        if not isinstance(payload, dict):
            raise AdobeStockUpstreamError(f"unexpected payload for {label}: {resp.text[:120]!r}")
        messages = graphql_messages(payload)
        refused = [m for m in messages if m.startswith(("Invalid Search Input", "Could not create filter"))]
        if refused:
            raise AdobeStockBadRequest(refused[0][:300])
        data = payload.get("data")
        if resp.status_code != 200 or not isinstance(data, dict):
            raise AdobeStockUpstreamError(f"HTTP {resp.status_code} for {label}: {'; '.join(messages)[:200]}")
        if messages and any(value is None for value in data.values()):
            # the operation itself failed: its field is null next to the errors
            # (for getAssetDetails that would read as "none of the ids exist")
            raise AdobeStockUpstreamError(f"{label} failed: {'; '.join(messages)[:200]}")
        return data
    return _retrying(once)


def fetch_assets(asset_ids, locale="en_US"):
    """The full records of the ids -> the raw rows the site knows (an
    unknown id is absent; none found answers an empty list)."""
    label = f"assets {','.join(asset_ids)[:60]}"
    data = _graphql(queries.details_body(asset_ids, locale), label, f"{SITE}/{asset_ids[0]}",
                    timeout=BULK_TIMEOUT if len(asset_ids) > 20 else API_TIMEOUT)
    rows = data.get("getAssetDetails")
    return rows if isinstance(rows, list) else []


def fetch_graphql_search(filters, page, limit, sort, locale, referer):
    """One page of the site's own search -> the raw getSearchResults object."""
    data = _graphql(queries.search_body(filters, page, limit, sort, locale), "search", referer)
    result = data.get("getSearchResults")
    if not isinstance(result, dict) or not isinstance(result.get("assets"), list):
        raise AdobeStockUpstreamError(f"search answered no rows: {str(data)[:120]!r}")
    return result


# ---- suggestions ---------------------------------------------------------------------

def fetch_related_searches(query):
    """The search page's related searches -> a list of phrases ([] when
    the site has none: it answers the literal null)."""
    label = f"related searches {query!r}"

    def once():
        body = {"filters": RELATED_FILTERS, "k": query}
        resp = _send("POST", RELATED_SEARCHES, label, data=json.dumps(body),
                     headers={**RELATED_HEADERS, "referer": f"{SITE}/search"}, timeout=API_TIMEOUT)
        _refused(resp, label)
        if resp.status_code != 200:
            raise AdobeStockUpstreamError(f"HTTP {resp.status_code} for {label}")
        payload = _decoded(resp, label)
        if isinstance(payload, dict) and "url" in payload:      # the bot manager's JSON challenge
            raise AdobeStockBlocked(f"challenge for {label}")
        return payload if isinstance(payload, list) else []
    return _retrying(once)


def unwrap_jsonp(text):
    """'cb({...})' -> the decoded object; None when it is not JSONP."""
    match = _JSONP_RE.match(text or "")
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None


def fetch_typeahead(query):
    """The search box's typeahead -> the raw {"hits": [...]} object."""
    label = f"typeahead {query!r}"

    def once():
        params = {"callback": TYPEAHEAD_CALLBACK, "language_id": TYPEAHEAD_LANGUAGE, "query": query,
                  "ff_1127001950": 1}
        resp = _send("GET", TYPEAHEAD, label, params=params, headers=TYPEAHEAD_HEADERS, timeout=API_TIMEOUT)
        _refused(resp, label)
        payload = unwrap_jsonp(resp.text) if resp.status_code == 200 else None
        if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
            raise AdobeStockUpstreamError(f"unexpected {label} answer (HTTP {resp.status_code}): {resp.text[:120]!r}")
        return payload
    return _retrying(once)
