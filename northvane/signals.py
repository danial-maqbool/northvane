"""Turns matched observations into the things a pricing team acts on.

All of it is computed from the crawled observations and the confirmed matches, nothing else.
"""
from __future__ import annotations

import statistics as st
from collections import defaultdict

from .catalog import DAYS, day_date

STORES = ["Brightcart", "Voltaro", "Hearth & Hollow"]


class Market:
    """In-memory view of the database: products, our prices, matched competitor price series."""

    def __init__(self, con, statuses=("matched",)):
        self.products = {r["sku"]: dict(r) for r in con.execute("SELECT * FROM products")}
        self.ours = defaultdict(dict)
        for r in con.execute("SELECT day, sku, price FROM our_prices"):
            self.ours[r["sku"]][r["day"]] = r["price"]
        self.listings = {(r["store"], r["listing_id"]): dict(r) for r in con.execute("SELECT * FROM listings")}
        self.matches = {(r["store"], r["listing_id"]): dict(r) for r in con.execute("SELECT * FROM matches")}
        self.obs = defaultdict(dict)
        for r in con.execute("SELECT * FROM observations"):
            self.obs[(r["store"], r["listing_id"])][r["day"]] = (r["price"], r["list_price"], bool(r["in_stock"]))
        self.comp = defaultdict(dict)            # sku -> store -> listing key
        for k, m in self.matches.items():
            if m["sku"] and m["status"] in statuses:
                self.comp[m["sku"]][k[0]] = k
        self.today = DAYS - 1

    def comp_prices(self, sku, d, in_stock_only=True):
        out = {}
        for store, k in self.comp.get(sku, {}).items():
            o = self.obs[k].get(d)
            if o and (o[2] or not in_stock_only):
                out[store] = o[0]
        return out


def _median(xs):
    return st.median(xs) if xs else None


def position(m: Market, sku: str, d: int):
    ours = m.ours[sku][d]
    cp = m.comp_prices(sku, d)
    if not cp:
        return None
    lo = min(cp.values())
    gap = (ours - lo) / lo
    pos = "cheapest" if ours < lo * 0.99 else ("matched" if ours <= lo * 1.01 else "above")
    return {"ours": ours, "lowest": lo, "lowest_store": min(cp, key=cp.get), "median": _median(list(cp.values())),
            "gap_pct": round(gap * 100, 2), "position": pos, "comps": cp}


def price_index(m: Market, d: int, category: str | None = None):
    """100 = priced exactly at the competitor average, weighted by unit sales. Below 100 = cheaper."""
    num = den = 0.0
    for sku, p in m.products.items():
        if category and p["category"] != category:
            continue
        cp = m.comp_prices(sku, d)
        if not cp:
            continue
        w = p["daily_units"]
        num += m.ours[sku][d] * w
        den += st.mean(cp.values()) * w
    return round(100 * num / den, 2) if den else None


def store_index(m: Market, d: int, store: str, category: str | None = None):
    """A competitor's price level against ours on the products we both sell (100 = same as us)."""
    num = den = 0.0
    for sku, p in m.products.items():
        if category and p["category"] != category:
            continue
        k = m.comp.get(sku, {}).get(store)
        o = m.obs[k].get(d) if k else None
        if not o or not o[2]:
            continue
        num += o[0] * p["daily_units"]
        den += m.ours[sku][d] * p["daily_units"]
    return round(100 * num / den, 2) if den else None


def pricing_errors(m: Market):
    out = []
    for k, series in m.obs.items():
        if k not in m.matches or not m.matches[k]["sku"]:
            continue
        for d in range(DAYS):
            if d not in series:
                continue
            window = [series[x][0] for x in range(max(0, d - 14), d) if x in series]
            if len(window) < 3:
                continue
            med = _median(window)
            if series[d][0] < 0.35 * med:
                out.append({"type": "pricing_error", "day": d, "store": k[0], "listing_id": k[1],
                            "sku": m.matches[k]["sku"], "price": series[d][0], "typical": med,
                            "drop_pct": round(100 * (1 - series[d][0] / med), 1)})
    return out


