from __future__ import annotations

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from pydantic import Field
from pydantic.dataclasses import dataclass

from ..api import ApiError
from ..api.query import SORTS, STATUSES
from .base import BaonlyTool, error_json, to_json

DESCRIPTION = (
    "查询蔚蓝档案(Blue Archive) BAONLY 同人展活动信息。"
    "返回活动列表，包含活动名称(title)、时间(timeText：已按东八区格式化的标准时间，"
    "如 2026.09.30 - 2026.10.01；startAt/endAt 为 ISO 标准时间，"
    "timeLabel 仅为源站原始文案，无标准时间时才使用)、"
    "地点(province/city/venueName/address)、票价(priceLabel)、"
    "售票状态(saleFlag)、主办方(organizer)、标签(tags)、"
    "运营标记(markers：已取消/已延期/地点变更)等详细信息。"
    "向用户播报时间时请使用 timeText 或依据 startAt/endAt 换算，不要直接照抄 timeLabel。"
    "可用于回答用户关于蔚蓝档案ONLY/同人展活动的查询。"
)


def _string(description: str, enum: tuple[str, ...] | None = None) -> dict:
    schema = {"type": "string", "description": description}
    if enum:
        schema["enum"] = list(enum)
    return schema


def _typed(kind: str, description: str) -> dict:
    return {"type": kind, "description": description}


PARAMETERS = {
    "type": "object",
    "properties": {
        "status": _string("活动状态筛选。upcoming=即将举行，ongoing=进行中，past=已结束，all=全部。默认 upcoming。", STATUSES),
        "include_past": _typed("boolean", "是否包含已结束的活动，默认 false。"),
        "city": _string("按城市名称筛选活动，例如'深圳市'、'上海市'、'广州市'。不填则返回全部城市。"),
        "province": _string('按省份名称筛选活动，例如"广东省"。'),
        "tag": _string('按标签筛选活动，例如"ONLY"、"同人展"。'),
        "marker": _string(
            "按运营标记筛选活动。cancelled=已取消，postponed=已延期，venueChanged=地点变更。",
            ("cancelled", "postponed", "venueChanged"),
        ),
        "q": _string("按活动标题关键字筛选。"),
        "region": _string('按大区筛选活动，例如"华东"、"华南"。'),
        "city_id": _string("按城市 ID 精确筛选，取值来自城市计数（facets）里的 value。"),
        "date_mode": _string(
            "日期筛选模式。holiday=按节假日，day=按单日（配合 date），range=按区间（配合 date_from/date_to）。",
            ("", "holiday", "day", "range"),
        ),
        "holiday_name": _string('节假日名称，配合 date_mode=holiday 使用，例如"国庆节"。'),
        "min_price_cents": _typed("integer", "最低票价下限，单位分（例如 6000 表示 60 元）。"),
        "max_price_cents": _typed("integer", "最高票价上限，单位分（例如 15000 表示 150 元）。"),
        "highlighted_only": _typed("boolean", "只返回带高亮（含高亮标签或运营标记）的活动。"),
        "carousel_only": _typed("boolean", "只返回进入首页海报轮播的精选活动。"),
        "lat": _typed("number", "纬度，与 lng 一起传入可开启距离排序（sort=distance）。"),
        "lng": _typed("number", "经度，与 lat 一起传入可开启距离排序（sort=distance）。"),
        "max_distance_km": _typed("number", "按距离筛选的最大半径（公里），需同时传 lat/lng，取值 1~5000。"),
        "date": _string("按具体日期筛选活动，格式 yyyy-MM-dd，例如 2026-10-01。"),
        "date_from": _string("按日期范围筛选（起始），格式 yyyy-MM-dd。"),
        "date_to": _string("按日期范围筛选（结束），格式 yyyy-MM-dd。"),
        "featured_only": _typed("boolean", "只返回运营精选的活动。"),
        "updated_since": _string("只返回这个时间点之后改动过的场次（ISO 8601 时间串），用于断线重连后的增量对齐。"),
        "sort": _string(
            "排序方式。timeAsc=按时间升序，startAsc=开始时间升序，priceAsc=价格升序，"
            "distance=按距离升序（需传 lat/lng）。默认 timeAsc。",
            SORTS,
        ),
        "page_size": _typed("integer", "每页返回条数，默认 20，最大 500。"),
    },
}


@dataclass
class QueryEventsTool(BaonlyTool):
    name: str = "baonly_query_events"
    description: str = DESCRIPTION
    parameters: dict = Field(default_factory=lambda: PARAMETERS)

    async def call(self, context: ContextWrapper[AstrAgentContext], **kwargs) -> ToolExecResult:
        catalog = self.svc.catalog
        try:
            return to_json(await catalog.query(catalog.build_query(kwargs)))
        except ApiError as exc:
            return error_json(str(exc))
