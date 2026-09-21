from datetime import datetime, timezone

from .contracts import PlanInput, TripRequest


def calculate(plan: PlanInput, trip: TripRequest, at: datetime | None = None):
    at = at or datetime.now(timezone.utc)
    if at.tzinfo is None:
        raise ValueError("calculation time must include timezone")
    if plan.trip_id != trip.trip_id:
        raise ValueError("plan.trip_id does not match trip.trip_id")
    issues, totals, breakdown = [], {}, []
    complete = True
    required = {"transport", "transfer", "per_diem"}
    category_names = {"transport":"交通費", "hotel":"宿泊費", "transfer":"現地移動費", "per_diem":"日当"}
    direction_names = {"outbound":"往路", "return":"復路"}
    if trip.lodging_required is not False:
        required.add("hotel")
    if trip.lodging_required is None:
        issues.append("宿泊の要否が確認されていません。")
        complete = False
    for item in plan.costs:
        amount = None if item.unit_amount is None or item.quantity is None else item.unit_amount * item.quantity
        breakdown.append({"description": item.description, "category": item.category,
                          "unit_amount": item.unit_amount, "quantity": item.quantity,
                          "unit": item.unit, "amount": amount, "source": item.source,
                          "queried_at": item.queried_at})
        if amount is None or item.taxes_included is not True:
            complete = False
            issues.append(f"費用が未確定です：{item.description}（金額・数量・税の扱いを確認してください）。")
        if amount is not None:
            totals[item.category] = totals.get(item.category, 0) + amount
    present = {item.category for item in plan.costs}
    for category, reason in plan.zero_cost_reasons.items():
        if category in present or not reason.strip():
            raise ValueError("zero_cost_reasons must be nonblank and cannot duplicate a cost category")
    for category in sorted(required - present - set(plan.zero_cost_reasons)):
        complete = False
        issues.append(f"費用区分または費用が発生しない根拠がありません：{category_names[category]}")
    if trip.lodging_required is False and "hotel" in present:
        complete = False
        issues.append("宿泊なしの申請ですが、見積りに宿泊費が含まれています。")
    elapsed, travel = {}, {}
    itinerary_valid = True
    if not trip.origin or not trip.destination or not trip.departure_at or not trip.arrive_by or not trip.return_by:
        itinerary_valid = False
        issues.append("出発地、目的地または指定時刻が不足しています。")
    all_legs = sorted(plan.legs, key=lambda leg: datetime.fromisoformat(leg.departure_at))
    for left, right in zip(all_legs, all_legs[1:]):
        if datetime.fromisoformat(left.arrival_at) > datetime.fromisoformat(right.departure_at):
            itinerary_valid = False
            issues.append("移動区間の時刻が重複しています。")
    for direction in ("outbound", "return"):
        legs = [leg for leg in all_legs if leg.direction == direction]
        if not legs:
            itinerary_valid = False
            issues.append(f"移動行程が不足しています：{direction_names[direction]}")
            elapsed[direction] = None
            travel[direction] = None
            continue
        for left, right in zip(legs, legs[1:]):
            if left.destination != right.origin:
                itinerary_valid = False
                issues.append("乗り継ぎ地点が一致しません。接続区間を明記してください。")
        origin = trip.origin if direction == "outbound" else trip.destination
        destination = trip.destination if direction == "outbound" else trip.origin
        if legs[0].origin != origin or legs[-1].destination != destination:
            itinerary_valid = False
            issues.append(f"{direction_names[direction]}の出発地または目的地が申請内容と一致しません。")
        start, end = datetime.fromisoformat(legs[0].departure_at), datetime.fromisoformat(legs[-1].arrival_at)
        elapsed[direction] = (end-start).total_seconds()/60
        travel[direction] = sum((datetime.fromisoformat(l.arrival_at)-datetime.fromisoformat(l.departure_at)).total_seconds()/60 for l in legs)
        if direction == "outbound":
            if trip.departure_at and start < datetime.fromisoformat(trip.departure_at):
                itinerary_valid = False
                issues.append("往路の出発が申請した出発日時より早くなっています。")
            if trip.arrive_by and end > datetime.fromisoformat(trip.arrive_by):
                itinerary_valid = False
                issues.append("往路が到着期限に間に合いません。")
        elif trip.return_by and end > datetime.fromisoformat(trip.return_by):
            itinerary_valid = False
            issues.append("復路の到着が帰着期限を過ぎています。")
    if all_legs and any(l.direction == "return" for l in all_legs):
        outbound = [l for l in all_legs if l.direction == "outbound"]
        returning = [l for l in all_legs if l.direction == "return"]
        if outbound and returning and datetime.fromisoformat(returning[0].departure_at) < datetime.fromisoformat(outbound[-1].arrival_at):
            itinerary_valid = False
            issues.append("往路が終わる前に復路が出発します。")
    fresh = None if plan.valid_until is None else datetime.fromisoformat(plan.valid_until) > at
    if fresh is not True:
        issues.append("見積りの有効期限が不明または期限切れです。再確認してください。")
    if plan.available is not True:
        issues.append("予約可否が未確認、または予約不可です。")
    # Never use successful arithmetic as proof of policy compliance.
    issues.append("規程の適用範囲と承認条件が未確認のため、規程適合は未判定です。")
    return {"plan_id": plan.plan_id, "version": plan.version, "trip_id": plan.trip_id,
            "currency": "JPY", "data_kind": plan.data_kind, "source": plan.source,
            "queried_at": plan.queried_at, "cost_breakdown": breakdown, "category_totals": totals,
            "known_subtotal": sum(totals.values()), "total_cost": sum(totals.values()) if complete else None,
            "cost_complete": complete, "elapsed_minutes": elapsed, "travel_minutes": travel,
            "itinerary_valid": itinerary_valid, "quote_fresh": fresh, "available": plan.available,
            "compliant": None, "needs_approval": None, "issues": list(dict.fromkeys(issues))}


def compare(plans: list[PlanInput], trip: TripRequest):
    if len({p.plan_id for p in plans}) != len(plans):
        raise ValueError("duplicate plan_id")
    if len({p.data_kind for p in plans}) > 1:
        raise ValueError("実データとシミュレーションは分けて比較してください。混在した順位付けはできません。")
    at = datetime.now(timezone.utc)
    results = [calculate(p, trip, at) for p in plans]
    comparable = [r for r in results if r["cost_complete"] and r["itinerary_valid"] and r["available"] is True and r["quote_fresh"] is True]
    by_price = sorted(comparable, key=lambda r: (r["total_cost"], r["plan_id"]))
    by_time = sorted(comparable, key=lambda r: (sum(r["elapsed_minutes"].values()), r["plan_id"]))
    return {"results": results, "price_order": [r["plan_id"] for r in by_price],
            "time_order": [r["plan_id"] for r in by_time],
            "message": "順位は有効な費用・時間データの比較結果です。規程への適合は別途確認してください。"}
