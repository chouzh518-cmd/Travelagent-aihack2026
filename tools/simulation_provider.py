"""Clearly synthetic travel offers for exercising the planning workflow."""
from __future__ import annotations

from datetime import datetime, timedelta

from core.contracts import TripRequest
from policy_import.store import now

FARE_REFERENCE = "https://travel.jr-central.co.jp/plan/tokushu/shinkansen/station/"
TIMETABLE_REFERENCE = "https://railway.jr-central.co.jp/pwd/_pdf/N700S-every.pdf"
HOTEL_API_REFERENCE = "https://webservice.rakuten.co.jp/documentation/vacant-hotel-search"
ROUTE_API_REFERENCE = "https://docs.ekispert.com/v1/api/search/course/extreme.html"


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="minutes")


def _nights(trip: TripRequest, departure: datetime, return_by: datetime) -> int:
    if trip.lodging_required is False:
        return 0
    return max(1, (return_by.date() - departure.date()).days)


def _is_tokyo_osaka(origin: str, destination: str) -> bool:
    origin_key = origin.casefold().replace(" ", "")
    destination_key = destination.casefold().replace(" ", "")
    return (("東京" in origin_key or "tokyo" in origin_key)
            and any(name in destination_key for name in ("大阪", "新大阪", "osaka"))) or (
            ("東京" in destination_key or "tokyo" in destination_key)
            and any(name in origin_key for name in ("大阪", "新大阪", "osaka")))


