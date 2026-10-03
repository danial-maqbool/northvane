"""Northvane API + dashboard. Run:  uvicorn northvane.api:app --port 8800   (after `python run.py`)."""
from __future__ import annotations

import json
import os
import statistics as st
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, repricing
from . import signals as S
from .catalog import DAYS, day_date

ROOT = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("NORTHVANE_DB", ROOT / "results" / "northvane.db"))
METRICS = ROOT / "results" / "metrics.json"
ORG = "Lumen & Lane"
STORE_KEY = {"Brightcart": "bc", "Voltaro": "vo", "Hearth & Hollow": "hh"}

app = FastAPI(title="Northvane", version="1.0")
_cache: dict = {}


@app.middleware("http")
async def no_store(request, call_next):           # the dashboard is tiny; always serve fresh files
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def con():
    if "con" not in _cache:
        _cache["con"] = db.connect(DB)
    return _cache["con"]


def market() -> S.Market:
    if "m" not in _cache:
        _cache["m"] = S.Market(con())
    return _cache["m"]


def metrics() -> dict:
    return json.loads(METRICS.read_text()) if METRICS.exists() else {}


def _title(sku):
    return market().products[sku]["title"]


def _series(m, k):
    return [[m.obs[k][d][0], m.obs[k][d][1], m.obs[k][d][2]] if d in m.obs[k] else None for d in range(DAYS)]


@app.get("/api/meta")
def meta():
    m = market()
    return {"org": ORG, "today": day_date(m.today).isoformat(), "days": [day_date(d).isoformat() for d in range(DAYS)],
            "stores": [{"name": s, "key": STORE_KEY[s]} for s in S.STORES],
            "categories": sorted({p["category"] for p in m.products.values()})}


@app.get("/api/overview")
def overview():
    m, d = market(), market().today
    tracked = [s for s in m.products if m.comp.get(s)]
    pe = S.pricing_errors(m)
    uc = S.undercuts(m, d)
    mv = S.map_violations(m, d)
    so = S.stockouts(m, d)
    op = S.opportunities(m, d)
    pr = [p for p in S.promos(m) if p["start"] <= d <= p["end"]]
    runs = db.rows(con(), "SELECT * FROM crawl_runs")
    feed = []                                   # a balanced digest: the strongest few of each kind
    for e in pe:
        feed.append({**e, "severity": 3, "title": _title(e["sku"]), "when": e["day"]})
    for e in sorted(mv, key=lambda e: (e["since"], -e["below_pct"]))[:6]:
        feed.append({**e, "severity": 2, "title": _title(e["sku"]), "when": e["since"]})
    for e in sorted([e for e in uc if e["new"]], key=lambda e: -e["under_pct"])[:5]:
        feed.append({**e, "severity": 2, "title": _title(e["sku"]), "when": d})
    for e in so:
        feed.append({**e, "severity": 1, "title": _title(e["sku"]), "when": e["since"]})
    for e in sorted(pr, key=lambda e: -e["depth_pct"])[:5]:
        feed.append({**e, "severity": 1, "title": _title(e["sku"]), "when": e["start"]})
    for e in op[:5]:
        feed.append({**e, "severity": 1, "title": _title(e["sku"]), "when": d})
    feed.sort(key=lambda e: (-e["severity"], -e["when"]))
    for e in feed:
        if e.get("sku"):
            e["ours_series"] = [m.ours[e["sku"]][x] for x in range(DAYS)]
            k = m.comp.get(e["sku"], {}).get(e.get("store"))
            e["their_series"] = [m.obs[k][x][0] if k and x in m.obs[k] else None for x in range(DAYS)] if k else None
    cats = sorted({p["category"] for p in m.products.values()})
    return {
        "kpis": {
            "price_index": S.price_index(m, d), "price_index_7d": S.price_index(m, d - 7),
            "products_tracked": len(tracked), "catalog": len(m.products),
            "listings": len(m.listings), "observations": sum(len(v) for v in m.obs.values()),
            "undercuts": len(uc), "new_undercuts": sum(e["new"] for e in uc),
            "map_violations": len(mv), "map_stores": len({e["store"] for e in mv}),
            "pricing_errors": len(pe), "stockouts": len(so), "promos_live": len(pr),
            "opportunity_monthly": round(sum(o["monthly_gain"] for o in op), 2), "opportunities": len(op),
            "requests_30d": sum(r["requests"] for r in runs),
        },
        "index_series": [S.price_index(m, x) for x in range(DAYS)],
        "store_index_series": {s: [S.store_index(m, x, s) for x in range(DAYS)] for s in S.STORES},
        "compass": [{"category": c, "ours": S.price_index(m, d, c),
                     "stores": {s: S.store_index(m, d, s, c) for s in S.STORES}} for c in cats],
        "feed": feed[:40],
        "response": S.response_to_cuts(m),
        "match": metrics().get("matching", {}),
    }


