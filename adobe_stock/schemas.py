"""Marshmallow request schemas for every /adobe-stock/* route.

ONE param per input (never a sibling `url` / `id` pair):

    asset        an asset id (94143804) OR a stock.adobe.com asset link
    assets       up to 100 of those, comma-separated
    contributor  a contributor id (203434592) OR a contributor link
    category     a category id (596) OR a category link
    series       an asset id or link: the other assets of its series
    image        a picture link, for a search by picture

The site's search ignores a value it does not know and answers the
unfiltered list, so every choice is checked here: a wrong value is a 400,
never a wider answer. A filter that belongs to one type (a video's
duration, a template's app) is refused next to a `type` that excludes it.
At most 100 results a page, and the first 10,000 results of a search.
"""
from marshmallow import ValidationError, pre_load, validates_schema

from adobe_stock import refs
from schema_fields import (BaseSchema, ChoiceField, CommaListField, LimitField, NonNegativeNumber, PageField,
                           PositiveInt, QueryField, RefField, TrueOnlyFlag)
from scraper_utils import pictures
from scraper_utils.schema import max_length as _max_length

MAX_PAGE = refs.MAX_RESULTS         # with limit=1; a page past the 10,000 results is an empty page
MAX_QUERY_LENGTH = 200
MAX_PIXELS = 100000
MAX_MEGAPIXELS = 1000


class _Schema(BaseSchema):
    @pre_load
    def empty_is_absent(self, data, **kwargs):
        """An optional param sent empty (`sort=`, `page=`: a form that
        sends every field) is the absent param. A required param sent
        empty is still refused."""
        required = {field.data_key or name for name, field in self.fields.items() if field.required}
        return {key: value for key, value in data.items()
                if key in required or not (isinstance(value, str) and not value.strip())}


class AssetRefField(RefField):
    resolver = staticmethod(refs.resolve_asset)


class AssetsRefField(RefField):
    """'94143804, 841165203, <link>' -> the asset ids, in order, repeats dropped."""
    resolver = staticmethod(refs.resolve_assets)


class ContributorRefField(RefField):
    resolver = staticmethod(refs.resolve_contributor)


class CategoryRefField(RefField):
    resolver = staticmethod(refs.resolve_category)


class ImageLinkField(RefField):
    resolver = staticmethod(pictures.resolve_link)


class LocaleField(RefField):
    """'de_DE' / 'de-DE' / 'de' -> 'de_DE'; en_US when absent."""
    resolver = staticmethod(refs.resolve_locale)

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", refs.DEFAULT_LOCALE)
        kwargs.setdefault("metadata", {"description": "language of keywords, category names and countries, and of the "
                                                      "search itself: " + ", ".join(refs.LOCALES) + " (default en_US)"})
        super().__init__(**kwargs)


class ColorsField(RefField):
    resolver = staticmethod(refs.resolve_colors)


class GenresField(RefField):
    resolver = staticmethod(refs.resolve_genres)


class MoodsField(RefField):
    resolver = staticmethod(refs.resolve_moods)


def _optional(field_cls, description, **kwargs):
    return field_cls(required=False, load_default=None, metadata={"description": description}, **kwargs)


def _page_field():
    return PageField(max_page=MAX_PAGE, metadata={"description": "page number, from 1; a search reaches its first "
                                                                 "10,000 results"})


def _limit_field():
    return LimitField(default=100, max_size=refs.MAX_LIMIT, metadata={"description": "results per page, up to 100"})


def _types_field(description):
    return CommaListField(value_map=dict(refs.TYPES), upper=False, max_items=len(refs.TYPES),
                          metadata={"description": description})


def _sort_field():
    return ChoiceField(dict(refs.SORTS), metadata={"description": "relevance (default), newest, downloads, "
                                                                  "popularity or undiscovered"})


def _query_field(description):
    return QueryField(required=False, load_default=None, validate=_max_length(MAX_QUERY_LENGTH),
                      metadata={"description": description})


def _pixels(description):
    return PositiveInt(max_value=MAX_PIXELS, metadata={"description": description})


def _check_span(data, low, high):
    if data.get(low) is not None and data.get(high) is not None and data[low] > data[high]:
        raise ValidationError(f"{low} must not be larger than {high}.", field_name=low)


