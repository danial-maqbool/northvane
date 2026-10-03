"""Polite, change-aware async crawler with one adapter per store.

What it does that a naive scraper does not:
* reads robots.txt first and never requests a disallowed path (it counts the links it declined)
* caps concurrency per store and retries 429/5xx with exponential backoff, honouring Retry-After
* sends If-None-Match, so unchanged product pages come back as 304 with no body
* fetches expensive detail pages only for listings it has never seen
* validates every row before it is stored; anything malformed goes to quarantine, not the table
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, ValidationError, field_validator

UA = "NorthvaneBot/1.0 (+demo; price monitoring)"


class Row(BaseModel):
    listing_id: str = Field(min_length=2)
    url: str
    title: str = Field(min_length=3)
    price: float = Field(gt=0, lt=100_000)
    list_price: float | None = None
    in_stock: bool
    brand: str | None = None
    category: str | None = None
    gtin: str | None = None
    mpn: str | None = None

    @field_validator("gtin")
    @classmethod
    def _gtin(cls, v):
        if v is None:
            return v
        if not re.fullmatch(r"\d{13}", v):
            raise ValueError("gtin must be 13 digits")
        s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(v[:12]))
        if (10 - s % 10) % 10 != int(v[12]):
            raise ValueError("gtin check digit")
        return v


@dataclass
class Stats:
    requests: int = 0
    ok: int = 0
    not_modified: int = 0
    retries: int = 0
    errors: int = 0
    robots_blocked: int = 0
    bytes: int = 0
    log: list = field(default_factory=list)


class Fetcher:
    def __init__(self, client: httpx.AsyncClient, base: str, store: str, concurrency: int, t0: float):
        self.c, self.base, self.store = client, base, store
        self.sem = asyncio.Semaphore(concurrency)
        self.stats = Stats()
        self.robots = RobotFileParser()
        self.t0 = t0

    async def load_robots(self, path: str):
        r = await self.c.get(self.base + path, headers={"User-Agent": UA})
        self.stats.requests += 1; self.stats.ok += 1; self.stats.bytes += len(r.content)
        self.robots.parse(r.text.splitlines())

    def allowed(self, url: str) -> bool:
        return self.robots.can_fetch(UA, urlparse(url).path + (("?" + urlparse(url).query) if urlparse(url).query else ""))

    async def get(self, url: str, headers: dict | None = None, note: str = "") -> httpx.Response | None:
        full = url if url.startswith("http") else self.base + url
        if not self.allowed(full):
            self.stats.robots_blocked += 1
            return None
        h = {"User-Agent": UA, **(headers or {})}
        async with self.sem:
            for attempt in range(5):
                t = time.perf_counter()
                try:
                    r = await self.c.get(full, headers=h)
                except httpx.TransportError:
                    r = None
                ms = (time.perf_counter() - t) * 1000
                self.stats.requests += 1
                status = r.status_code if r is not None else 0
                size = len(r.content) if r is not None else 0
                self.stats.bytes += size
                self.stats.log.append(((time.perf_counter() - self.t0) * 1000, urlparse(full).path +
                                       (("?" + urlparse(full).query) if urlparse(full).query else ""), status, ms, size,
                                       note if attempt == 0 else f"retry {attempt}"))
                if status == 304:
                    self.stats.not_modified += 1
                    return r
                if status and status < 400:
                    self.stats.ok += 1
                    return r
                if status in (429, 500, 502, 503, 504, 0):
                    self.stats.retries += 1
                    wait = float(r.headers.get("Retry-After", 0)) if r is not None and status == 429 else 0
                    await asyncio.sleep(max(wait, 0.05 * 2 ** attempt))
                    continue
                self.stats.errors += 1
                return None
        self.stats.errors += 1
        return None


# ------------------------------------------------------------------------------- adapters
def money(s: str) -> float | None:
    m = re.search(r"\$\s*([\d,]+(?:\.\d{1,2})?)", s.replace(" ", " "))
    return float(m.group(1).replace(",", "")) if m else None


async def crawl_brightcart(f: Fetcher, known: dict, etags: dict) -> list[dict]:
    await f.load_robots("/brightcart/robots.txt")
    home = await f.get("/brightcart/", note="home")
    soup = BeautifulSoup(home.text, "lxml")
    for a in soup.select("header a"):                       # account/cart links: robots says no
        if not f.allowed(f.base + a["href"]):
            f.stats.robots_blocked += 1
    cats = [a["href"] for a in soup.select("nav.cats a")]
    cards = []

    async def walk(cat):
        url = cat
        while url:
            r = await f.get(url, note="category")
            if r is None:
                return
            s = BeautifulSoup(r.text, "lxml")
            for c in s.select("article.pcard"):
                was = c.select_one("s.was")
                cards.append({"listing_id": c["data-pid"], "url": c.a["href"], "title": c.h3.get_text(strip=True),
                              "price": money(c.select_one(".price").get_text()),
                              "list_price": money(was.get_text()) if was else None})
            nxt = s.select_one('a[rel="next"]')
            url = nxt["href"] if nxt else None

    await asyncio.gather(*(walk(c) for c in cats))

    async def detail(card):
        h = {"If-None-Match": etags[card["listing_id"]]} if card["listing_id"] in etags else {}
        r = await f.get(card["url"], headers=h, note="product")
        if r is None:
            return None
        prev = known.get(card["listing_id"])
        if r.status_code == 304 and prev:
            return {**prev, "price": card["price"], "list_price": card["list_price"]}
        etags[card["listing_id"]] = r.headers.get("ETag", "")
        m = re.search(r'<script type="application/ld\+json">(.*?)</script>', r.text, re.S)
        ld = json.loads(m.group(1))
        return {"listing_id": card["listing_id"], "url": card["url"], "title": ld["name"],
                "price": float(ld["offers"]["price"]), "list_price": card["list_price"],
                "in_stock": ld["offers"]["availability"].endswith("InStock"),
                "brand": ld.get("brand", {}).get("name"), "category": ld.get("category"), "gtin": ld.get("gtin13")}

    out = await asyncio.gather(*(detail(c) for c in cards))
    return [o for o in out if o]


async def crawl_voltaro(f: Fetcher, known: dict, etags: dict) -> list[dict]:
    await f.load_robots("/voltaro/robots.txt")
    shell = await f.get("/voltaro/", note="app shell")
    api = re.search(r'data-api="([^"]+)"', shell.text).group(1)      # discover the JSON API behind the JS app
    items, cursor = [], ""
    while True:
        r = await f.get(f"{api}?limit=24" + (f"&cursor={cursor}" if cursor else ""), note="api page")
        if r is None:
            break
        j = r.json()
        items += j["items"]
        cursor = j.get("next_cursor")
        if not cursor:
            break
    new = [it for it in items if it["id"] not in known]

    async def spec(it):                                   # specs only for listings we have never seen
        await f.get(f"{api}/{it['id']}", note="api item")

    await asyncio.gather(*(spec(it) for it in new))
    return [{"listing_id": it["id"], "url": f"/voltaro/#/p/{it['id']}", "title": it["name"],
             "price": it["price_cents"] / 100, "list_price": (it.get("compare_at_cents") or 0) / 100 or None,
             "in_stock": it["available"], "brand": it.get("brand"), "category": it.get("dept"), "gtin": it.get("ean")}
            for it in items]


async def crawl_hearth(f: Fetcher, known: dict, etags: dict) -> list[dict]:
    await f.load_robots("/hearth/robots.txt")
    rows, url = [], "/hearth/shop?page=1"
    while url:
        r = await f.get(url, note="shop page")
        if r is None:
            break
        s = BeautifulSoup(r.text, "lxml")
        for it in s.select("div.item"):
            for a in it.select("a"):                      # wishlist links are disallowed: count, don't follow
                if not f.allowed(f.base + a["href"]):
                    f.stats.robots_blocked += 1
            pr = it.select_one(".pr")
            was = pr.select_one("del")
            if was:
                was_v = money(was.get_text()); was.extract()
            else:
                was_v = None
            a = it.select_one("a.t")
            rows.append({"listing_id": it["id"][1:], "url": a["href"], "title": a.get_text(strip=True),
                         "price": money(pr.get_text("", strip=True)), "list_price": was_v,
                         "in_stock": it.select_one(".badge.oos") is None})
        more = s.select_one("a.more")
        url = more["href"] if more else None
    new = [x for x in rows if x["listing_id"] not in known]

    async def detail(x):
        r = await f.get(x["url"], note="item page")
        if r is None:
            return
        s = BeautifulSoup(r.text, "lxml")
        b, m = s.select_one('[itemprop="brand"]'), s.select_one('[itemprop="mpn"]')
        x["brand"] = b.get_text(strip=True) if b else None
        x["mpn"] = m.get_text(strip=True) if m else None

    await asyncio.gather(*(detail(x) for x in new))
    for x in rows:
        if x["listing_id"] in known:
            for k in ("brand", "mpn", "category"):
                x.setdefault(k, known[x["listing_id"]].get(k))
    return rows


ADAPTERS = {"Brightcart": (crawl_brightcart, 8), "Voltaro": (crawl_voltaro, 8), "Hearth & Hollow": (crawl_hearth, 6)}


async def crawl_store(client, base, store, known, etags, t0):
    fn, conc = ADAPTERS[store]
    f = Fetcher(client, base, store, conc, t0)
    t = time.perf_counter()
    raw = await fn(f, known, etags)
    good, bad = [], []
    for x in raw:
        try:
            good.append(Row(**x).model_dump())
        except ValidationError as e:
            bad.append((x, e.errors()[0]["msg"]))
    return good, bad, f.stats, time.perf_counter() - t
