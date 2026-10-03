"""Regenerate everything Northvane reports, from scratch, in about a minute.

  1. start the three demo competitor stores locally
  2. crawl them once a day for 30 simulated days
  3. match their listings to our catalog, and score the matcher against the hidden ground truth
  4. compute the signals and write results/metrics.json

Nothing here is hand-typed: every number in the README and the dashboard comes from this run.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from northvane import db, matching, pipeline, repricing
from northvane import signals as S
from northvane.catalog import DAYS, build_market

OUT = Path(__file__).parent / "results"


def main():
    OUT.mkdir(exist_ok=True)
    t = time.perf_counter()
    con = pipeline.run(OUT / "northvane.db", verbose=False)
    crawl_s = time.perf_counter() - t

    products, listings = db.rows(con, "SELECT * FROM products"), db.rows(con, "SELECT * FROM listings")
    t = time.perf_counter()
    decisions = matching.match(products, listings)
    match_s = time.perf_counter() - t
    pipeline.store_matches(con, decisions)

    _, _, truth_listings, planted = build_market()
    truth = {(L.store, L.listing_id): L.truth_sku for L in truth_listings}
    auto = matching.evaluate(decisions, truth)
    with_review = matching.evaluate(decisions, truth, ("matched", "review"))
    base = matching.evaluate(matching.baseline(products, listings), truth)
    review = [d for d in decisions if d["status"] == "review"]
    by_method = {}
    for d in decisions:
        if d["status"] == "matched":
            by_method[d["method"]] = by_method.get(d["method"], 0) + 1

    runs = db.rows(con, "SELECT * FROM crawl_runs")
    tot = lambda k, store=None: sum(r[k] for r in runs if store is None or r["store"] == store)
    m = S.Market(con)
    d = m.today
    resp = S.response_to_cuts(m)
    metrics = {
        "crawl": {
            "days": DAYS, "seconds": round(crawl_s, 1), "requests": tot("requests"), "not_modified": tot("not_modified"),
            "retries": tot("retries"), "errors": tot("errors"), "robots_blocked": tot("robots_blocked"),
            "observations": db.rows(con, "SELECT COUNT(*) n FROM observations")[0]["n"],
            "quarantined": db.rows(con, "SELECT COUNT(*) n FROM quarantine")[0]["n"],
            "listings": len(listings), "bytes": tot("bytes"),
            "by_store": {s: {"requests": tot("requests", s), "not_modified": tot("not_modified", s),
                             "retries": tot("retries", s), "listings": sum(1 for L in listings if L["store"] == s)}
                         for s in S.STORES},
            "day0_requests": sum(r["requests"] for r in runs if r["day"] == 0),
            "steady_requests_per_day": round(sum(r["requests"] for r in runs if r["day"] > 0) / (DAYS - 1), 1),
        },
        "matching": {
            "seconds": round(match_s, 2), "listings": len(decisions), "auto_matched": len(decisions) - len(review) -
            sum(1 for x in decisions if x["status"] == "unmatched"), "review_queue": len(review),
            "review_correct": sum(1 for x in review if x["sku"] == truth[(x["store"], x["listing_id"])]),
            "unmatched": sum(1 for x in decisions if x["status"] == "unmatched"),
            "not_carried_by_us": sum(1 for v in truth.values() if v is None),
            "by_method": by_method, "auto": auto, "auto_plus_review": with_review, "baseline_fuzzy": base,
        },
        "signals_today": {
            "date": str(S.day_date(d)), "price_index": S.price_index(m, d),
            "store_index": {s: S.store_index(m, d, s) for s in S.STORES},
            "undercuts": len(S.undercuts(m, d)), "map_violations": len(S.map_violations(m, d)),
            "stockouts": len(S.stockouts(m, d)), "pricing_errors_30d": S.pricing_errors(m),
            "planted_pricing_errors": [e for e in planted if e["type"] == "pricing_error"],
            "promos_30d": len(S.promos(m)),
            "opportunities": len(S.opportunities(m, d)),
            "opportunity_monthly": round(sum(o["monthly_gain"] for o in S.opportunities(m, d)), 2),
            "response_to_cuts": resp,
        },
        "repricing_default": {k: v for k, v in repricing.suggest(m).items() if k != "rows"},
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=1))

    c, mt, sg = metrics["crawl"], metrics["matching"], metrics["signals_today"]
    lines = [
        f"Crawl: {c['days']} days, {c['requests']:,} requests in {c['seconds']} s, {c['observations']:,} price observations",
        f"  {c['not_modified']:,} answered 304 Not Modified, {c['retries']} retried (429/503), {c['errors']} failed, "
        f"{c['robots_blocked']:,} links skipped because robots.txt disallows them, {c['quarantined']} rows quarantined",
        f"  day 1 full crawl {c['day0_requests']} requests, then {c['steady_requests_per_day']} a day on average",
        f"Matching: {mt['listings']} listings in {mt['seconds']} s -> {mt['auto_matched']} auto-matched "
        f"({mt['by_method']}), {mt['review_queue']} to review, {mt['unmatched']} unmatched",
        f"  auto-match precision {mt['auto']['precision']:.1%}, recall {mt['auto']['recall']:.1%}, F1 {mt['auto']['f1']:.3f}",
        f"  baseline fuzzy title match: precision {mt['baseline_fuzzy']['precision']:.1%}, recall "
        f"{mt['baseline_fuzzy']['recall']:.1%}, F1 {mt['baseline_fuzzy']['f1']:.3f} ({mt['baseline_fuzzy']['fp']} wrong matches)",
        f"Today ({sg['date']}): price index {sg['price_index']}, {sg['undercuts']} undercuts, {sg['map_violations']} MAP "
        f"violations, {sg['stockouts']} competitor stock-outs, {len(sg['pricing_errors_30d'])} pricing errors caught in 30 days "
        f"(planted: {len(sg['planted_pricing_errors'])})",
        f"  Brightcart followed {resp['by_store']['Brightcart']['followed']} of {resp['by_store']['Brightcart']['cut_products']} "
        f"of our price cuts, median lag {resp['by_store']['Brightcart']['median_lag_days']} day",
        f"  {sg['opportunities']} products with headroom worth ${sg['opportunity_monthly']:,.0f}/month at current volume",
    ]
    (OUT / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