# ---- assets --------------------------------------------------------------------------

class AssetsSearchSchema(_Schema):
    query = _query_field("search keywords; a phrase in double quotes is matched as written, -word leaves a word out")
    type = _types_field("photo, illustration, vector, video, template or 3d; several are comma-separated. "
                        "Without it: photos, illustrations, vectors and videos")
    sort = _sort_field()
    orientation = ChoiceField(list(refs.ORIENTATIONS), metadata={"description": "horizontal, vertical, square or panoramic"})
    premium = ChoiceField(dict(refs.ONLY_OR_EXCLUDE), metadata={"description": "photos, illustrations and vectors of the "
                                                                               "Premium collection: only or exclude"})
    ai = ChoiceField(dict(refs.ONLY_OR_EXCLUDE), metadata={"description": "generative AI assets: only or exclude"})
    releases = ChoiceField(dict(refs.WITH_OR_WITHOUT), metadata={"description": "with or without a model or property release"})
    isolated = TrueOnlyFlag(metadata={"description": "true: only isolated subjects"})
    transparent = TrueOnlyFlag(metadata={"description": "true: only assets with a transparent background"})
    copy_space = TrueOnlyFlag(metadata={"description": "true: only pictures with room for text"})
    loop = TrueOnlyFlag(metadata={"description": "true: only looping videos"})
    icon = ChoiceField(dict(refs.ICON_TYPES), metadata={"description": "icons only: single (one icon) or sheet (an icon set)"})
    colors = _optional(ColorsField, "up to 3 hex colors, comma-separated (ff0000,0000ff)")
    min_megapixels = NonNegativeNumber(metadata={"description": "smallest size in megapixels"})
    max_megapixels = NonNegativeNumber(metadata={"description": "largest size in megapixels"})
    min_width = _pixels("smallest width in pixels")
    max_width = _pixels("largest width in pixels")
    min_height = _pixels("smallest height in pixels")
    max_height = _pixels("largest height in pixels")
    added_within = ChoiceField(dict(refs.ADDED_WITHIN), metadata={"description": "added in the last 1w, 1m, 6m, 1y or 2y"})
    video_duration = ChoiceField(dict(refs.VIDEO_DURATIONS), metadata={"description": "videos only: up_to_10, up_to_20, "
                                                                                      "up_to_30 or over_30 (seconds)"})
    template_app = CommaListField(value_map=dict(refs.TEMPLATE_APPS), upper=False, max_items=len(refs.TEMPLATE_APPS),
                                  metadata={"description": "templates for: photoshop, illustrator, indesign, "
                                                           "premiere_pro, after_effects or premiere_rush; several "
                                                           "are comma-separated"})
    template_category = ChoiceField(dict(refs.TEMPLATE_CATEGORIES),
                                    metadata={"description": "templates of one category: " + ", ".join(refs.TEMPLATE_CATEGORIES)})
    three_d_type = ChoiceField(dict(refs.THREE_D_TYPES), metadata={"description": "3D assets of one kind: model, light or material"})
    category = _optional(CategoryRefField, "only this category: a category id (596) or a stock.adobe.com category link")
    series = _optional(AssetRefField, "only the series of this asset: an asset id or link")
    locale = LocaleField()
    page = _page_field()
    limit = _limit_field()

    @validates_schema
    def check(self, data, **kwargs):
        _check_span(data, "min_megapixels", "max_megapixels")
        _check_span(data, "min_width", "max_width")
        _check_span(data, "min_height", "max_height")
        for name in ("min_megapixels", "max_megapixels"):
            if data.get(name) is not None and data[name] > MAX_MEGAPIXELS:
                raise ValidationError(f"Must be at most {MAX_MEGAPIXELS}.", field_name=name)
        types = data.get("type")
        if data.get("premium"):
            others = [name for name in ("video_duration", "loop", "template_app", "template_category", "three_d_type")
                      if data.get(name)]
            if others or any(t not in ("photo", "illustration", "vector") for t in types or ()):
                raise ValidationError("premium filters photos, illustrations and vectors: use it with those types only "
                                      "(the site has no Premium collection of videos, templates or 3D).",
                                      field_name="premium")
        if not types:
            return
        for needs, names in (("video", ("video_duration", "loop")), ("template", ("template_app", "template_category")),
                             ("3d", ("three_d_type",))):
            for name in names:
                if data.get(name) and needs not in types:
                    raise ValidationError(f"{name} filters {needs} assets: add {needs} to `type` or leave `type` out.",
                                          field_name=name)


