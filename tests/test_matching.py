import pytest

from northvane import db, matching
from northvane.matching import Normalizer, color_family, model_check, numbers


@pytest.fixture(scope="module")
def norm():
    return Normalizer({"Halo", "Pebble", "Orbit", "Vista"})


def test_fused_tokens_are_split(norm):
    assert "halo 700" in norm("AUREN Halo700 ANC Wireless Headphones")
    assert "pebble pro" in norm("KOVO PebblePro TWS Earbuds")
    assert "noise cancelling" in norm("Halo700 ANC")
    assert "true wireless" in norm("TWS Earbuds")


@pytest.mark.parametrize("a,b", [("Midnight Black", "Black"), ("Onyx", "Black"), ("Platinum", "Silver"),
                                 ("Champagne", "Starlight"), ("Slate Grey", "Slate"), ("Gray", "Grey"),
                                 ("Silver Titanium", "Titanium"), ("Soft White", "Warm White")])
def test_colour_synonyms(a, b):
    assert color_family(a) == color_family(b) is not None


@pytest.mark.parametrize("a,b", [("Black", "Silver"), ("Midnight", "Starlight"), ("Graphite", "Snow"), ("Warm White", "RGB Color")])
def test_colour_siblings_differ(a, b):
    assert color_family(a) != color_family(b)


def test_units_normalise():
    assert numbers("Espresso Machine, 2 L")["ml"] == numbers("Espresso Machine - 2000 ml")["ml"] == 2000
    assert numbers('Vista 32" 4K Monitor')["inch"] == numbers("Vista 32-inch monitor")["inch"] == 32


def test_model_check():
    assert model_check("700", {"500"}, {"halo", "700"}) == "ok"
    assert model_check("700", {"500"}, {"halo", "500"}) == "conflict"
    assert model_check("700", {"500"}, {"halo"}) == "unknown"


def test_quality_on_full_market(oracle_db, market):
    con = db.connect(oracle_db)
    dec = matching.match(db.rows(con, "SELECT * FROM products"), db.rows(con, "SELECT * FROM listings"))
    truth = {(L.store, L.listing_id): L.truth_sku for L in market[2]}
    auto = matching.evaluate(dec, truth)
    base = matching.evaluate(matching.baseline(db.rows(con, "SELECT * FROM products"), db.rows(con, "SELECT * FROM listings")), truth)
    assert auto["precision"] >= 0.99
    assert auto["recall"] >= 0.95
    assert auto["f1"] > base["f1"] + 0.2
    # never two listings from one store on the same product
    seen = {}
    for d in dec:
        if d["sku"] and d["status"] != "unmatched":
            assert (d["store"], d["sku"]) not in seen
            seen[(d["store"], d["sku"])] = d["listing_id"]


def test_brands_we_dont_sell_are_never_matched(oracle_db, market):
    con = db.connect(oracle_db)
    dec = matching.match(db.rows(con, "SELECT * FROM products"), db.rows(con, "SELECT * FROM listings"))
    truth = {(L.store, L.listing_id): L.truth_sku for L in market[2]}
    assert all(d["status"] == "unmatched" for d in dec if truth[(d["store"], d["listing_id"])] is None)