@app.get("/api/products")
def products(category: str | None = None, q: str | None = None):
    m, d = market(), market().today
    out = []
    for sku, p in m.products.items():
        if category and p["category"] != category:
            continue
        if q and q.lower() not in (p["title"] + " " + sku).lower():
            continue
        pos = S.position(m, sku, d)
        comps = {}
        for store in S.STORES:
            k = m.comp.get(sku, {}).get(store)
            o = m.obs[k].get(d) if k else None
            comps[store] = {"price": o[0], "in_stock": o[2]} if o else None
        out.append({"sku": sku, "title": p["title"], "brand": p["brand"], "category": p["category"],
                    "ours": m.ours[sku][d], "cost": p["cost"], "map": p["map_price"],
                    "lowest": pos["lowest"] if pos else None, "lowest_store": pos["lowest_store"] if pos else None,
                    "gap_pct": pos["gap_pct"] if pos else None, "position": pos["position"] if pos else "unmatched",
                    "comps": comps, "units": p["daily_units"],
                    "spark": [m.ours[sku][x] for x in range(DAYS)],
                    "low_spark": [min(m.comp_prices(sku, x).values()) if m.comp_prices(sku, x) else None for x in range(DAYS)]})
    return out


@app.get("/api/product/{sku}")
def product(sku: str):
    m = market()
    if sku not in m.products:
        raise HTTPException(404)
    p = m.products[sku]
    comps = {}
    for store in S.STORES:
        k = m.comp.get(sku, {}).get(store)
        if not k:
            comps[store] = None
            continue
        L, mt = m.listings[k], m.matches[k]
        comps[store] = {"listing_id": k[1], "title": L["title"], "url": L["url"], "gtin": L["gtin"], "mpn": L["mpn"],
                        "series": _series(m, k),
                        "match": {"score": mt["score"], "method": mt["method"], "evidence": json.loads(mt["evidence"])}}
    ev = [e for e in S.pricing_errors(m) if e["sku"] == sku] + [e for e in S.promos(m) if e["sku"] == sku]
    mv = [e for e in S.map_violations(m, m.today) if e["sku"] == sku]
    sug = next((r for r in repricing.suggest(m)["rows"] if r["sku"] == sku), None)
    return {"product": p, "ours": [m.ours[sku][d] for d in range(DAYS)], "comps": comps, "events": ev + mv,
            "position": S.position(m, sku, m.today), "suggestion": sug}


@app.get("/api/heatmap")
def heatmap(n: int = 40):
    m, d = market(), market().today
    rows = []
    for sku, p in m.products.items():
        if not m.comp.get(sku):
            continue
        ours = m.ours[sku][d]
        gaps = {}
        for store in S.STORES:
            k = m.comp[sku].get(store)
            o = m.obs[k].get(d) if k else None
            gaps[store] = (round(100 * (o[0] - ours) / ours, 1) if o[2] else "oos") if o else None
        rows.append({"sku": sku, "title": p["title"], "category": p["category"], "revenue": ours * p["daily_units"], "gaps": gaps})
    rows.sort(key=lambda r: -r["revenue"])
    return rows[:n]


@app.get("/api/review")
def review():
    m = market()
    items = []
    for k, mt in m.matches.items():
        if mt["status"] != "review":
            continue
        L = m.listings[k]
        o = m.obs[k][m.today]
        p = m.products[mt["sku"]]
        items.append({"store": k[0], "listing_id": k[1], "score": mt["score"], "evidence": json.loads(mt["evidence"]),
                      "listing": {"title": L["title"], "brand": L["brand"], "gtin": L["gtin"], "mpn": L["mpn"],
                                  "url": L["url"], "price": o[0], "in_stock": o[2]},
                      "candidate": {"sku": p["sku"], "title": p["title"], "brand": p["brand"], "gtin": p["gtin"],
                                    "mpn": p["mpn"], "price": m.ours[p["sku"]][m.today], "variant": p["variant"]}})
    items.sort(key=lambda x: -x["score"])
    counts = {s: 0 for s in ("matched", "review", "unmatched", "rejected")}
    for mt in m.matches.values():
        counts[mt["status"]] = counts.get(mt["status"], 0) + 1
    return {"items": items, "counts": counts, "quality": metrics().get("matching", {})}