class AssetsDetailsSchema(_Schema):
    asset = AssetRefField(metadata={"description": "asset id (94143804) or a stock.adobe.com asset link"})
    locale = LocaleField()


class AssetsBulkSchema(_Schema):
    assets = AssetsRefField(metadata={"description": f"up to {refs.MAX_BULK_ASSETS} asset ids or asset links, comma-separated"})
    locale = LocaleField()


class AssetsSimilarSchema(_Schema):
    asset = _optional(AssetRefField, "find assets that look like this one: an asset id or a stock.adobe.com asset link")
    image = _optional(ImageLinkField, "or find assets that look like this picture: a public picture link (https://...)")
    type = _types_field("photo, illustration, vector, video, template or 3d; several are comma-separated")
    locale = LocaleField()
    page = _page_field()
    limit = _limit_field()

    @validates_schema
    def one_input(self, data, **kwargs):
        if bool(data.get("asset")) == bool(data.get("image")):
            raise ValidationError("Give `asset` (an asset id or link) or `image` (a picture link), one of the two.",
                                  field_name="asset")


class AssetsSuggestionsSchema(_Schema):
    query = QueryField(max_length=100, metadata={"description": "the start of a search term, or a whole one"})


# ---- contributors --------------------------------------------------------------------

class ContributorsAssetsSchema(_Schema):
    contributor = ContributorRefField(metadata={"description": "contributor id (203434592) or a stock.adobe.com "
                                                               "contributor link"})
    query = _query_field("keywords within the portfolio")
    type = _types_field("photo, illustration, vector, video, template or 3d; several are comma-separated")
    sort = _sort_field()
    locale = LocaleField()
    page = _page_field()
    limit = _limit_field()


# ---- categories ----------------------------------------------------------------------

class CategoriesListSchema(_Schema):
    parent = _optional(CategoryRefField, "a category id or link: answers its subcategories; without it, the 21 "
                                         "top categories")
    locale = LocaleField()


# ---- audio ---------------------------------------------------------------------------

class AudioSearchSchema(_Schema):
    query = _query_field("search keywords")
    type = ChoiceField(dict(refs.AUDIO_TYPES), metadata={"description": "music or sfx (sound effects); both without it"})
    genres = _optional(GenresField, "genres, comma-separated (" + ", ".join(refs.GENRES) + "); a subgenre is "
                                    "written Genre/Subgenre (Jazz/Swing)")
    moods = _optional(MoodsField, "moods, comma-separated: " + ", ".join(refs.MOODS))
    min_tempo = PositiveInt(max_value=refs.MAX_TEMPO, metadata={"description": "slowest tempo in beats per minute (1-300)"})
    max_tempo = PositiveInt(max_value=refs.MAX_TEMPO, metadata={"description": "fastest tempo in beats per minute (1-300)"})
    min_duration = PositiveInt(max_value=refs.MAX_AUDIO_SECONDS, metadata={"description": "shortest length in seconds"})
    max_duration = PositiveInt(max_value=refs.MAX_AUDIO_SECONDS, metadata={"description": "longest length in seconds (up to 1200)"})
    vocals = ChoiceField(dict(refs.VOCALS), metadata={"description": "with or without vocals"})
    loop = TrueOnlyFlag(metadata={"description": "true: only loops"})
    sort = ChoiceField(dict(refs.AUDIO_SORTS), metadata={"description": "relevance (default), newest, downloads, "
                                                                        "popularity or undiscovered"})
    locale = LocaleField()
    page = PageField(max_page=MAX_PAGE, metadata={"description": "page number, from 1; a search reaches its first "
                                                                 "10,000 results"})
    limit = LimitField(default=100, max_size=refs.MAX_LIMIT, metadata={"description": "tracks per page, up to 100"})

    @validates_schema
    def check(self, data, **kwargs):
        _check_span(data, "min_tempo", "max_tempo")
        _check_span(data, "min_duration", "max_duration")
