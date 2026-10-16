from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from typing import Any

from ...utils.text import clean, to_bool, to_float, to_int

STATUSES = ("upcoming", "ongoing", "past", "all")
SORTS = ("timeAsc", "startAsc", "startDesc", "priceAsc", "priceDesc", "distance")
MAX_PAGE_SIZE = 500

_PARAM_NAMES = {
    "status": "status",
    "page": "page",
    "page_size": "pageSize",
    "sort": "sort",
    "q": "q",
    "city": "cityName",
    "province": "province",
    "tag": "tag",
    "marker": "marker",
    "region": "region",
    "city_id": "cityId",
    "updated_since": "updatedSince",
    "date_mode": "dateMode",
    "date": "date",
    "date_from": "dateFrom",
    "date_to": "dateTo",
    "holiday_name": "holidayName",
    "min_price_cents": "minPriceCents",
    "max_price_cents": "maxPriceCents",
    "lat": "lat",
    "lng": "lng",
    "max_distance_km": "maxDistanceKm",
}
_FLAG_NAMES = {
    "highlighted_only": "highlightedOnly",
    "featured_only": "featuredOnly",
    "carousel_only": "carouselOnly",
}
_INT_FIELDS = {"min_price_cents", "max_price_cents"}
_FLOAT_FIELDS = {"lat", "lng", "max_distance_km"}


@dataclass(frozen=True)
class EventQuery:
    status: str = "upcoming"
    include_past: bool = False
    page: int = 1
    page_size: int = 20
    sort: str = "timeAsc"
    q: str = ""
    city: str = ""
    province: str = ""
    tag: str = ""
    marker: str = ""
    region: str = ""
    city_id: str = ""
    updated_since: str = ""
    date_mode: str = ""
    date: str = ""
    date_from: str = ""
    date_to: str = ""
    holiday_name: str = ""
    min_price_cents: int | None = None
    max_price_cents: int | None = None
    lat: float | None = None
    lng: float | None = None
    max_distance_km: float | None = None
    highlighted_only: bool = False
    featured_only: bool = False
    carousel_only: bool = False
    facets: bool | None = None

    @classmethod
    def from_args(cls, args: Mapping[str, Any], *, default_page_size: int = 20) -> EventQuery:
        values: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in args or args[f.name] is None:
                continue
            raw = args[f.name]
            if f.name in _INT_FIELDS:
                values[f.name] = to_int(raw, 0, lo=0)
            elif f.name in _FLOAT_FIELDS:
                values[f.name] = to_float(raw, 0.0)
            elif f.name in ("include_past", "facets", *_FLAG_NAMES):
                values[f.name] = to_bool(raw)
            elif f.name in ("page", "page_size"):
                values[f.name] = to_int(raw, 1)
            else:
                values[f.name] = clean(raw)
        values.setdefault("page_size", default_page_size)
        return cls(**values).normalized()

    def normalized(self) -> EventQuery:
        return replace(
            self,
            status=self.status if self.status in STATUSES else "upcoming",
            sort=self.sort if self.sort in SORTS else "timeAsc",
            page=max(1, self.page),
            page_size=min(max(1, self.page_size), MAX_PAGE_SIZE),
        )

    def to_params(self) -> dict[str, str]:
        params: dict[str, str] = {
            "includePast": str(self.include_past or self.status == "all").lower(),
        }
        for name, param in _PARAM_NAMES.items():
            value = getattr(self, name)
            if value is not None and value != "":
                params[param] = str(value)
        for name, param in _FLAG_NAMES.items():
            if getattr(self, name):
                params[param] = "true"
        if self.facets is not None:
            params["facets"] = str(self.facets).lower()
        return params

    def describe(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "city": self.city,
            "province": self.province,
            "tag": self.tag,
            "marker": self.marker,
            "include_past": self.include_past,
        }
