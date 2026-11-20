"""Offline tests for adobe_stock/parsers.py against the raw captures in
fixtures/ (taken 2026-11-20 through fetch.py, untrimmed).

    python -m pytest adobe_stock/test_parsers.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adobe_stock import fetch, parsers, refs  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")

ASSET_KEYS = [
    "id", "title", "link", "type", "format", "mime_type", "file_extension", "description", "keywords",
    "category", "category_path", "contributor", "created_at", "dimensions", "file_size_bytes", "stats",
    "is_ai_generated", "ai_prompt", "is_premium", "is_free", "premium_level", "is_editorial",
    "is_editorial_use_only", "is_transparent", "has_releases", "is_available_with_subscription",
    "thumbnail", "thumbnails", "watermarked_previews", "sizes", "licenses", "stock_id",
    "video", "vector_type", "icon_type", "template", "three_d_type", "audio",
]


def raw(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def load(name):
    return json.loads(raw(name))


def page(name, limit=5, with_stats=True):
    return parsers.parse_search_page(load(name), 1, limit, with_stats)


def rows(name, limit=5):
    return page(name, limit)["results"]


def record(name, index=0, with_stats=True):
    return parsers.parse_graphql_asset(load(name)["data"]["getAssetDetails"][index], with_stats)


def graphql_page(name, limit=5):
    return parsers.parse_graphql_search(load(name)["data"]["getSearchResults"], 1, limit)


# ---- the search API: a result page ---------------------------------------------------

def test_search_page():
    listing = page("search_coffee.json", 8)
    assert listing["pagination"] == {"page": 1, "items_per_page": 8, "total_count": 16014776, "total_pages": 1250}
    assert [r["id"] for r in listing["results"]] == [94143804, 224982353, 129973255, 267568050, 248668319,
                                                      206899395, 263601965, 159183621]
    assert all(list(r) == ASSET_KEYS for r in listing["results"])


def test_search_row_photo():
    row = rows("search_coffee.json", 8)[0]
    assert row["id"] == 94143804
    assert row["title"] == "cup of coffee latte in coffee shop"
    assert row["link"] == "https://stock.adobe.com/94143804"
    assert (row["type"], row["format"], row["mime_type"]) == ("photo", "jpeg", "image/jpeg")
    assert row["keywords"] == ["hot drink", "latte", "art", "cafes", "drink", "hot", "cup", "espresso", "shop"]
    assert row["category"] == {"id": 230, "name": "Coffee"}
    assert row["category_path"] == [{"id": 214, "name": "Drinks"}, {"id": 229, "name": "Hot Drinks"},
                                    {"id": 230, "name": "Coffee"}]
    assert row["contributor"] == {"id": 203434592, "name": "chayathon2000", "country": "Thailand",
                                  "link": "https://stock.adobe.com/contributor/203434592/chayathon2000"}
    # the site prints Paris time ("2015-10-22 13:57:38"): two hours ahead of UTC in October
    assert row["created_at"] == "2015-10-22T11:57:38Z"
    assert row["dimensions"] == {"width": 4928, "height": 3280}
    assert row["file_size_bytes"] == 3980840
    assert row["stats"] == {"downloads": 3052, "views": 19}
    assert (row["is_ai_generated"], row["is_premium"], row["is_free"], row["premium_level"]) == (False, False, False, 0)
    assert (row["is_editorial"], row["is_editorial_use_only"], row["is_transparent"], row["has_releases"]) == (
        False, False, False, False)
    assert row["is_available_with_subscription"] is None        # only the full record says
    assert row["thumbnail"] == "https://as1.ftcdn.net/v2/jpg/00/94/14/38/500_F_94143804_QFuKnDxb29Crj61iuBClT9wQPErPfGsw.jpg"
    assert [t["size"] for t in row["thumbnails"]] == [110, 160, 220, 240, 500, 1000]
    assert row["thumbnails"][3]["width"] == 361             # the site prints 360.9022...
    assert row["thumbnails"][0] == {"size": 110, "width": 110, "height": 73,
                                    "link": "https://as1.ftcdn.net/jpg/00/94/14/38/110_F_94143804_QFuKnDxb29Crj61iuBClT9wQPErPfGsw.jpg"}
    assert row["watermarked_previews"] == [
        {"name": "Standard", "width": 1000, "height": 665,
         "link": "https://stock.adobe.com/Rest/Libraries/Watermarked/Download/94143804/1"},
        {"name": "Preview", "width": 1000, "height": 665,
         "link": "https://stock.adobe.com/Rest/Libraries/Watermarked/Download/94143804/2"}]
    assert row["licenses"] == [{"name": "Standard", "width": 4928, "height": 3280},
                               {"name": "Enhanced", "width": 4928, "height": 3280}]
    assert row["stock_id"] == "QFuKnDxb29Crj61iuBClT9wQPErPfGsw"
    assert row["sizes"] is None and row["video"] is None and row["template"] is None and row["audio"] is None


def test_search_row_has_no_html_and_no_tracking_link():
    text = json.dumps(page("search_coffee.json", 8))
    assert "<img" not in text and "as_channel" not in text and "thumbnail_html_tag" not in text


def test_search_page_two_and_no_result():
    second = parsers.parse_search_page(load("search_coffee_page2.json"), 2, 8)
    assert second["pagination"]["page"] == 2 and second["results"][0]["id"] == 129936834
    first_ids = {r["id"] for r in rows("search_coffee.json", 8)}
    assert not first_ids & {r["id"] for r in second["results"]}
    empty = page("search_no_result.json", 100)
    assert empty == {"results": [], "pagination": {"page": 1, "items_per_page": 100, "total_count": 0, "total_pages": 0}}


def test_search_past_the_end_and_the_last_rows():
    past = parsers.parse_search_page(load("search_past_end.json"), 121, 5)
    assert past["results"] == [] and past["pagination"]["total_count"] == 482 and past["pagination"]["total_pages"] == 97
    last = parsers.parse_search_page(load("search_last_rows.json"), 97, 5)
    assert [r["id"] for r in last["results"]] == [309241691, 309241455]


def test_pages_stop_at_the_ten_thousand_results_the_search_reaches():
    listing = parsers.parse_search_page(load("search_coffee.json"), 1, 100)
    assert listing["pagination"]["total_count"] == 16014776 and listing["pagination"]["total_pages"] == 100
    assert parsers.empty_page(101, 100, 16014776) == {
        "results": [], "pagination": {"page": 101, "items_per_page": 100, "total_count": 16014776, "total_pages": 100}}
    assert parsers.empty_page(3, 10)["pagination"]["total_pages"] == 0


def test_stats_can_be_switched_off():
    row = page("search_coffee.json", 8, with_stats=False)["results"][0]
    assert row["stats"] == {"downloads": None, "views": None}
    assert record("assets_photo_841165203.json", with_stats=False)["stats"] == {"downloads": None, "views": None}


# ---- the search API: one row per kind ------------------------------------------------

def test_search_row_video():
    row = rows("search_video.json")[0]
    assert (row["id"], row["type"], row["format"], row["mime_type"]) == (481358641, "video", "quicktime", "video/quicktime")
    assert row["created_at"] == "2022-01-19T11:11:26Z"           # 12:11:26 in Paris, winter time
    assert row["dimensions"] == {"width": 4096, "height": 2160} and row["file_size_bytes"] == 584624484
    video = row["video"]
    assert (video["duration_seconds"], video["frame_rate"], video["is_loop"], video["codec"]) == (38.75, 24, False, None)
    assert list(video) == ["duration_seconds", "frame_rate", "codec", "container", "is_loop", "preview_link",
                           "small_preview_link", "renditions"]
    assert video["preview_link"] == "https://v.ftcdn.net/04/81/35/86/700_F_481358641_4uyOioGYFnr84S6nC5u1XxTGQa8qN2ui_ST.mp4"
    assert video["small_preview_link"].endswith("/240_F_481358641_4uyOioGYFnr84S6nC5u1XxTGQa8qN2ui_ST.mp4")
    assert video["renditions"][0] == {"name": "preview", "link": video["preview_link"], "width": 700, "height": 370,
                                      "size_bytes": 5952643, "bitrate_kbps": None, "codec": None, "mime_type": "video/mp4"}
    assert [p["name"] for p in row["watermarked_previews"]] == ["Video_HD", "Video_4K"]
    assert row["watermarked_previews"][1] == {"name": "Video_4K", "width": 4096, "height": 2160,
                                              "link": "https://stock.adobe.com/Rest/Libraries/Watermarked/Download/481358641/4"}
    assert row["licenses"] == []


def test_search_row_looping_video():
    video = rows("search_video_loop.json")[0]["video"]
    assert (video["is_loop"], video["duration_seconds"], video["frame_rate"]) == (True, 10.01, 23.976)


def test_search_row_vector_and_icon():
    vector = rows("search_vector.json")[0]
    assert (vector["id"], vector["type"], vector["vector_type"], vector["mime_type"]) == (
        245914492, "vector", "zip", "application/illustrator")
    assert vector["format"] is None and vector["icon_type"] is None
    icon = rows("search_icon.json")[0]
    assert (icon["id"], icon["type"], icon["icon_type"]) == (206388213, "vector", "single")


def test_search_row_illustration_made_with_ai():
    row = rows("search_illustration.json")[0]
    assert (row["id"], row["type"], row["is_ai_generated"], row["is_transparent"]) == (614722086, "illustration", True, True)
    assert row["ai_prompt"] is None


def test_search_row_template():
    row = rows("search_template.json")[0]
    assert (row["id"], row["type"], row["mime_type"]) == (196235209, "template", "application/illustrator.template")
    assert row["template"] == {"app": "Illustrator", "categories": [{"id": 3, "name": "Print"}],
                               "preview_images": None, "preview_videos": None}
    # the site's light markdown ("##### A business flyer...", "* A4 size") as plain lines
    assert row["description"].split("\n")[:3] == [
        "A business flyer layout with colorful elements in three color palettes.", "- A4 size", "- 3 color options"]
    assert "#" not in row["description"] and "*" not in row["description"]
    motion = rows("search_motion_template.json")[0]
    assert motion["template"]["app"] == "Premiere Pro"
    assert motion["template"]["categories"] == [{"id": 8, "name": "Titles/Text Overlays"}]
    assert motion["video"] is None


def test_search_row_3d():
    row = rows("search_3d.json")[0]
    assert (row["id"], row["type"], row["three_d_type"]) == (392281290, "3d", "model")
    assert row["mime_type"] == "application/vnd.adobe.obj.3d+zip"


def test_search_row_premium():
    row = rows("search_premium.json")[0]
    assert (row["id"], row["is_premium"], row["is_free"], row["premium_level"]) == (382272282, True, False, 3)


def test_the_premium_filter_counts_every_video_as_premium():
    """Why queries.implied_types keeps a premium search to pictures: asked
    with photos and videos, the rows the site calls premium..."""
    payload = load("search_premium_with_videos.json")
    assert {f["media_type_id"] for f in payload["files"]} == {1}
    # ...are pictures here only because pictures outrank the videos; the count below is of photos alone
    assert payload["nb_results"] == 162147


def test_search_row_in_german():
    row = parsers.parse_search_page(load("search_locale_de.json"), 1, 2)["results"][0]
    assert row["keywords"][:3] == ["tassen", "kaffee", "balken"]
    assert row["category"] == {"id": 214, "name": "Getränke"} and row["contributor"]["country"] == "Italien"


def test_portfolio_rows_and_their_contributor():
    listing = page("search_contributor.json")
    assert listing["pagination"]["total_count"] == 14817
    assert [(r["id"], r["type"]) for r in listing["results"]][:3] == [(94143804, "photo"), (131053005, "photo"),
                                                                      (303876556, "video")]
    assert parsers.first_contributor(listing["results"]) == {
        "id": 203434592, "name": "chayathon2000", "country": "Thailand",
        "link": "https://stock.adobe.com/contributor/203434592/chayathon2000"}
    assert parsers.first_contributor([]) is None


def test_similar_rows():
    assert [r["id"] for r in rows("search_similar.json")][:2] == [94144339, 1035484139]
    assert rows("search_similar_image.json")[0]["id"] == 1008863731


def test_series_and_category_rows():
    series = page("search_series.json")
    assert series["pagination"]["total_count"] == 3451
    assert {r["contributor"]["id"] for r in series["results"]} == {203434592}      # a series is one contributor's
    category = page("search_category.json")
    assert [r["id"] for r in category["results"]] == [296714147, 265580176]
    assert all({"id": 596, "name": "Landscapes"} in r["category_path"] for r in category["results"])


def test_a_count_only_answer():
    listing = parsers.parse_search_page(load("search_count_only.json"), 1, 1)
    assert listing["pagination"]["total_count"] == 16014485
    assert listing["results"][0]["id"] == 94143804 and listing["results"][0]["title"] is None


def test_one_asset_by_id():
    row = rows("search_asset_841165203.json", 1)[0]
    assert (row["id"], row["file_size_bytes"], row["stock_id"]) == (841165203, 7128031, "VZjtdfVTdJV8sGsc1J5IPQ6b17jItZPP")
    assert rows("search_asset_template.json", 1)[0]["id"] == 2244142596
    assert rows("search_asset_3d.json", 1)[0]["three_d_type"] == "model"
    # an unknown id, a template asked for without its type, a track and an
    # editorial-use asset: the search API has no row
    for name in ("search_asset_not_found.json", "search_asset_template_plain.json", "search_asset_audio.json",
                 "search_asset_editorial_use_no_row.json"):
        assert rows(name, 1) == []


def test_a_partial_row_gives_a_partial_asset():
    row = parsers.parse_search_row({"id": "12", "media_type_id": 4, "keywords": [{"name": " a "}, {}, None]})
    assert list(row) == ASSET_KEYS
    assert (row["id"], row["type"], row["keywords"]) == (12, "video", ["a"])
    assert row["video"]["renditions"] == [] and row["contributor"]["link"] is None
    assert parsers.parse_search_row(None)["id"] is None
    assert parsers.parse_search_page({}, 1, 10)["results"] == []


# ---- the GraphQL record --------------------------------------------------------------

def test_record_photo():
    asset = record("assets_photo_841165203.json")
    assert list(asset) == ASSET_KEYS
    assert (asset["id"], asset["type"], asset["format"], asset["mime_type"], asset["file_extension"]) == (
        841165203, "photo", "jpeg", "image/jpeg", "jpg")
    assert asset["title"] == "Anime Style Watercolor Night Sky Background"
    assert asset["link"] == "https://stock.adobe.com/841165203"
    assert len(asset["keywords"]) == 27 and asset["keywords"][:3] == ["anime", "watercolor", "night sky"]
    assert asset["category"] == {"id": 596, "name": "Landscapes"} and asset["category_path"] == [asset["category"]]
    assert asset["contributor"] == {"id": 210445386, "name": "Eva13186707", "country": "Bangladesh",
                                    "link": "https://stock.adobe.com/contributor/210445386/Eva13186707"}
    assert asset["created_at"] == "2024-06-06T04:57:05Z"         # epoch seconds "1717649825.254689"
    assert asset["dimensions"] == {"width": 5824, "height": 3264}
    assert asset["stats"] == {"downloads": 18, "views": 0}
    assert (asset["is_ai_generated"], asset["is_premium"], asset["is_free"], asset["premium_level"]) == (True, False, False, 0)
    assert asset["is_available_with_subscription"] is True
    assert asset["thumbnail"].endswith("/500_F_841165203_VZjtdfVTdJV8sGsc1J5IPQ6b17jItZPP.jpg")
    assert [t["size"] for t in asset["thumbnails"]] == [110, 160, 220, 240, 360, 500, 1000]
    assert [s["name"] for s in asset["sizes"]] == ["XS", "S", "M", "L", "XL", "XXL", "X"]
    assert asset["sizes"][0] == {"name": "XS", "width": 463, "height": 259, "dpi": 72, "credits": 1}
    assert asset["sizes"][-1] == {"name": "X", "width": 5824, "height": 3264, "dpi": 300, "credits": 30}
    # what only the search API row carries
    assert asset["file_size_bytes"] is None and asset["watermarked_previews"] is None
    assert asset["licenses"] is None and asset["stock_id"] is None


def test_the_same_asset_from_both_upstreams_agrees():
    a, b = record("assets_photo_841165203.json"), rows("search_asset_841165203.json", 1)[0]
    for key in ("id", "title", "link", "type", "format", "mime_type", "category", "category_path", "contributor",
                "created_at", "dimensions", "stats", "is_ai_generated", "is_premium", "is_free", "premium_level",
                "is_editorial", "is_editorial_use_only", "is_transparent", "has_releases"):
        assert a[key] == b[key], key
    assert a["keywords"] == list(dict.fromkeys(a["keywords"])) == b["keywords"]


def test_merge_adds_what_only_the_row_carries():
    merged = parsers.merge_asset(record("assets_photo_841165203.json"), rows("search_asset_841165203.json", 1)[0])
    assert list(merged) == ASSET_KEYS
    assert merged["file_size_bytes"] == 7128031 and merged["stock_id"] == "VZjtdfVTdJV8sGsc1J5IPQ6b17jItZPP"
    assert merged["watermarked_previews"][0]["link"].endswith("/Watermarked/Download/841165203/1")
    assert [lic["name"] for lic in merged["licenses"]] == ["Standard", "Enhanced"]
    assert len(merged["sizes"]) == 7 and merged["file_extension"] == "jpg"        # the record's own values stay
    video = parsers.merge_asset(record("assets_video_481358641.json"), rows("search_asset_video.json", 1)[0])
    assert video["video"]["is_loop"] is False and video["video"]["codec"] == "h264" and len(video["video"]["renditions"]) == 8
    assert video["file_size_bytes"] == 584624484
    template = parsers.merge_asset(record("assets_template_2244142596.json"), rows("search_asset_template.json", 1)[0])
    assert template["template"]["app"] == "Photoshop" and isinstance(template["template"]["categories"], list)
    threed = parsers.merge_asset(record("assets_3d_417655015.json"), rows("search_asset_3d.json", 1)[0])
    assert threed["three_d_type"] == "model" and threed["file_size_bytes"] == 7721505
    assert parsers.merge_asset(record("assets_photo_841165203.json"), None) == record("assets_photo_841165203.json")


def test_record_in_german():
    asset = record("assets_photo_94143804_de.json")
    assert asset["keywords"][:3] == ["kaffee", "milchkaffee", "kunst"] and asset["category"] == {"id": 230, "name": "Kaffee"}


def test_record_illustration_and_vector():
    illustration = record("assets_illustration_600525660.json")
    assert (illustration["type"], illustration["is_transparent"], illustration["mime_type"]) == ("illustration", True, "image/png")
    vector = record("assets_vector_245914492.json")
    assert (vector["type"], vector["format"], vector["vector_type"], vector["file_extension"]) == ("vector", "ai/eps", "zip", "zip")
    assert vector["dimensions"] == {"width": 4500, "height": 4500} and vector["stats"] == {"downloads": 3393, "views": 25}


def test_record_video():
    asset = record("assets_video_481358641.json")
    assert (asset["type"], asset["format"], asset["mime_type"], asset["file_extension"]) == ("video", "mp4", "video/mp4", None)
    assert asset["created_at"] == "2022-01-19T11:11:26Z"
    video = asset["video"]
    assert (video["duration_seconds"], video["frame_rate"], video["codec"], video["is_loop"]) == (38.75, 24, "h264", None)
    assert video["container"] == "mpeg4"
    assert list(video) == ["duration_seconds", "frame_rate", "codec", "container", "is_loop", "preview_link",
                           "small_preview_link", "renditions"]
    # the record's videoUrl (the preview file without its "_ST" mark) is not passed on
    assert "4uyOioGYFnr84S6nC5u1XxTGQa8qN2ui.mp4" not in json.dumps(asset)
    assert video["preview_link"].endswith("/700_F_481358641_4uyOioGYFnr84S6nC5u1XxTGQa8qN2ui_ST.mp4")
    assert video["small_preview_link"].endswith("/240_F_481358641_4uyOioGYFnr84S6nC5u1XxTGQa8qN2ui_ST.mp4")
    names = [(r["name"], bool(r["link"])) for r in video["renditions"]]
    # the files a license delivers (4k, full_hd, hd_ready) come without a link
    assert names == [("4k", False), ("comp", True), ("hd_ready", False), ("full_hd", False), ("comp_full_hd", True),
                     ("comp_w1920", True), ("700px", True), ("240px", True)]
    assert video["renditions"][0] == {"name": "4k", "link": None, "width": 4096, "height": 2160, "size_bytes": 584624484,
                                      "bitrate_kbps": 120693, "codec": "h264", "mime_type": None}
    assert asset["thumbnail"].endswith("/500_F_481358641_4uyOioGYFnr84S6nC5u1XxTGQa8qN2ui.jpg")


def test_the_unmarked_video_preview_only_on_request():
    raw_asset = load("assets_video_481358641.json")["data"]["getAssetDetails"][0]
    assert "unmarked_preview_link" not in parsers.parse_graphql_asset(raw_asset)["video"]
    shown = parsers.parse_graphql_asset(raw_asset, unmarked_preview=True)["video"]
    assert shown["unmarked_preview_link"] == "https://v.ftcdn.net/04/81/35/86/700_F_481358641_4uyOioGYFnr84S6nC5u1XxTGQa8qN2ui.mp4"


def test_record_template():
    asset = record("assets_template_2244142596.json")
    assert (asset["type"], asset["format"], asset["mime_type"]) == ("template", "template", "application/vnd.adobe.stock.psdt+zip")
    assert asset["template"]["app"] == "Photoshop" and asset["template"]["categories"] is None
    assert asset["template"]["preview_images"][0] == {
        "link": "https://as2.ftcdn.net/jpg/22/44/14/25/1024W_F_2244142596_DljIX7eBk3hCH8DDt3DazalexoxyMjXp_NW1.jpg",
        "width": 2048, "height": 4115}
    assert len(asset["template"]["preview_images"]) == 3 and asset["template"]["preview_videos"] == []
    assert [t["size"] for t in asset["thumbnails"]] == [110, 220, 240, 360, 400, 500, 1000]
    assert asset["description"].split("\n") == [
        "Template details:", "- RGB", "- 1 design option", "- 4500 x 3000 pixels",
        "- Photos or design elements shown in the preview are for display only and are not included in the downloaded file"]
    assert asset["sizes"] == [{"name": "T", "width": 2048, "height": 1424, "dpi": 72, "credits": 1}]


def test_record_motion_template():
    asset = record("assets_motion_template_2240653450.json")
    assert (asset["type"], asset["format"]) == ("template", "mogrt") and asset["template"]["app"] == "Premiere Pro"
    assert [v["name"] for v in asset["template"]["preview_videos"]] == ["240px", "700px"]
    assert asset["template"]["preview_videos"][1]["link"].endswith("/700_F_2240653450_TuTcKKy8ZGWfAb0tCNgDeCW7Ovt1sU3M.mp4")
    assert asset["video"] is None


def test_record_whose_one_field_failed_is_kept():
    payload = load("assets_template_field_error_222533946.json")
    assert fetch.graphql_messages(payload) == ["Internal server error"]
    asset = record("assets_template_field_error_222533946.json")
    assert (asset["id"], asset["type"], asset["template"]["app"]) == (222533946, "template", "InDesign")


def test_record_3d():
    asset = record("assets_3d_417655015.json")
    assert (asset["type"], asset["three_d_type"], asset["title"]) == ("3d", "model", "Smartphone")
    assert asset["category"] is None and asset["category_path"] == []        # the site answers {id: null, name: null}
    assert asset["sizes"] == [{"name": "3D", "width": 2048, "height": 2048, "dpi": 72, "credits": 1}]


def test_record_audio():
    asset = record("assets_audio_2250132122.json")
    assert list(asset) == ASSET_KEYS
    assert (asset["type"], asset["format"], asset["mime_type"], asset["file_extension"]) == ("audio", "wav", "audio/wav", "wav")
    assert asset["audio"] == {
        "artist": "Dashing Scherzo", "album": "Pop Inspirational", "partner": "FineTune Music",
        "duration_seconds": 91.24, "tempo_bpm": 121, "genres": ["Pop"], "subgenres": ["Electropop", "Europop"],
        "moods": ["Happy", "Powerful", "Dynamic", "Inspiring", "Emotional"], "is_instrumental": True, "is_loop": False,
        "preview_link": "https://audios.ftcdn.net/22/50/13/21/48K_2250132122.m4a",
        "waveform_link": "https://audios.ftcdn.net/22/50/13/21/1000_2250132122.json"}
    assert asset["dimensions"] == {"width": None, "height": None} and asset["thumbnail"] is None and asset["thumbnails"] == []
    assert asset["sizes"] == [{"name": "A", "width": None, "height": None, "dpi": None, "credits": 1}]
    assert asset["contributor"]["link"] == "https://stock.adobe.com/contributor/210481708/Dashing-Scherzo-FineTune-Music"
    assert asset["description"].startswith("Electric guitar chords and a synth riser start the cue.")


def test_record_free_premium_and_editorial_use():
    free, premium = record("assets_free_336674195.json"), record("assets_premium_382272282.json")
    assert (free["is_free"], free["is_premium"], free["premium_level"]) == (True, False, 1)
    assert (premium["is_free"], premium["is_premium"], premium["premium_level"]) == (False, True, 3)
    editorial = record("assets_editorial_use_644781013.json")
    assert editorial["is_editorial_use_only"] is True and editorial["is_editorial"] is False


def test_a_batch_keeps_the_order_asked_and_names_the_unknown():
    payload = load("assets_mixed_found_and_unknown.json")
    wanted = ["94143804", "999999999999", "481358641", "2250132122"]
    parsed = parsers.parse_graphql_assets(payload["data"]["getAssetDetails"], wanted)
    assert [(a["id"], a["type"]) for a in parsed["assets"]] == [(94143804, "photo"), (481358641, "video"), (2250132122, "audio")]
    assert parsed["not_found"] == ["999999999999"]
    reordered = parsers.parse_graphql_assets(payload["data"]["getAssetDetails"], ["2250132122", "94143804"])
    assert [a["id"] for a in reordered["assets"]] == [2250132122, 94143804] and reordered["not_found"] == []


def test_none_found_and_a_locale_the_site_cannot_serve():
    assert load("assets_not_found.json") == {"data": {"getAssetDetails": None}}
    assert parsers.parse_graphql_assets(None, ["999999999999"]) == {"assets": [], "not_found": ["999999999999"]}
    # en_GB: the id comes back with no record (why refs.LOCALES leaves it out)
    assert record("assets_unserved_locale.json") is None
    assert parsers.parse_graphql_asset({}) is None and parsers.parse_graphql_asset(None) is None


# ---- the GraphQL search --------------------------------------------------------------

def test_audio_search_page():
    listing = graphql_page("graphql_search_audio_piano.json")
    assert listing["pagination"] == {"page": 1, "items_per_page": 5, "total_count": 29484, "total_pages": 2000}
    assert [(r["id"], r["type"]) for r in listing["results"]] == [
        (898824613, "audio"), (2230771904, "audio"), (481020453, "audio"), (2225334138, "audio"), (744866323, "audio")]
    assert all(list(r) == ASSET_KEYS and r["audio"]["preview_link"] for r in listing["results"])


def test_audio_search_with_filters():
    track = graphql_page("graphql_search_audio_filters.json", 3)["results"][0]
    assert (track["id"], track["title"], track["created_at"]) == (506618426, "Ann Waltz", "2022-05-24T11:14:29Z")
    audio = track["audio"]
    assert (audio["artist"], audio["album"], audio["partner"]) == ("Dylan Hunger", "Heartfelt", "Jamendo")
    assert (audio["duration_seconds"], audio["tempo_bpm"], audio["is_instrumental"]) == (151, 93, True)
    assert audio["genres"] == ["Classical", "Film"] and "Romantic" in audio["subgenres"] and "Relaxing" in audio["moods"]
    assert track["stats"] == {"downloads": 17, "views": 0} and track["category"] is None


def test_sound_effect_and_no_result():
    effect = graphql_page("graphql_search_audio_sfx.json", 3)["results"][0]
    assert (effect["title"], effect["audio"]["duration_seconds"], effect["audio"]["tempo_bpm"]) == ("Buzzer Game Show", 0.341, None)
    assert effect["audio"]["genres"] == [] and effect["audio"]["is_instrumental"] is None
    empty = graphql_page("graphql_search_audio_no_result.json")
    assert empty == {"results": [], "pagination": {"page": 1, "items_per_page": 5, "total_count": 0, "total_pages": 0}}


def test_a_page_size_the_search_api_does_not_have():
    listing = parsers.parse_graphql_search(load("graphql_search_audio_limit_37.json")["data"]["getSearchResults"], 2, 37)
    assert len(listing["results"]) == 37 and listing["pagination"]["total_pages"] == 271


def test_the_fallback_search_answers_the_same_first_results():
    fallback = [r["id"] for r in graphql_page("graphql_search_coffee.json", 8)["results"]]
    assert fallback == [r["id"] for r in rows("search_coffee.json", 8)]
    filtered = graphql_page("graphql_search_photo_filters.json", 3)["results"]
    assert all(r["type"] == "photo" and r["dimensions"]["height"] > r["dimensions"]["width"] for r in filtered)


# ---- categories and suggestions ------------------------------------------------------

def test_categories():
    top = parsers.parse_categories(load("categories_root.json"))
    assert len(top) == 21
    assert top[0] == {"id": 1, "name": "Animals", "link": "https://stock.adobe.com/category/animals/1"}
    children = parsers.parse_categories(load("categories_1043.json"))
    assert len(children) == 12 and children[0]["name"] == "Accesories and Objects"
    assert "load_type" not in json.dumps(top + children)
    assert len(parsers.parse_categories(load("categories_leaf_596.json"))) == 13
    assert parsers.parse_category(load("category_596.json")) == {
        "id": 596, "name": "Landscapes", "link": "https://stock.adobe.com/category/landscapes/596"}
    assert parsers.parse_categories(None) == [] and parsers.parse_categories([{"name": "x"}]) == []


def test_suggestions():
    hits = fetch.unwrap_jsonp(raw("typeahead_cof.js"))
    assert parsers.parse_typeahead(hits) == ["coffee", "coffee cup", "coffe", "shop coffee", "coffee beans", "cup coffee",
                                             "beans coffee", "coffin", "coffee shop", "morning coffee"]
    assert "<em>" not in json.dumps(parsers.parse_typeahead(hits))
    assert parsers.parse_typeahead(fetch.unwrap_jsonp(raw("typeahead_none.js"))) == []
    assert parsers.parse_related_searches(load("related_wedding.json")) == [
        "wedding reception", "wedding ceremony", "wedding dress", "wedding photography", "wedding planning"]
    assert parsers.parse_related_searches(load("related_null.json")) == []
    assert parsers.parse_typeahead(None) == [] and parsers.parse_typeahead({"hits": [{}, {"term": " a "}]}) == ["a"]


# ---- small helpers -------------------------------------------------------------------

@pytest.mark.parametrize("value, expected", [
    ("##### Title\n* one\n* two\n\n\n", "Title\n- one\n- two"),
    ("plain  text", "plain text"),
    ("a\r\n\r\n\r\nb", "a\n\nb"),
    ("", None), (None, None), (5, None),
])
def test_text_block(value, expected):
    assert parsers._text_block(value) == expected


def test_media_types_cover_every_kind_the_site_has():
    assert set(parsers.MEDIA_TYPES.values()) == set(refs.TYPES) | {"audio"}
