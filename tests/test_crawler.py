"""End to end: real HTTP against the demo stores, two simulated days."""
import asyncio

import pytest
from pydantic import ValidationError

from northvane import db, pipeline
from northvane.crawler import Row, money


def test_money_parsing():
    assert money("$1,299.99") == 1299.99
    assert money("Now $ 89") == 89.0
    assert money("no price") is None


def test_row_validation_rejects_bad_rows():
    ok = dict(listing_id="AB12", url="/x", title="A product", price=10.0, in_stock=True)
    Row(**ok)
    with pytest.raises(ValidationError):
        Row(**{**ok, "price": 0})
    with pytest.raises(ValidationError):
        Row(**{**ok, "gtin": "2000000000001"})          # wrong check digit
    with pytest.raises(ValidationError):
        Row(**{**ok, "title": ""})


@pytest.fixture(scope="module")
def crawled(tmp_path_factory):
    path = tmp_path_factory.mktemp("crawl") / "c.db"
    con = db.reset(path)
    pipeline.load_catalog(con)
    port = pipeline.free_port()
    with pipeline.StoreServer(port):
        asyncio.run(pipeline.crawl_all(con, f"http://127.0.0.1:{port}", days=2))
    return con


def test_every_listing_observed_every_day(crawled):
    n = db.rows(crawled, "SELECT COUNT(*) n FROM listings")[0]["n"]
    assert n == 470
    for d in (0, 1):
        assert db.rows(crawled, "SELECT COUNT(*) n FROM observations WHERE day=?", d)[0]["n"] == n


def test_nothing_failed_or_quarantined(crawled):
    runs = db.rows(crawled, "SELECT * FROM crawl_runs")
    assert sum(r["errors"] for r in runs) == 0
    assert db.rows(crawled, "SELECT COUNT(*) n FROM quarantine")[0]["n"] == 0


def test_day_two_is_cheap(crawled):
    r = {(x["day"], x["store"]): x for x in db.rows(crawled, "SELECT * FROM crawl_runs")}
    assert r[(1, "Brightcart")]["not_modified"] > 100                    # ETag / 304 works
    assert r[(1, "Hearth & Hollow")]["requests"] < r[(0, "Hearth & Hollow")]["requests"] / 5
    assert r[(1, "Voltaro")]["requests"] < r[(0, "Voltaro")]["requests"] / 5


def test_rate_limits_and_robots(crawled):
    r = db.rows(crawled, "SELECT * FROM crawl_runs WHERE day=0")
    assert sum(x["retries"] for x in r) > 0                             # 429 / 503 were hit and retried
    assert sum(x["robots_blocked"] for x in r) > 0
    paths = [x["url"] for x in db.rows(crawled, "SELECT url FROM crawl_log")]
    assert not any("/wishlist" in p or "/cart" in p or "/account" in p for p in paths)


def test_parsed_prices_match_the_store(crawled, market):
    truth = {(L.store, L.listing_id): L for L in market[2]}
    for o in db.rows(crawled, "SELECT * FROM observations WHERE day=1"):
        L = truth[(o["store"], o["listing_id"])]
        assert abs(o["price"] - L.prices[1]) < 0.005
        assert bool(o["in_stock"]) == L.in_stock[1]
