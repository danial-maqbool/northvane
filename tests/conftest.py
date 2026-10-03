"""Shared fixtures. `oracle_db` loads the generator's data straight into the schema (no crawl), so signal
and API tests run in about a second; the crawler has its own end-to-end test."""
import pytest

from northvane import db, matching, pipeline
from northvane.catalog import DAYS, build_market


@pytest.fixture(scope="session")
def market():
    return build_market()


@pytest.fixture(scope="session")
def oracle_db(tmp_path_factory, market):
    catalog, ours, listings, _ = market
    path = tmp_path_factory.mktemp("nv") / "oracle.db"
    con = db.reset(path)
    pipeline.load_catalog(con)
    for L in listings:
        con.execute("INSERT INTO listings VALUES (?,?,?,?,?,?,?,?,?)",
                    (L.store, L.listing_id, "/x", L.title, L.brand_shown, L.category, L.gtin, L.mpn, 0))
        con.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?)",
                        [(d, L.store, L.listing_id, L.prices[d], L.list_prices[d], int(L.in_stock[d])) for d in range(DAYS)])
    con.commit()
    pipeline.store_matches(con, matching.match(db.rows(con, "SELECT * FROM products"), db.rows(con, "SELECT * FROM listings")))
    return path