class Decision(BaseModel):
    decision: str            # "accept" | "reject"


@app.post("/api/review/{store}/{listing_id}")
def decide(store: str, listing_id: str, body: Decision):
    status = {"accept": "matched", "reject": "rejected"}.get(body.decision)
    if not status:
        raise HTTPException(400, "decision must be accept or reject")
    c = con()
    c.execute("UPDATE matches SET status=?, method=CASE WHEN ?='matched' THEN 'human' ELSE method END "
              "WHERE store=? AND listing_id=?", (status, status, store, listing_id))
    c.commit()
    _cache.pop("m", None)
    return review()["counts"]


@app.get("/api/reprice")
def reprice(strategy: str = "beat_lowest", beat: float = 1.0, index: float = 100.0, min_margin: float = 15.0,
            respect_map: bool = True, max_move: float = 8.0, category: str | None = None):
    r = repricing.suggest(market(), strategy=strategy, beat_pct=beat, index_target=index, min_margin=min_margin,
                          respect_map=respect_map, max_move=max_move, category=category)
    r["hist"] = _hist([x["delta_pct"] for x in r["rows"]])
    return r


def _hist(xs, lo=-12, hi=12, step=1):
    bins = [0] * int((hi - lo) / step)
    for x in xs:
        i = int((min(max(x, lo), hi - 1e-9) - lo) // step)
        bins[i] += 1
    return {"lo": lo, "step": step, "bins": bins}


class Rule(BaseModel):
    store: str = "any"
    condition: str = "undercut"           # undercut | map | stockout | drop
    threshold: float = 3.0
    category: str | None = None


@app.post("/api/alerts/preview")
def alert_preview(rule: Rule):
    m = market()
    by_day, examples = [0] * DAYS, []
    for d in range(1, DAYS):
        if rule.condition == "undercut":
            evs = [e for e in S.undercuts(m, d, rule.threshold) if e["new"]]
        elif rule.condition == "map":
            evs = [e for e in S.map_violations(m, d) if e["since"] == d]
        elif rule.condition == "stockout":
            evs = [e for e in S.stockouts(m, d) if e["since"] == d]
        else:                                  # a competitor drops its own price by >= threshold % day over day
            evs = []
            for sku, stores in m.comp.items():
                for store, k in stores.items():
                    a, b = m.obs[k].get(d - 1), m.obs[k].get(d)
                    if a and b and b[0] <= a[0] * (1 - rule.threshold / 100):
                        evs.append({"store": store, "sku": sku, "price": b[0], "was": a[0], "day": d})
        evs = [e for e in evs if (rule.store == "any" or e["store"] == rule.store) and
               (not rule.category or m.products[e["sku"]]["category"] == rule.category)]
        by_day[d] = len(evs)
        for e in evs[:2]:
            examples.append({**e, "title": _title(e["sku"]), "date": day_date(d).isoformat()})
    return {"fires": sum(by_day), "days_with_alerts": sum(1 for x in by_day if x), "by_day": by_day,
            "examples": examples[-6:][::-1]}


@app.get("/api/crawls")
def crawls():
    runs = db.rows(con(), "SELECT * FROM crawl_runs ORDER BY day, store")
    log = db.rows(con(), "SELECT * FROM crawl_log WHERE day=? ORDER BY t_ms", market().today)
    log0 = db.rows(con(), "SELECT * FROM crawl_log WHERE day=0 ORDER BY t_ms")
    first = db.rows(con(), "SELECT store, COUNT(*) n, SUM(status=429) r429, SUM(status=503) r503 FROM crawl_log WHERE day=0 GROUP BY store")
    q = db.rows(con(), "SELECT COUNT(*) n FROM quarantine")[0]["n"]
    return {"runs": runs, "log": log, "log0": log0, "day0": first, "quarantined": q, "crawl": metrics().get("crawl", {})}


app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")
