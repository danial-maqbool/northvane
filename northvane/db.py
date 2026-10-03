"""SQLite storage. One file, no server, easy to inspect."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
  sku TEXT PRIMARY KEY, title TEXT, brand TEXT, category TEXT, line TEXT, model TEXT, variant TEXT,
  gtin TEXT, mpn TEXT, cost REAL, map_price REAL, daily_units REAL);
CREATE TABLE IF NOT EXISTS our_prices (day INT, sku TEXT, price REAL, PRIMARY KEY (day, sku));
CREATE TABLE IF NOT EXISTS listings (
  store TEXT, listing_id TEXT, url TEXT, title TEXT, brand TEXT, category TEXT, gtin TEXT, mpn TEXT,
  first_seen INT, PRIMARY KEY (store, listing_id));
CREATE TABLE IF NOT EXISTS observations (
  day INT, store TEXT, listing_id TEXT, price REAL, list_price REAL, in_stock INT,
  PRIMARY KEY (day, store, listing_id));
CREATE TABLE IF NOT EXISTS quarantine (day INT, store TEXT, listing_id TEXT, reason TEXT, raw TEXT);
CREATE TABLE IF NOT EXISTS crawl_runs (
  day INT, store TEXT, duration_s REAL, requests INT, ok INT, not_modified INT, retries INT, errors INT,
  robots_blocked INT, items INT, new_items INT, changed_items INT, bytes INT, PRIMARY KEY (day, store));
CREATE TABLE IF NOT EXISTS crawl_log (day INT, store TEXT, t_ms REAL, url TEXT, status INT, ms REAL, bytes INT, note TEXT);
CREATE TABLE IF NOT EXISTS matches (
  store TEXT, listing_id TEXT, sku TEXT, score REAL, method TEXT, status TEXT, evidence TEXT,
  PRIMARY KEY (store, listing_id));
"""


def connect(path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def reset(path: str | Path) -> sqlite3.Connection:
    p = Path(path)
    if p.exists():
        p.unlink()
    return connect(p)


def rows(con, sql, *args):
    return [dict(r) for r in con.execute(sql, args).fetchall()]


def dumps(x) -> str:
    return json.dumps(x, separators=(",", ":"))
