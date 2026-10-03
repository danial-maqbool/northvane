"""Synthetic market generator.

Builds one retailer's catalog ("Lumen & Lane", the Northvane customer) and three competitor
storefronts that carry overlapping products under their own titles, plus 30 days of prices.
Everything is seeded, fictional and reproducible. Brands, stores and products are made up;
GTINs use the 200-299 prefix range, which GS1 reserves for in-store use, so none of them can
collide with a real product.

The generator also writes the ground truth (which competitor listing is which of our products),
which the matcher never sees. It is only used to score the matcher.
"""
from __future__ import annotations

import datetime as dt
import math
import random
import re
from dataclasses import dataclass, field

SEED = 20261003
DAYS = 30
START = dt.date(2026, 9, 4)          # day 0; day 29 is 2026-10-03


def day_date(d: int) -> dt.date:
    return START + dt.timedelta(days=d)


# --------------------------------------------------------------------------------------------
# catalog templates: (line, kind, models, variant axis, values, base price per model)
# --------------------------------------------------------------------------------------------
CATS = {
    "Audio": {
        "brands": ["Auren", "Kovo", "Brisa"],
        "lines": [
            ("Halo", "Wireless Noise Cancelling Headphones", ["700", "500"], "color", ["Black", "Silver", "Sand"], [349, 229]),
            ("Pebble", "True Wireless Earbuds", ["Pro", "Lite"], "color", ["Black", "White"], [199, 99]),
            ("Arc", "Portable Bluetooth Speaker", ["M", "S"], "color", ["Slate", "Coral"], [149, 89]),
        ],
    },
    "Coffee": {
        "brands": ["Talwin", "Crema Nord", "Oskar & Lee"],
        "lines": [
            ("Barista", "Espresso Machine", ["Duo", "One"], "capacity", ["2 L", "1.5 L"], [649, 429]),
            ("Pour", "Drip Coffee Maker", ["12-Cup", "8-Cup"], "color", ["Black", "Steel"], [129, 89]),
            ("Grind", "Conical Burr Grinder", ["Pro", "Mini"], "color", ["Black", "White"], [199, 119]),
        ],
    },
    "Displays": {
        "brands": ["Nimbra", "Vistar", "Lumaq"],
        "lines": [
            ("Vista", "4K UHD Monitor", ["32", "27"], "size", ["32 inch", "27 inch"], [549, 399]),
            ("Edge", "QHD 165Hz Gaming Monitor", ["27", "24"], "size", ["27 inch", "24 inch"], [379, 279]),
            ("Flow", "Ultrawide Curved Monitor", ["34", "38"], "size", ["34 inch", "38 inch"], [699, 949]),
        ],
    },
    "Smart Home": {
        "brands": ["Hollis", "Tessel", "Brightwell"],
        "lines": [
            ("Guard", "Indoor Security Camera", ["4K", "2K"], "color", ["White", "Black"], [129, 79]),
            ("Glow", "Smart LED Bulb", ["4-Pack", "2-Pack"], "color", ["Warm White", "Color"], [59, 34]),
            ("Dial", "Smart Thermostat", ["Gen 3", "Gen 2"], "color", ["Graphite", "Snow"], [229, 169]),
        ],
    },
    "Air & Floor": {
        "brands": ["Zephra", "Duvo", "Kairo"],
        "lines": [
            ("Orbit", "Robot Vacuum and Mop", ["S8", "S6"], "color", ["Black", "White"], [799, 499]),
            ("Breeze", "HEPA Air Purifier", ["600", "400"], "color", ["White", "Stone"], [349, 229]),
            ("Glide", "Cordless Stick Vacuum", ["Pro", "Lite"], "color", ["Copper", "Grey"], [449, 299]),
        ],
    },
    "Wearables": {
        "brands": ["Pulsa", "Strada", "Veyl"],
        "lines": [
            ("Stride", "GPS Smartwatch", ["45 mm", "41 mm"], "color", ["Midnight", "Starlight"], [399, 349]),
            ("Band", "Fitness Tracker", ["4", "3"], "color", ["Black", "Rose"], [129, 89]),
            ("Loop", "Smart Ring", ["Size 10", "Size 8"], "color", ["Titanium", "Gold"], [299, 299]),
        ],
    },
}

