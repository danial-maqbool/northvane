from northvane.catalog import DAYS, STORES, build_market, day_date


def check_digit_ok(g):
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(g[:12]))
    return (10 - s % 10) % 10 == int(g[12])


def test_deterministic():
    a, b = build_market(), build_market()
    assert [p.title for p in a[0]] == [p.title for p in b[0]]
    assert [L.prices for L in a[2]] == [L.prices for L in b[2]]


def test_shapes(market):
    catalog, ours, listings, events = market
    assert len(catalog) == 198
    assert all(len(v) == DAYS for v in ours.values())
    assert all(len(L.prices) == DAYS and len(L.in_stock) == DAYS for L in listings)
    assert {L.store for L in listings} == set(STORES)
    assert day_date(DAYS - 1).isoformat() == "2026-10-03"


def test_gtins_are_valid_and_in_store_range(market):
    catalog = market[0]
    assert all(p.gtin.startswith("2") and len(p.gtin) == 13 and check_digit_ok(p.gtin) for p in catalog)
    assert len({p.gtin for p in catalog}) == len(catalog)


def test_planted_events(market):
    events = market[3]
    assert sum(e["type"] == "pricing_error" for e in events) == 2
    assert sum(e["type"] == "map_breach" for e in events) == 6


def test_distractor_listings_have_no_truth(market):
    listings = market[2]
    extra = [L for L in listings if L.truth_sku is None]
    assert extra and all(L.brand_shown not in {"Auren", "Kovo", "Brisa"} for L in extra)
