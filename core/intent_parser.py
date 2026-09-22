"""Exact, explainable trip-slot parsing; model/API calls are separate adapters."""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, time, timedelta

from .contracts import TripRequest

REQUIRED = {
    "origin": "出発地", "destination": "目的地", "departure_at": "出発日時",
    "return_by": "帰着日時", "arrive_by": "到着期限", "purpose": "出張目的",
    "lodging_required": "宿泊の要否",
}
WEEKDAYS = {"周一":0, "星期一":0, "周二":1, "星期二":1, "周三":2, "星期三":2,
            "周四":3, "星期四":3, "周五":4, "星期五":4, "周六":5, "星期六":5,
            "周日":6, "星期日":6, "星期天":6, "月曜日":0, "月曜":0,
            "火曜日":1, "火曜":1, "水曜日":2, "水曜":2, "木曜日":3,
            "木曜":3, "金曜日":4, "金曜":4, "土曜日":5, "土曜":5,
            "日曜日":6, "日曜":6}


def validate_request(trip: TripRequest):
    missing = [key for key in REQUIRED if getattr(trip, key) is None
               or (isinstance(getattr(trip, key), str) and not getattr(trip, key).strip())]
    if missing:
        return {"status": "needs_information", "missing_fields": missing,
                "question": "次の項目を入力してください：" + "、".join(REQUIRED[key] for key in missing) + "。"}
    if not trip.confirmed:
        return {"status": "needs_confirmation", "missing_fields": [], "question": "日付、時刻、出張内容を確認してください。"}
    return {"status": "ready", "missing_fields": [], "question": None}


def _time_offset(value: datetime):
    offset = value.utcoffset()
    if offset is None:
        raise ValueError("base_time must include an explicit timezone")
    seconds = int(offset.total_seconds())
    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)
    return f"{sign}{seconds//3600:02d}:{(seconds%3600)//60:02d}"


def _explicit_date_mentions(text: str, base_time: datetime | None):
    pattern = r"(?<!\d)(?:(20\d{2})[-/年])?(\d{1,2})[-/月](\d{1,2})(?:日)?"
    mentions = []
    for match in re.finditer(pattern, text):
        year = int(match.group(1)) if match.group(1) else (base_time.year if base_time else None)
        if year is None:
            continue
        try:
            mentions.append((date(year, int(match.group(2)), int(match.group(3))), match.start(), match.end()))
        except ValueError:
            continue
    return mentions


def _date_from_text(text: str, base_time: datetime | None):
    mentions = _explicit_date_mentions(text, base_time)
    if mentions:
        return mentions[0][0], "explicit"
    explicit = re.search(r"(?<!\d)(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})(?:日)?", text)
    if explicit:
        try:
            return date(int(explicit.group(1)), int(explicit.group(2)), int(explicit.group(3))), "explicit"
        except ValueError as exc:
            return None, str(exc)
    if base_time is None or base_time.tzinfo is None:
        if re.search(r"下周|明天|后天|今天|来週|明日|明後日|今日", text):
            return None, "relative date requires base_time with an explicit timezone"
        return None, None
    local_date = base_time.date()
    for marker, delta in (("今天", 0), ("今日", 0), ("明天", 1), ("明日", 1),
                          ("后天", 2), ("明後日", 2)):
        if marker in text:
            return local_date + timedelta(days=delta), marker
    weekday = next((day for marker, day in WEEKDAYS.items() if marker in text), None)
    if weekday is not None:
        if "下周" not in text and "来週" not in text:
            return None, "weekday requires an explicit relative week"
        current_monday = local_date - timedelta(days=local_date.weekday())
        return current_monday + timedelta(days=7 + weekday), "next_week_weekday"
    return None, None