# how competitors rename colours (a real source of matching misses)
COLOR_SYN = {
    "Black": ["Midnight Black", "Onyx", "Black"], "Silver": ["Platinum", "Silver"], "Sand": ["Desert Sand", "Sand"],
    "White": ["Frost White", "White", "Arctic"], "Slate": ["Slate Grey", "Slate"], "Coral": ["Coral Red", "Coral"],
    "Steel": ["Stainless Steel", "Steel"], "Warm White": ["Soft White", "Warm White"], "Color": ["Multicolor", "RGB Color"],
    "Graphite": ["Graphite", "Charcoal"], "Snow": ["Snow White", "Snow"], "Stone": ["Stone Grey", "Stone"],
    "Copper": ["Copper", "Rose Copper"], "Grey": ["Grey", "Gray"], "Midnight": ["Midnight", "Midnight Blue"],
    "Starlight": ["Starlight", "Champagne"], "Rose": ["Rose", "Blush Pink"], "Titanium": ["Titanium", "Silver Titanium"],
    "Gold": ["Gold", "Satin Gold"],
}


@dataclass
class Product:                       # one of OUR products (Lumen & Lane)
    sku: str
    title: str
    brand: str
    category: str
    line: str
    model: str
    variant: str
    kind: str
    gtin: str
    mpn: str
    cost: float
    base_price: float
    map_price: float | None
    daily_units: float


@dataclass
class Listing:                       # one competitor's listing
    store: str
    listing_id: str
    title: str
    brand_shown: str
    category: str
    gtin: str | None
    mpn: str | None
    truth_sku: str | None            # ground truth; never exposed to the crawler or matcher
    prices: list[float] = field(default_factory=list)       # advertised price per day
    list_prices: list[float | None] = field(default_factory=list)  # strike-through "was" price
    in_stock: list[bool] = field(default_factory=list)


def gtin13(rng: random.Random) -> str:
    body = "2" + "".join(str(rng.randint(0, 9)) for _ in range(11))
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(body))
    return body + str((10 - s % 10) % 10)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def r99(x: float) -> float:          # retail rounding: 349.00 -> 349.99 style
    return max(0.99, math.floor(x) + 0.99) if x >= 10 else round(x, 2)


def r00(x: float) -> float:
    return float(round(x))


def build_catalog(rng: random.Random) -> list[Product]:
    out: list[Product] = []
    n = 0
    for cat, spec in CATS.items():
        for bi, brand in enumerate(spec["brands"]):
            for line, kind, models, axis, values, bases in spec["lines"]:
                for mi, model in enumerate(models):
                    for vi, val in enumerate(values):
                        if axis == "size" and vi != mi:      # sizes are the model, not a variant
                            continue
                        if axis == "capacity" and vi != mi:
                            continue
                        n += 1
                        brand_mult = [1.0, 0.92, 1.07][bi]
                        base = bases[mi] * brand_mult * (1 + rng.uniform(-0.04, 0.04))
                        price = r99(base)
                        cost = round(price * rng.uniform(0.58, 0.72), 2)
                        variant = val
                        if axis in ("size", "capacity"):
                            title = f"{brand} {line} {model} {kind}" if axis == "capacity" else f"{brand} {line} {val} {kind}"
                            if axis == "capacity":
                                title += f", {val}"
                        else:
                            title = f"{brand} {line} {model} {kind}, {val}"
                        title = title.replace(" 32 inch 4K", " 32 inch 4K").replace("  ", " ")
                        code = (brand[:2] + line[:2]).upper()
                        mnum = re.sub(r"[^A-Za-z0-9]", "", model).upper()
                        mpn = f"{code}-{mnum}" + ("" if axis in ("size", "capacity") else f"-{val[:2].upper()}")
                        out.append(Product(
                            sku=f"LL-{n:04d}", title=title, brand=brand, category=cat, line=line, model=model,
                            variant=variant, kind=kind, gtin=gtin13(rng), mpn=mpn, cost=cost, base_price=price,
                            map_price=(r99(price * 0.9) if bi != 2 else None),     # third brand has no MAP policy
                            daily_units=round(rng.lognormvariate(1.2, 0.6), 2),
                        ))
    return out


