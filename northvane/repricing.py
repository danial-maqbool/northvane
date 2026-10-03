"""Guard-railed repricing suggestions. Nothing is pushed anywhere; it proposes and explains.

Order of rules: strategy target -> max daily move -> hard floor (minimum margin, then MAP).
The floor always wins: Northvane will exceed the max move upward before it prices below cost + margin
or below a brand's minimum advertised price.
"""
from __future__ import annotations

import math

from .signals import Market, position


def retail(x: float) -> float:
    return math.floor(x) + 0.99 if x >= 10 else round(x, 2)


def suggest(m: Market, strategy="beat_lowest", beat_pct=1.0, index_target=100.0, min_margin=15.0,
            respect_map=True, max_move=8.0, category=None, d=None):
    d = m.today if d is None else d
    rows, ups, downs, guard_hits = [], 0, 0, 0
    margin_now = margin_new = 0.0
    for sku, p in m.products.items():
        if category and p["category"] != category:
            continue
        pos = position(m, sku, d)
        if not pos:
            continue
        cur = pos["ours"]
        target = {"beat_lowest": pos["lowest"] * (1 - beat_pct / 100), "match_lowest": pos["lowest"]}.get(
            strategy, pos["median"] * index_target / 100)
        guards = []
        lo, hi = cur * (1 - max_move / 100), cur * (1 + max_move / 100)
        if target < lo:
            target = lo; guards.append("max move")
        elif target > hi:
            target = hi; guards.append("max move")
        margin_floor = p["cost"] * (1 + min_margin / 100)
        map_floor = p["map_price"] if respect_map and p["map_price"] else 0.0
        floor = max(margin_floor, map_floor)
        new = retail(target)
        if new > hi and new - 1 >= lo:                 # rounding up to .99 must not break the max move
            new = round(new - 1, 2)
        if new < floor:
            new = retail(floor) if retail(floor) >= floor else retail(floor) + 1
            guards = [g for g in guards if g != "max move"] + ["MAP" if map_floor >= margin_floor else "margin"]
        delta = round(new - cur, 2)
        units = p["daily_units"] * 30
        margin_now += (cur - p["cost"]) * units
        margin_new += ((new if abs(delta) >= 0.5 else cur) - p["cost"]) * units
        if abs(delta) < 0.5:
            continue
        guard_hits += bool(guards)
        ups += delta > 0
        downs += delta < 0
        rows.append({"sku": sku, "title": p["title"], "category": p["category"], "current": cur, "suggested": new,
                     "delta": delta, "delta_pct": round(100 * delta / cur, 2), "lowest": pos["lowest"],
                     "lowest_store": pos["lowest_store"], "margin_pct": round(100 * (new - p["cost"]) / new, 1),
                     "guards": guards})
    rows.sort(key=lambda r: -abs(r["delta_pct"]))
    return {"strategy": strategy, "changes": len(rows), "ups": ups, "downs": downs, "guard_hits": guard_hits,
            "monthly_margin_now": round(margin_now, 2), "monthly_margin_new": round(margin_new, 2),
            "monthly_margin_delta": round(margin_new - margin_now, 2), "rows": rows}