def create_simulated_offers(trip: TripRequest) -> dict:
    """Return two schema-compatible offers plus UI-only synthetic provider details.

    Public fare material is shown only as a reference link. All generated
    departure/arrival times, fares, local transport costs, hotel records, and
    hotel prices are simulation values. Unknown per-diem amounts and seat
    inventory stay unknown instead of being fabricated.
    """
    queried_at = now()
    departure = datetime.fromisoformat(trip.departure_at)
    arrive_by = datetime.fromisoformat(trip.arrive_by)
    return_by = datetime.fromisoformat(trip.return_by)
    nights = _nights(trip, departure, return_by)
    tokyo_osaka = _is_tokyo_osaka(trip.origin, trip.destination)

    choices = [
        {"id": "simulated_nozomi", "name": "速達プラン", "train": "のぞみ相当（時刻は模擬）",
         "outbound_minutes": 147, "return_minutes": 147, "fare": 14720 if tokyo_osaka else 12000,
         "seats": None, "hotel_price": 9800, "hotel_walk": None, "transfer": 1200},
        {"id": "simulated_hikari", "name": "費用重視プラン", "train": "ひかり相当（時刻は模擬）",
         "outbound_minutes": 180, "return_minutes": 180, "fare": 14400 if tokyo_osaka else 10800,
         "seats": None, "hotel_price": 12000, "hotel_walk": None, "transfer": 900},
    ]

    plans = []
    details = {}
    for index, choice in enumerate(choices):
        out_departure = departure + timedelta(minutes=index * 10)
        out_arrival = out_departure + timedelta(minutes=choice["outbound_minutes"])
        latest_return_departure = return_by - timedelta(minutes=choice["return_minutes"])
        return_departure = max(latest_return_departure, out_arrival + timedelta(minutes=30))
        return_arrival = return_departure + timedelta(minutes=choice["return_minutes"])
        plan_id = choice["id"]
        hotel_name = f"{trip.destination}駅周辺の模擬ホテル {chr(65 + index)}" if nights else None
        hotel_location = f"{trip.destination}駅周辺（所在地は模擬）" if nights else None
        line_source = "シミュレーション上の固定値。実際の運賃・空席・予約可否は照会していません。"
        costs = [
            {"description": f"新幹線相当・往復（{choice['name']}／余席は未確認）", "category": "transport",
             "currency": "JPY", "unit_amount": choice["fare"], "quantity": 2,
             "unit": "往復", "taxes_included": True, "source": line_source, "queried_at": queried_at},
            {"description": "現地移動（行先詳細未指定の模擬値）", "category": "transfer",
             "currency": "JPY", "unit_amount": choice["transfer"], "quantity": 1,
             "unit": "一式", "taxes_included": True, "source": "シミュレーション値", "queried_at": queried_at},
            {"description": "日当（規程の表示範囲外のため未算定）", "category": "per_diem",
             "currency": "JPY", "unit_amount": None, "quantity": None,
             "unit": "単価・算定数量ともに未確認", "taxes_included": None,
             "source": "提示された規程画像では日当の金額・算定条件が画面外のため未算定", "queried_at": queried_at},
        ]
        zero_cost_reasons = {}
        if nights:
            costs.append({"description": f"{hotel_name}（1室・1泊あたり）", "category": "hotel",
                          "currency": "JPY", "unit_amount": choice["hotel_price"], "quantity": nights,
                          "unit": "泊・1室", "taxes_included": True,
                          "source": "架空の施設・料金によるシミュレーション値", "queried_at": queried_at})
        else:
            zero_cost_reasons["hotel"] = "宿泊不要の申請として、模擬見積りでは宿泊費を計上していません。"
        plans.append({
            "schema_version": "1.0", "plan_id": plan_id, "trip_id": trip.trip_id,
            "version": "simulation-2", "data_kind": "simulation", "available": None,
            "valid_until": None,
            "source": "ローカル模擬プロバイダー（予約・購入には利用できません）", "queried_at": queried_at,
            "legs": [
                {"direction": "outbound", "mode": "新幹線相当（時刻・運賃は模擬）",
                 "origin": trip.origin, "destination": trip.destination,
                 "departure_at": _iso(out_departure), "arrival_at": _iso(out_arrival),
                 "source": "時刻は模擬値で、実際の運行ダイヤとは照合していません。"},
                {"direction": "return", "mode": "新幹線相当（時刻・運賃は模擬）",
                 "origin": trip.destination, "destination": trip.origin,
                 "departure_at": _iso(return_departure), "arrival_at": _iso(return_arrival),
                 "source": "時刻は模擬値で、実際の運行ダイヤとは照合していません。"},
            ],
            "costs": costs, "zero_cost_reasons": zero_cost_reasons,
        })
        details[plan_id] = {
            "plan_name": choice["name"], "data_kind": "simulation",
            "seat_inventory": {"label": "余席は未確認（座席在庫 API 未接続）", "value": None,
                               "is_live": False},
            "hotel": ({"name": hotel_name, "location": hotel_location,
                       "walking_minutes": choice["hotel_walk"], "nightly_price_jpy": choice["hotel_price"],
                       "nights": nights, "rooms_assumed": 1, "is_real_facility": False,
                       "note": "施設名・所在地・空室数・料金はすべて架空の模擬値です。"} if nights else None),
            "fare_basis": ({"description": "シミュレーション上の固定運賃（実見積り・予約情報ではありません）",
                            "amount_jpy": choice["fare"], "reference_url": None,
                            "is_quote": False}),
            "assumptions": ["乗車時刻は入力された出発時刻を基準に作った模擬値です。",
                            "帰路は申請した帰着期限から逆算した模擬値です。",
                            "座席在庫 API は未接続のため、余席と予約可否を表示していません。",
                            "宿泊候補の位置・価格・室数は模擬値で、実在施設や空室を表しません。",
                            "日当は規程の表示範囲外です。単価・算定数量・金額を仮定していません。",
                            "旅費規程への適合はこの模擬データでは判定していません。"],
        }

    return {
        "status": "simulation", "data_kind": "simulation", "queried_at": queried_at,
        "plans": plans, "details": details,
        "provider_events": [
            {"provider": "ホテル検索", "status": "simulation", "source": HOTEL_API_REFERENCE,
             "message": "ホテル位置・空室・料金の項目を模擬応答で生成しました。実データは未取得です。"},
            {"provider": "新幹線検索", "status": "simulation", "source": ROUTE_API_REFERENCE,
             "message": "時刻・運賃・余席の項目を模擬応答で生成しました。実データは未取得です。"},
        ],
        "references": {"hotel_api": HOTEL_API_REFERENCE, "route_api": ROUTE_API_REFERENCE,
                       "timetable": TIMETABLE_REFERENCE, "fare": FARE_REFERENCE},
    }
