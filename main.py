"""Use the scraper straight from Python, no server needed.

    python main.py

Each call validates its params with the same schema the API uses (so the
defaults apply) and returns the same JSON the API does, except that a list
keeps its `pagination` block instead of next / previous links. The results
are written to output/*.json.
"""
import json
import os

from adobe_stock import api, schemas
from schema_fields import load_query

os.makedirs("output", exist_ok=True)


def run(schema_cls, impl, **params):
    data, error = load_query(schema_cls, {k: str(v) for k, v in params.items()})
    if error:
        raise ValueError(error)
    return impl(**data)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # an asset id or any stock.adobe.com asset link: title, keywords, category, contributor, downloads, sizes with credits, licenses, previews
    save("assets_details.json", run(schemas.AssetsDetailsSchema, api.assets_details, asset='209705645'))

    # the suggestions Adobe Stock's own search box shows for the start of a term, plus its related searches
    save("assets_suggestions.json", run(schemas.AssetsSuggestionsSchema, api.assets_suggestions, query='new york'))

    # up to 100 photos, illustrations, vectors and videos per page with title, keywords, downloads and contributor; 25+ filters
    save("assets_search.json", run(schemas.AssetsSearchSchema, api.assets_search, query='new york city'))
