"""Cache TTL per /adobe-stock/* surface (cache.py, keyed on the validated
params).
"""
from datetime import timedelta

# assets/search, assets/similar, contributors/assets, audio/search: a
# result page moves as assets are added (about 90,000 a week match
# "coffee") and as download counts shift the ranking; an hour keeps a
# pager's pages consistent with each other
LISTING_CACHE = timedelta(hours=1)
# assets/details and assets/bulk: an asset's record changes only in its
# download and view counters, which move by a few a day
ASSET_CACHE = timedelta(hours=6)
# the contributor block of a portfolio (id, name, country): a contributor
# renames rarely
CONTRIBUTOR_CACHE = timedelta(hours=24)
# categories/list: the category tree is fixed (21 top categories)
CATEGORIES_CACHE = timedelta(days=7)
# assets/suggestions: the typeahead index and the related searches follow
# what people search for, slowly
SUGGESTIONS_CACHE = timedelta(hours=24)