def map_violations(m: Market, d: int):
    out = []
    for sku, stores in m.comp.items():
        mp = m.products[sku]["map_price"]
        if not mp:
            continue
        for store, k in stores.items():
            o = m.obs[k].get(d)
            if o and o[0] < mp - 0.005:
                since = d
                while since - 1 >= 0 and m.obs[k].get(since - 1, (mp,))[0] < mp - 0.005:
                    since -= 1
                out.append({"type": "map_violation", "day": d, "since": since, "store": store, "listing_id": k[1],
                            "sku": sku, "price": o[0], "map": mp, "below_pct": round(100 * (1 - o[0] / mp), 1)})
    return out


def promos(m: Market):
    """Flash sales: a price at least 10% under its own 7-day median, shown with a strike-through price."""
    out = []
    for k, series in m.obs.items():
        if k not in m.matches or not m.matches[k]["sku"]:
            continue
        d = 0
        while d < DAYS:
            o = series.get(d)
            window = [series[x][0] for x in range(max(0, d - 7), d) if x in series]
            if o and o[1] and window and o[0] <= 0.9 * _median(window):
                start, med = d, _median(window)
                while d + 1 < DAYS and series.get(d + 1) and series[d + 1][1] and series[d + 1][0] <= 0.9 * med:
                    d += 1
                out.append({"type": "promo", "store": k[0], "listing_id": k[1], "sku": m.matches[k]["sku"],
                            "start": start, "end": d, "depth_pct": round(100 * (1 - o[0] / med), 1)})
            d += 1
    return out


def stockouts(m: Market, d: int):
    out = []
    for sku, stores in m.comp.items():
        for store, k in stores.items():
            o = m.obs[k].get(d)
            if o and not o[2]:
                since = d
                while since - 1 >= 0 and m.obs[k].get(since - 1) and not m.obs[k][since - 1][2]:
                    since -= 1
                out.append({"type": "stockout", "store": store, "sku": sku, "since": since, "day": d})
    return out


def undercuts(m: Market, d: int, min_pct=2.0):
    """Competitors more than min_pct under us today; 'new' if they were not under us yesterday."""
    out = []
    for sku in m.products:
        ours, ours_y = m.ours[sku][d], m.ours[sku].get(d - 1)
        for store, price in m.comp_prices(sku, d).items():
            if price < ours * (1 - min_pct / 100):
                py = m.comp_prices(sku, d - 1).get(store) if d else None
                new = py is None or ours_y is None or py >= ours_y * (1 - min_pct / 100)
                out.append({"type": "undercut", "day": d, "store": store, "sku": sku, "price": price, "ours": ours,
                            "under_pct": round(100 * (1 - price / ours), 1), "new": new})
    return out


def response_to_cuts(m: Market, cut_day=10, window=2):
    """When we cut a price, how fast did each competitor follow?"""
    cut = [sku for sku in m.products if m.ours[sku][cut_day] < m.ours[sku][cut_day - 1] * 0.995]
    out = {}
    for store in STORES:
        followed, carried, lags = 0, 0, []
        for sku in cut:
            k = m.comp.get(sku, {}).get(store)
            if not k:
                continue
            carried += 1
            before = m.obs[k][cut_day - 1][0]
            for lag in range(0, window + 1):
                o = m.obs[k].get(cut_day + lag)
                if o and o[0] < before * 0.985:
                    followed += 1; lags.append(lag); break
        out[store] = {"cut_products": carried, "followed": followed,
                      "median_lag_days": _median(lags) if lags else None}
    return {"cut_day": cut_day, "date": day_date(cut_day).isoformat(), "n_cut": len(cut), "by_store": out}


def opportunities(m: Market, d: int, min_gap=5.0):
    """We are the cheapest by more than min_gap% with every matched rival in stock: room to raise."""
    out = []
    for sku, p in m.products.items():
        pos = position(m, sku, d)
        if not pos or pos["position"] != "cheapest":
            continue
        if len(m.comp_prices(sku, d)) < len(m.comp.get(sku, {})):
            continue
        headroom = (pos["lowest"] - pos["ours"]) / pos["ours"] * 100
        if headroom >= min_gap:
            target = round(pos["lowest"] * 0.99 // 1 + 0.99, 2) if pos["lowest"] > 10 else pos["lowest"]
            gain = (target - pos["ours"]) * p["daily_units"] * 30
            out.append({"type": "opportunity", "sku": sku, "ours": pos["ours"], "lowest": pos["lowest"],
                        "headroom_pct": round(headroom, 1), "target": target, "monthly_gain": round(gain, 2)})
    return sorted(out, key=lambda x: -x["monthly_gain"])
