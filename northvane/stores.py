"""Three demo competitor storefronts, served locally, each a different scraping problem.

* Brightcart       server-rendered category pages + product pages with JSON-LD; supports ETag/304.
* Voltaro          a JavaScript storefront: the HTML is an empty shell, data comes from a paginated
                   JSON API with opaque cursors, and the API rate-limits bursts with 429 + Retry-After.
* Hearth & Hollow  hand-written HTML: prices split across tags, strike-through sale prices, sold-out
                   badges, microdata on product pages, and the odd transient 503.

A simulation clock (POST /_sim/clock) moves all three stores to a given day, so one process can
replay 30 days of prices. The ground truth never leaves the generator.
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import time
from collections import deque

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from .catalog import STORE_KEYS, build_market, day_date, slug

CATALOG, OURS, LISTINGS, EVENTS = build_market()
BY_STORE = {k: [L for L in LISTINGS if STORE_KEYS[L.store] == k] for k in STORE_KEYS.values()}
BY_ID = {L.listing_id: L for L in LISTINGS}
CLOCK = {"day": 0}
_req_count = {"n": 0}
_volt_window: deque = deque()

app = FastAPI(title="Northvane demo stores")


@app.post("/_sim/clock")
async def set_clock(req: Request):
    CLOCK["day"] = int((await req.json())["day"])
    return {"day": CLOCK["day"], "date": day_date(CLOCK["day"]).isoformat()}


def _e(s: str) -> str:
    return html.escape(s, quote=True)


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _shell(store: str, body: str, title: str) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><html lang=en><head><meta charset=utf-8><title>{_e(title)} | {store}</title>"
                        f"</head><body>{body}</body></html>")


# ------------------------------------------------------------------ Brightcart
BC_PER_PAGE = 24


@app.get("/brightcart/robots.txt", response_class=PlainTextResponse)
def bc_robots():
    return "User-agent: *\nDisallow: /brightcart/cart\nDisallow: /brightcart/account\n"


@app.get("/brightcart/")
def bc_home():
    cats = sorted({L.category for L in BY_STORE["brightcart"]})
    nav = "".join(f'<li><a href="/brightcart/c/{slug(c)}">{_e(c)}</a></li>' for c in cats)
    return _shell("Brightcart", f'<header><a href="/brightcart/account">Account</a> <a href="/brightcart/cart">Cart</a></header>'
                                f'<nav class="cats"><ul>{nav}</ul></nav>', "Home")


@app.get("/brightcart/c/{cat}")
def bc_category(cat: str, page: int = 1):
    d = CLOCK["day"]
    items = [L for L in BY_STORE["brightcart"] if slug(L.category) == cat]
    chunk = items[(page - 1) * BC_PER_PAGE: page * BC_PER_PAGE]
    cards = []
    for L in chunk:
        was = f'<s class="was">{_money(L.list_prices[d])}</s>' if L.list_prices[d] else ""
        cards.append(f'<article class="pcard" data-pid="{L.listing_id}"><a href="/brightcart/p/{slug(L.title)}-{L.listing_id}">'
                     f'<h3>{_e(L.title)}</h3></a><div class="price">{_money(L.prices[d])}</div>{was}</article>')
    nxt = f'<a rel="next" href="/brightcart/c/{cat}?page={page + 1}">Next</a>' if page * BC_PER_PAGE < len(items) else ""
    return _shell("Brightcart", f'<main><div class="grid">{"".join(cards)}</div><nav class="pager">{nxt}</nav></main>', cat)


@app.get("/brightcart/p/{path}")
def bc_product(path: str, request: Request):
    d = CLOCK["day"]
    L = BY_ID.get(path.rsplit("-", 1)[-1])
    if not L or L.store != "Brightcart":
        return Response(status_code=404)
    offer = {"@type": "Offer", "price": f"{L.prices[d]:.2f}", "priceCurrency": "USD",
             "availability": "https://schema.org/" + ("InStock" if L.in_stock[d] else "OutOfStock")}
    ld = {"@context": "https://schema.org", "@type": "Product", "name": L.title, "sku": L.listing_id,
          "brand": {"@type": "Brand", "name": L.brand_shown}, "category": L.category, "offers": offer}
    if L.gtin:
        ld["gtin13"] = L.gtin
    body = (f'<main><h1>{_e(L.title)}</h1><p class="price">{_money(L.prices[d])}</p>'
            f'<script type="application/ld+json">{json.dumps(ld)}</script></main>')
    etag = '"' + hashlib.md5(body.encode()).hexdigest()[:16] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    r = _shell("Brightcart", body, L.title)
    r.headers["ETag"] = etag
    return r


# ------------------------------------------------------------------ Voltaro (JS storefront + JSON API)
VO_LIMIT = 24


@app.get("/voltaro/robots.txt", response_class=PlainTextResponse)
def vo_robots():
    return "User-agent: *\nAllow: /voltaro/api/\nDisallow: /voltaro/checkout\n"


@app.get("/voltaro/")
def vo_shell():
    return _shell("Voltaro", '<div id="app" data-api="/voltaro/api/v2/products"></div>'
                             '<script src="/voltaro/static/app.js" defer></script>'
                             '<noscript>This store needs JavaScript.</noscript>', "Voltaro")


def _vo_rate_limited() -> bool:
    now = time.monotonic()
    while _volt_window and now - _volt_window[0] > 0.5:
        _volt_window.popleft()
    _volt_window.append(now)
    return len(_volt_window) > 12            # more than 12 requests in 500 ms


def _vo_item(L, d):
    it = {"id": L.listing_id, "name": L.title, "brand": L.brand_shown, "dept": L.category,
          "price_cents": int(round(L.prices[d] * 100)), "available": L.in_stock[d]}
    if L.list_prices[d]:
        it["compare_at_cents"] = int(round(L.list_prices[d] * 100))
    if L.gtin:
        it["ean"] = L.gtin
    return it


@app.get("/voltaro/api/v2/products")
def vo_api(cursor: str = "", limit: int = VO_LIMIT):
    if _vo_rate_limited():
        return JSONResponse({"error": "rate_limited"}, status_code=429, headers={"Retry-After": "1"})
    d = CLOCK["day"]
    off = int(base64.urlsafe_b64decode(cursor.encode()).decode()) if cursor else 0
    limit = min(limit, VO_LIMIT)
    items = BY_STORE["voltaro"][off: off + limit]
    nxt = base64.urlsafe_b64encode(str(off + limit).encode()).decode() if off + limit < len(BY_STORE["voltaro"]) else None
    return {"items": [_vo_item(L, d) for L in items], "next_cursor": nxt}


@app.get("/voltaro/api/v2/products/{pid}")
def vo_api_one(pid: str):
    if _vo_rate_limited():
        return JSONResponse({"error": "rate_limited"}, status_code=429, headers={"Retry-After": "1"})
    L = BY_ID.get(pid)
    if not L or L.store != "Voltaro":
        return JSONResponse({"error": "not_found"}, status_code=404)
    it = _vo_item(L, CLOCK["day"])
    it["specs"] = {"category": L.category}
    return it


# ------------------------------------------------------------------ Hearth & Hollow (messy HTML)
HH_PER_PAGE = 30


@app.get("/hearth/robots.txt", response_class=PlainTextResponse)
def hh_robots():
    return "User-agent: *\nDisallow: /hearth/checkout\nDisallow: /hearth/wishlist\n"


def _hh_flaky(path: str) -> bool:
    _req_count["n"] += 1
    h = int(hashlib.md5(f"{CLOCK['day']}:{path}:{_req_count['n']}".encode()).hexdigest(), 16)
    return h % 100 < 2                       # ~2% transient 503s


def _hh_price(x: float) -> str:
    whole, cents = f"{x:,.2f}".split(".")
    return f'<span class="cur">$</span>{whole}<sup>.{cents}</sup>'


@app.get("/hearth/shop")
def hh_shop(page: int = 1, request: Request = None):
    if _hh_flaky(str(request.url)):
        return Response("Service temporarily unavailable", status_code=503)
    d = CLOCK["day"]
    items = BY_STORE["hearth"][(page - 1) * HH_PER_PAGE: page * HH_PER_PAGE]
    rows = []
    for L in items:
        badge = '<span class="badge oos">Sold out</span>' if not L.in_stock[d] else ""
        sale = f'<del>{_money(L.list_prices[d])}</del> ' if L.list_prices[d] else ""
        rows.append(f'<div class="item" id="i{L.listing_id}"><a class="t" href="/hearth/item/{L.listing_id}.html">'
                    f'{_e(L.title)}</a><div class="pr">{sale}{_hh_price(L.prices[d])}</div>{badge}'
                    f'<a class="wl" href="/hearth/wishlist?add={L.listing_id}">&#9825;</a></div>')
    more = (f'<a class="more" href="/hearth/shop?page={page + 1}">More &raquo;</a>'
            if page * HH_PER_PAGE < len(BY_STORE["hearth"]) else "")
    return _shell("Hearth &amp; Hollow", f'<div id="shop">{"".join(rows)}</div>{more}', "Shop")


@app.get("/hearth/item/{pid}.html")
def hh_item(pid: str, request: Request):
    if _hh_flaky(str(request.url)):
        return Response("Service temporarily unavailable", status_code=503)
    L = BY_ID.get(pid)
    if not L or L.store != "Hearth & Hollow":
        return Response(status_code=404)
    d = CLOCK["day"]
    mpn = f'<span itemprop="mpn">{L.mpn}</span>' if L.mpn else ""
    body = (f'<div itemscope itemtype="https://schema.org/Product"><h1 itemprop="name">{_e(L.title)}</h1>'
            f'<span itemprop="brand">{_e(L.brand_shown)}</span>{mpn}'
            f'<div itemprop="offers" itemscope itemtype="https://schema.org/Offer">'
            f'<meta itemprop="price" content="{L.prices[d]:.2f}"><meta itemprop="priceCurrency" content="USD">'
            f'<link itemprop="availability" href="https://schema.org/{"InStock" if L.in_stock[d] else "OutOfStock"}">'
            f'</div></div>')
    return _shell("Hearth &amp; Hollow", body, L.title)