# --------------------------------------------------------------------------------------------
# competitor titles
# --------------------------------------------------------------------------------------------
def title_brightcart(p: Product, rng: random.Random) -> str:
    kind = p.kind.replace("Noise Cancelling", "Noise-Cancelling").replace("True Wireless", "True-Wireless")
    if p.variant in (p.model,) or "inch" in p.variant or " L" in p.variant:
        extra = p.variant.replace(" inch", '"').replace(" L", "L")
        return f"{p.brand} {p.line} {extra} {kind}".replace(f'{p.model} {extra}', extra)
    color = rng.choice(COLOR_SYN.get(p.variant, [p.variant]))
    return f"{p.brand} {p.line} {p.model} {kind} ({color})"


def title_voltaro(p: Product, rng: random.Random) -> str:
    kind = (p.kind.replace("Wireless Noise Cancelling Headphones", "ANC Wireless Headphones")
            .replace("True Wireless Earbuds", "TWS Earbuds").replace("Portable Bluetooth Speaker", "BT Speaker")
            .replace("Conical Burr Grinder", "Burr Coffee Grinder").replace("Robot Vacuum and Mop", "Robot Vac + Mop")
            .replace("Cordless Stick Vacuum", "Cordless Vacuum").replace("Smart LED Bulb", "Smart Bulb"))
    model = p.model.replace(" ", "")
    if "inch" in p.variant:
        return f"{p.brand.upper()} {p.line}{model} {p.variant.replace(' inch', 'in')} {kind}"
    if " L" in p.variant:
        ml = int(float(p.variant.split()[0]) * 1000)
        return f"{p.brand.upper()} {p.line} {model} {kind} - {ml} ml"
    color = rng.choice(COLOR_SYN.get(p.variant, [p.variant]))
    return f"{p.brand.upper()} {p.line}{model if len(model) <= 3 else ' ' + model} {kind} – {color}"


def title_hearth(p: Product, rng: random.Random) -> str:
    kind = p.kind.lower()
    if "inch" in p.variant:
        return f"{p.line} {p.variant.replace(' inch', '-inch')} {kind} by {p.brand}"
    if " L" in p.variant:
        return f"{p.line} {p.model} {kind} by {p.brand} ({p.variant.replace(' ', '')} tank)"
    bundle = rng.random() < 0.15
    color = p.variant if rng.random() < 0.85 else ""
    t = f"{p.line} {p.model} {kind} by {p.brand}"
    if color:
        t += f" — {color}"
    if bundle:
        t += " + travel case"
    return t


STORES = {
    # name: (carry probability, gtin exposure, title fn, rounding)
    "Brightcart": (0.82, 0.65, title_brightcart, r99),
    "Voltaro": (0.76, 0.35, title_voltaro, r99),
    "Hearth & Hollow": (0.72, 0.0, title_hearth, r00),
}
STORE_KEYS = {"Brightcart": "brightcart", "Voltaro": "voltaro", "Hearth & Hollow": "hearth"}


# --------------------------------------------------------------------------------------------
# prices over 30 days
# --------------------------------------------------------------------------------------------
def our_price_path(p: Product, rng: random.Random) -> list[float]:
    path = [p.base_price] * DAYS
    if rng.random() < 0.35:                          # day-10 price cut on a third of the range
        cut = r99(p.base_price * rng.uniform(0.90, 0.95))
        for d in range(10, DAYS):
            path[d] = cut
    if rng.random() < 0.15:                          # a later increase on a few
        up = r99(path[19] * rng.uniform(1.03, 1.06))
        for d in range(20, DAYS):
            path[d] = up
    return path


