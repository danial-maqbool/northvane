"""Replays 30 days: moves the demo stores' clock, crawls all three stores, stores what came back."""
from __future__ import annotations

import asyncio
import socket
import threading
import time

import httpx
import uvicorn

from . import db
from .catalog import DAYS, build_market
from .crawler import crawl_store

STORES = ["Brightcart", "Voltaro", "Hearth & Hollow"]


def free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class StoreServer:
    def __init__(self, port: int):
        from .stores import app
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        while not self.server.started:
            time.sleep(0.02)
        return self

    def __exit__(self, *a):
        self.server.should_exit = True
        self.thread.join(timeout=5)


def load_catalog(con):
    catalog, ours, _, _ = build_market()           # our own catalog comes from our own store export
    con.executemany("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(p.sku, p.title, p.brand, p.category, p.line, p.model, p.variant, p.gtin, p.mpn, p.cost,
                      p.map_price, p.daily_units) for p in catalog])
    con.executemany("INSERT INTO our_prices VALUES (?,?,?)",
                    [(d, sku, path[d]) for sku, path in ours.items() for d in range(DAYS)])
    con.commit()


async def crawl_all(con, base: str, days: int = DAYS, log_days=(0, DAYS - 1)):
    known = {s: {} for s in STORES}
    etags = {s: {} for s in STORES}
    async with httpx.AsyncClient(timeout=10, limits=httpx.Limits(max_connections=40)) as client:
        for d in range(days):
            await client.post(base + "/_sim/clock", json={"day": d})
            t0 = time.perf_counter()
            results = await asyncio.gather(*(crawl_store(client, base, s, known[s], etags[s], t0) for s in STORES))
            for s, (good, bad, st, dur) in zip(STORES, results):
                new = changed = 0
                prev_obs = {r["listing_id"]: r for r in db.rows(
                    con, "SELECT listing_id, price, in_stock FROM observations WHERE day=? AND store=?", d - 1, s)}
                for r in good:
                    if r["listing_id"] not in known[s]:
                        new += 1
                        con.execute("INSERT OR REPLACE INTO listings VALUES (?,?,?,?,?,?,?,?,?)",
                                    (s, r["listing_id"], r["url"], r["title"], r["brand"], r["category"], r["gtin"],
                                     r["mpn"], d))
                    else:
                        p = prev_obs.get(r["listing_id"])
                        if p and (abs(p["price"] - r["price"]) > 0.001 or bool(p["in_stock"]) != r["in_stock"]):
                            changed += 1
                    known[s][r["listing_id"]] = r
                    con.execute("INSERT OR REPLACE INTO observations VALUES (?,?,?,?,?,?)",
                                (d, s, r["listing_id"], r["price"], r["list_price"], int(r["in_stock"])))
                for x, why in bad:
                    con.execute("INSERT INTO quarantine VALUES (?,?,?,?,?)", (d, s, x.get("listing_id"), why, db.dumps(x)))
                con.execute("INSERT OR REPLACE INTO crawl_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (d, s, round(dur, 3), st.requests, st.ok, st.not_modified, st.retries, st.errors,
                             st.robots_blocked, len(good), new, changed, st.bytes))
                if d in log_days:
                    con.executemany("INSERT INTO crawl_log VALUES (?,?,?,?,?,?,?,?)",
                                    [(d, s, round(t, 1), u, code, round(ms, 1), b, note) for t, u, code, ms, b, note in st.log])
            con.commit()


def run(db_path, verbose=True):
    con = db.reset(db_path)
    load_catalog(con)
    port = free_port()
    t = time.perf_counter()
    with StoreServer(port):
        asyncio.run(crawl_all(con, f"http://127.0.0.1:{port}"))
    if verbose:
        print(f"crawled {DAYS} days in {time.perf_counter() - t:.1f} s")
    return con


def store_matches(con, decisions):
    con.execute("DELETE FROM matches")
    con.executemany("INSERT INTO matches VALUES (?,?,?,?,?,?,?)",
                    [(d["store"], d["listing_id"], d["sku"], d["score"], d["method"], d["status"], db.dumps(d["evidence"]))
                     for d in decisions])
    con.commit()
