import pytest

from northvane import db, repricing
from northvane import signals as S


@pytest.fixture(scope="module")
def m(oracle_db):
    return S.Market(db.connect(oracle_db))


def test_pricing_errors_are_exactly_the_planted_ones(m, market):
    planted = {(e["store"], e["listing"], e["day"]) for e in market[3] if e["type"] == "pricing_error"}
    found = {(e["store"], e["listing_id"], e["day"]) for e in S.pricing_errors(m)}
    assert found == planted


def test_map_violations_are_real(m):
    for e in S.map_violations(m, m.today):
        assert e["price"] < m.products[e["sku"]]["map_price"]
        assert e["since"] <= e["day"]


def test_brightcart_follows_our_cuts_and_voltaro_does_not(m):
    r = S.response_to_cuts(m)["by_store"]
    assert r["Brightcart"]["followed"] / r["Brightcart"]["cut_products"] > 0.7
    assert r["Brightcart"]["median_lag_days"] == 1
    assert r["Voltaro"]["followed"] / r["Voltaro"]["cut_products"] < 0.1


def test_index_bounds(m):
    assert 90 < S.price_index(m, m.today) < 110
    assert S.store_index(m, m.today, "Brightcart") < 100 < S.store_index(m, m.today, "Voltaro")


@pytest.mark.parametrize("strategy", ["beat_lowest", "match_lowest", "index"])
@pytest.mark.parametrize("min_margin,max_move", [(15, 8), (30, 3)])
def test_repricing_guardrails(m, strategy, min_margin, max_move):
    r = repricing.suggest(m, strategy=strategy, min_margin=min_margin, max_move=max_move)
    for row in r["rows"]:
        p = m.products[row["sku"]]
        assert row["suggested"] >= p["cost"] * (1 + min_margin / 100) - 0.01, row
        if p["map_price"]:
            assert row["suggested"] >= p["map_price"] - 0.01, row
        floor_hit = "margin" in row["guards"] or "MAP" in row["guards"]
        if not floor_hit:
            assert abs(row["delta_pct"]) <= max_move + 1.0, row      # +1 for .99 rounding


def test_ignoring_map_can_go_lower(m):
    with_map = repricing.suggest(m, respect_map=True, min_margin=5)
    without = repricing.suggest(m, respect_map=False, min_margin=5)
    assert without["monthly_margin_new"] <= with_map["monthly_margin_new"]