def build_market(seed: int = SEED):
    rng = random.Random(seed)
    catalog = build_catalog(rng)
    ours = {p.sku: our_price_path(p, rng) for p in catalog}
    listings: list[Listing] = []
    events: list[dict] = []           # planted events, for documentation and tests
    for store, (carry, gexp, tfn, rnd) in STORES.items():
        key = STORE_KEYS[store]
        lid = 0
        for p in catalog:
            if rng.random() > carry:
                continue
            lid += 1
            L = Listing(store=store, listing_id=f"{key[:2].upper()}{1000 + lid * 7}", title=tfn(p, rng),
                        brand_shown=p.brand, category=p.category,
                        gtin=(p.gtin if rng.random() < gexp else None),
                        mpn=(p.mpn if store == "Hearth & Hollow" and rng.random() < 0.7 else None),
                        truth_sku=p.sku)
            mine = ours[p.sku]
            stock = [True] * DAYS
            listp: list[float | None] = [None] * DAYS
            if store == "Brightcart":                        # undercutter: follows our price, one day late
                off = rng.uniform(-0.045, -0.015)
                raw = [mine[max(0, d - 1)] * (1 + off) for d in range(DAYS)]
                promo = rng.random() < 0.18
                for d in range(DAYS):
                    if promo and day_date(d).weekday() >= 5:
                        listp[d] = rnd(raw[d]); raw[d] *= 0.9
            elif store == "Voltaro":                         # premium with 48 h flash sales
                off = rng.uniform(0.02, 0.07)
                raw = [p.base_price * (1 + off)] * DAYS
                raw = list(raw)
                if rng.random() < 0.22:
                    s = rng.randint(2, DAYS - 3); depth = rng.uniform(0.15, 0.25)
                    for d in (s, s + 1):
                        listp[d] = rnd(raw[d]); raw[d] = raw[d] * (1 - depth)
            else:                                            # steady drift, stock-outs, some MAP breaches
                off = rng.uniform(-0.02, 0.03)
                walk, raw = 0.0, []
                for d in range(DAYS):
                    if day_date(d).weekday() == 0:           # reprices on Mondays only
                        walk += rng.gauss(0, 0.012)
                    raw.append(p.base_price * (1 + off + walk))
                if rng.random() < 0.13:
                    s = rng.randint(3, DAYS - 2); ln = rng.randint(2, 6)
                    for d in range(s, min(DAYS, s + ln)):
                        stock[d] = False
            L.prices = [rnd(x) for x in raw]
            L.list_prices = listp
            L.in_stock = stock
            listings.append(L)

    # planted MAP breaches at Hearth & Hollow (selling under the brand's minimum advertised price)
    hh = [L for L in listings if L.store == "Hearth & Hollow"]
    mp = {p.sku: p for p in catalog}
    breach = [L for L in hh if mp[L.truth_sku].map_price][:40]
    rng.shuffle(breach)
    for L in breach[:6]:
        m = mp[L.truth_sku].map_price
        s = rng.randint(18, 25)
        for d in range(s, DAYS):
            L.prices[d] = r00(m * rng.uniform(0.86, 0.93))
        events.append({"type": "map_breach", "store": L.store, "listing": L.listing_id, "from_day": s})

    # planted pricing errors (a dropped digit) for one day each
    for store, day in (("Voltaro", 27), ("Brightcart", 21)):
        cands = [L for L in listings if L.store == store and L.prices[0] > 300]
        L = rng.choice(cands)
        L.prices[day] = round(L.prices[day] / 10, 2)
        events.append({"type": "pricing_error", "store": store, "listing": L.listing_id, "day": day})

    # products they carry that we do not (should never be matched)
    extra_brands = {"Audio": "Morrow", "Coffee": "Bellini Haus", "Displays": "Corvex", "Smart Home": "Nook",
                    "Air & Floor": "Aerin", "Wearables": "Tallis"}
    for store, (carry, gexp, tfn, rnd) in STORES.items():
        key = STORE_KEYS[store]
        for cat, b in extra_brands.items():
            for line, kind, models, axis, values, bases in CATS[cat]["lines"][:2]:
                fake = Product(sku="", title="", brand=b, category=cat, line=line, model=models[0],
                               variant=values[0], kind=kind, gtin=gtin13(rng), mpn="", cost=0,
                               base_price=bases[0] * 0.95, map_price=None, daily_units=0)
                if rng.random() < 0.5:
                    continue
                L = Listing(store=store, listing_id=f"{key[:2].upper()}9{rng.randint(1000, 9999)}",
                            title=tfn(fake, rng), brand_shown=b, category=cat,
                            gtin=(fake.gtin if rng.random() < gexp else None), mpn=None, truth_sku=None)
                L.prices = [rnd(fake.base_price * (1 + rng.gauss(0, 0.01))) for _ in range(DAYS)]
                L.list_prices = [None] * DAYS
                L.in_stock = [True] * DAYS
                listings.append(L)
    return catalog, ours, listings, events


if __name__ == "__main__":
    cat, ours, ls, ev = build_market()
    print(len(cat), "products,", len(ls), "listings")
    for s in STORES:
        sub = [L for L in ls if L.store == s]
        print(s, len(sub), sub[0].title, "|", sub[1].title)
    print(cat[0].title, cat[0].mpn, "|", cat[40].title, "|", cat[80].title)
    print(ev)