def parse_text(text: str, *, base_time: datetime | None = None):
    """Extract only literal places, dates, times and facts explicitly present in input.

    Relative dates require the captured local timestamp; missing clock times, headcount,
    and unresolved place names are asked back rather than silently invented.
    """
    if not text.strip():
        return {"status":"invalid_input", "message":"出張内容を入力してください。"}
    if base_time is not None and base_time.tzinfo is None:
        return {"status":"invalid_input", "message":"base_time にはタイムゾーンを指定してください。"}
    origin = destination = None
    place_text = re.sub(r"来週(?:の)?(?:月|火|水|木|金|土|日)(?:曜日|曜)に?", "", text)
    place_text = re.sub(r"(?:今日|明日|明後日)", "", place_text)
    route = re.search(r"(?P<origin>[^，,。；;\s]+?)から(?P<destination>[^，,。；;\s]+?)(?:へ|に)(?=[0-9]|日帰り|出張|顧客|訪問|会議|商談|[，,。；;]|$)", place_text)
    if not route:
        route = re.search(r"(?P<origin>[^，,。；;\s]+)\s*(?:→|->)\s*(?P<destination>[^，,。；;\s]+)", place_text)
    if not route:
        # Chinese route syntax is only accepted when the route marker is
        # explicit. A bare ``到`` also appears in Japanese phrases such as
        # ``到着希望`` and must not turn the rest of the sentence into a place.
        route = re.search(r"从(?P<origin>[^，,。；;\s]+?)(?:到|前往)(?P<destination>[^，,。；;\s]+?)(?=下周|今天|明天|后天|当天|当日|出差|见|拜访|参加|[，,。；;]|$)", text)
        if not route:
            route = re.search(r"(?P<origin>[^，,。；;\s]+)前往(?P<destination>[^，,。；;\s]+?)(?=下周|今天|明天|后天|当天|当日|出差|见|拜访|参加|[，,。；;]|$)", text)
    if route:
        origin = route.group("origin")
        destination = route.group("destination").removesuffix("へ").removesuffix("に")
    else:
        japanese_destination = re.search(r"(?P<destination>[^，,。；;\s]+?)(?:へ|に)(?=[0-9]|日帰り|出張|顧客|訪問|会議|商談|[，,。；;]|$)", place_text)
        chinese_destination = re.search(r"去(?P<destination>[^，,。；;\s]+?)(?=下周|今天|明天|后天|当天|当日|\d+天|见客户|拜访客户|参加会议|[，,。；;]|$)", text)
        event_destination = re.search(
            r"(?:^|[、，,。；;])(?P<destination>[^、，,。；;\s]+?)の[^、，,。；;\s]*(?:学会|カンファレンス|会議|セミナー|展示会)に参加", text)
        chinese_event_destination = re.search(
            r"(?:^|[、，,。；;])(?P<destination>[^、，,。；;\s]+)的[^、，,。；;\s]*(?:学会|会议|研讨会|展会)(?:想|要|准备)?参加", text)
        dest = japanese_destination or chinese_destination or event_destination or chinese_event_destination
        if dest:
            destination = dest.group("destination").removesuffix("へ").removesuffix("に")

    date_mentions = _explicit_date_mentions(text, base_time)
    travel_date, date_note = _date_from_text(text, base_time)
    if isinstance(date_note, str) and (date_note.startswith("relative") or date_note.startswith("weekday")):
        return {"status":"needs_reference_time", "message":"相対日付の解析には、タイムゾーン付きの基準時刻が必要です。", "date_note":date_note}
    if date_note and date_note not in {"explicit", "next_week_weekday", "今天", "明天", "后天", "今日", "明日", "明後日"}:
        return {"status":"invalid_input", "message":"日付を解析できませんでした。", "date_note":date_note}
    offset = _time_offset(base_time) if base_time is not None else None
    clocks = []
    time_pattern = r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)|(?<!\d)([01]?\d|2[0-3])時(半|[0-5]?\d分)?"
    for match in re.finditer(time_pattern, text):
        if match.group(1) is not None:
            hour, minute = int(match.group(1)), int(match.group(2))
        else:
            hour = int(match.group(3))
            minute = 30 if match.group(4) == "半" else int((match.group(4) or "0分").removesuffix("分"))
        clocks.append((time(hour, minute), match.start(), match.end()))
    arrival_match = re.search(
        r"(?P<before>[01]?\d|2[0-3]):(?P<before_minute>[0-5]\d)(?:之前|以前|前|までに)?(?:到达|到大阪|到目的地|到着)"
        r"|(?:到着(?:希望|期限)?(?:日時)?|到達希望)(?:は|：|:)\s*(?P<after>[01]?\d|2[0-3]):(?P<after_minute>[0-5]\d)",
        text,
    )
    if arrival_match and offset:
        clock_text = arrival_match.group("before")
        if clock_text is not None:
            clock_text += ":" + arrival_match.group("before_minute")
        else:
            clock_text = arrival_match.group("after") + ":" + arrival_match.group("after_minute")
        clock_position = text.find(clock_text, arrival_match.start(), arrival_match.end())
        matched_clock = next((clock for clock in clocks if clock[1] == clock_position), None)
        arrive_by = datetime.combine(travel_date, matched_clock[0]).isoformat() + offset if travel_date and matched_clock else None
    else:
        arrive_by = None
    departure_at = None
    return_by = None
    if travel_date and offset and clocks:
        departure_clock = clocks[0][0]
        departure_at = datetime.combine(travel_date, departure_clock).isoformat() + offset
    same_day = any(term in text for term in ("当天回", "当日回", "当天返回", "当日返回", "日帰り"))
    return_date_explicit = date_mentions[1][0] if len(date_mentions) > 1 else None
    return_date = return_date_explicit or (travel_date if same_day else None)
    return_clock = None
    if travel_date and offset and clocks:
        duration_match = re.search(r"(?:出差)?(\d+)天", text)
        if same_day:
            remaining = [item for item in clocks if item[1] > clocks[0][2]]
            return_clock = remaining[-1][0] if remaining else None
        elif duration_match and return_date_explicit is None:
            # Day-count wording has no stable inclusive/exclusive meaning without
            # an end-date confirmation, so never turn it into a return date.
            return_date, return_clock = None, None
        else:
            return_date = return_date_explicit or travel_date
            return_clock = clocks[-1][0] if len(clocks) > 1 else None
        if return_date and return_clock:
            return_by = datetime.combine(return_date, return_clock).isoformat() + offset
    event_match = re.search(r"(?P<event>[^，,。；;\s]{1,60}(?:学会|カンファレンス|会議|セミナー|展示会))(?:に)?参加", text)
    chinese_event_match = re.search(r"(?P<event>[^，,。；;\s]{1,60}(?:学会|会议|研讨会|展会))(?:想|要|准备)?参加", text)
    purpose_match = re.search(r"(见客户|拜访客户|客户会议|参加会议|参加研讨会|出席会议|顧客訪問|顧客との打合せ|商談|会議|研修|現地確認)", text)
    purpose = (event_match.group("event").rsplit("の", 1)[-1] + "への参加" if event_match else
               chinese_event_match.group("event").rsplit("的", 1)[-1] + "への参加" if chinese_event_match else
               purpose_match.group(0) if purpose_match else None)
    stay_match = re.search(r"(?P<nights>\d+)泊(?P<days>\d+)日", text)
    stay_match = stay_match or re.search(r"(?P<nights>\d+)(?:晚|夜)(?P<days>\d+)天", text)
    duration_limit_days = int(stay_match.group("days")) if stay_match else None
    stay_nights = int(stay_match.group("nights")) if stay_match else None
    budget_match = re.search(r"(?:预算(?:上限)?|予算(?:上限)?)(?:为|は|：|:|=)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(万)?\s*(?:元|円)?", text)
    budget_jpy = None
    if budget_match:
        amount = float(budget_match.group(1).replace(",", ""))
        budget_jpy = int(amount * 10000) if budget_match.group(2) else int(amount)
    no_lodging_terms = (
        "不住宿", "不要住宿", "无需住宿", "不需要住宿", "住宿不需要", "住宿不用",
        "不住酒店", "不用住酒店", "无需住酒店", "酒店不需要", "酒店无需", "不住一晚",
        "宿泊不要", "宿泊は不要", "宿泊なし", "宿泊しない", "宿泊の必要はありません",
        "宿泊は必要ありません", "宿泊する必要はありません", "宿泊は必要ない",
        "宿泊しなくてよい", "宿泊しなくてもよい", "ホテル不要", "ホテルは不要",
        "ホテルに泊まらない", "ホテルは必要ない", "泊まらない",
    )
    if any(term in text for term in no_lodging_terms) or same_day:
        lodging_required = False
    elif stay_nights or any(term in text for term in ("住宿", "酒店", "过夜", "住一晚", "宿泊", "ホテル", "一泊")):
        lodging_required = True
    else:
        lodging_required = None
    trip = TripRequest(trip_id=uuid.uuid4().hex, company_id=None, employee_id=None,
                       origin=origin, destination=destination, departure_at=departure_at,
                       arrive_by=arrive_by, return_by=return_by, purpose=purpose,
                       lodging_required=lodging_required, confirmed=False)
    validation = validate_request(trip)
    return_date_context = (return_date_explicit or
                           (travel_date + timedelta(days=stay_nights)
                            if travel_date and stay_nights is not None else
                            travel_date if travel_date and same_day else None))
    return {"status":validation["status"], "trip":trip.model_dump(), "budget_jpy": budget_jpy,
            "duration_limit_days": duration_limit_days,
            "missing_fields":validation["missing_fields"], "question":validation["question"],
            "date_note":date_note,
            "date_context":{"departure_date":travel_date.isoformat() if travel_date else None,
                            "return_date":return_date_context.isoformat() if return_date_context else None,
                            "same_day_return":same_day, "stay_nights":stay_nights,
                            "duration_limit_days":duration_limit_days, "timezone_offset":offset},
            "original_text":text,
            "model_api_status":"not_configured",
            "message":"入力文に明記された場所、日付、時刻を抽出しました。不足項目を入力し、確定した日時を確認してください。"}
