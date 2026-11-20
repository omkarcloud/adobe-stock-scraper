"""Configuration for the Adobe Stock Scraper. Everything can be set with an environment
variable; the defaults work out of the box.

    PORT                port the API listens on (default 8000)
    ADOBE_STOCK_PROXY   proxy URL for every request, e.g. http://user:pass@host:port
                        (default: none, requests go out from your own connection).
                        Adobe Stock's own JSON calls answer home, office, cloud and
                        datacenter connections alike, so you don't need a proxy:
                        your own connection is all it needs. Set one only if your
                        server's address is ever refused.

Everything else below is a plain constant with a working default.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

ADOBE_STOCK_PROXY = os.environ.get("ADOBE_STOCK_PROXY") or None


# ---- what the code reads off config: defaults for a direct run ----
ADOBE_STOCK_CLIENT_ID = 'AdobeStockClient2'     # the website's own client id: every visitor's browser sends it
ADOBE_STOCK_DETAILS_SEARCH_API_ROW = True       # assets/details adds the asset's search API row (file size, watermarked previews, license kinds, stock id): one more call. False: the GraphQL record only
ADOBE_STOCK_EXIT = ADOBE_STOCK_PROXY      # the exit every session leaves through: your proxy, or direct
ADOBE_STOCK_GRAPHQL_FALLBACK = True             # a keyword search the search API fails on is asked from the site's own GraphQL search (same engine, same ranking)
ADOBE_STOCK_SHOW_STATS = True                   # download and view counts. False answers them as null
ADOBE_STOCK_UNMARKED_VIDEO_PREVIEW = False      # True adds a video's 700 px preview file without the "_ST" mark as video.unmarked_preview_link
MAX_RETRIES = 3
RETRY_BACKOFF = 2
