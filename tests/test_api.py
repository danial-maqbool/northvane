import importlib
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(oracle_db):
    os.environ["NORTHVANE_DB"] = str(oracle_db)
    import northvane.api as api
    importlib.reload(api)
    return TestClient(api.app)


@pytest.mark.parametrize("path", ["/api/meta", "/api/overview", "/api/products", "/api/product/LL-0001",
                                  "/api/heatmap", "/api/review", "/api/reprice", "/api/crawls", "/"])
def test_endpoints(client, path):
    assert client.get(path).status_code == 200


def test_overview_numbers_are_consistent(client):
    o = client.get("/api/overview").json()
    assert o["kpis"]["products_tracked"] <= o["kpis"]["catalog"]
    assert len(o["index_series"]) == 30 and o["index_series"][-1] == o["kpis"]["price_index"]
    assert {c["category"] for c in o["compass"]} == set(client.get("/api/meta").json()["categories"])


def test_review_decision_persists(client):
    items = client.get("/api/review").json()["items"]
    if not items:
        pytest.skip("empty queue")
    it = items[0]
    before = client.get("/api/review").json()["counts"]
    after = client.post(f"/api/review/{it['store']}/{it['listing_id']}", json={"decision": "accept"}).json()
    assert after["review"] == before["review"] - 1 and after["matched"] == before["matched"] + 1
    assert client.post(f"/api/review/{it['store']}/{it['listing_id']}", json={"decision": "maybe"}).status_code == 400


def test_alert_preview(client):
    r = client.post("/api/alerts/preview", json={"store": "any", "condition": "undercut", "threshold": 3}).json()
    assert r["fires"] == sum(r["by_day"]) and len(r["by_day"]) == 30
    r2 = client.post("/api/alerts/preview", json={"store": "any", "condition": "undercut", "threshold": 10}).json()
    assert r2["fires"] <= r["fires"]


def test_unknown_product_404(client):
    assert client.get("/api/product/NOPE").status_code == 404
