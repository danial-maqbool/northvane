"""Product matching: which competitor listing is which of our products.

Pipeline, cheapest evidence first:
  1. GTIN equal                        -> match (score 1.00)
  2. manufacturer part number equal    -> match (score 0.99)
  3. block by brand, then score every pair:
       0.45 x TF-IDF cosine on character 3-5 grams (robust to "Halo700" vs "Halo 700")
       0.25 x token-set similarity
       0.30 x model check (is OUR model token in THEIR title, or a sibling model's?)
     and an attribute guard: a colour family, screen size, capacity or model that disagrees is a
     hard conflict (score x 0.35). Colour missing from their title sends it to review (x 0.78).
  4. one-to-one assignment per store (Hungarian algorithm), so two listings never claim one product.
  5. score >= AUTO -> matched; REVIEW <= score < AUTO -> human review queue; below -> unmatched.

The colour lexicon below is generic retail vocabulary, written independently of the generator.
"""
from __future__ import annotations

import re
from collections import defaultdict

import numpy as np
from rapidfuzz import fuzz
from scipy.optimize import linear_sum_assignment
from sklearn.feature_extraction.text import TfidfVectorizer

AUTO, REVIEW = 0.80, 0.55

COLOR_FAMILIES = {
    "black": ["midnight black", "jet black", "black", "onyx", "obsidian"],
    "white": ["frost white", "snow white", "arctic", "white", "snow", "ivory", "frost"],
    "warm white": ["warm white", "soft white"],
    "multicolor": ["multicolor", "rgb color", "color", "colour"],
    "silver": ["silver titanium", "platinum", "silver"],
    "titanium": ["titanium"],
    "grey": ["slate grey", "stone grey", "slate", "stone", "charcoal", "graphite", "grey", "gray"],
    "beige": ["desert sand", "sand", "champagne", "starlight", "beige"],
    "blue": ["midnight blue", "midnight", "navy", "blue"],
    "red": ["coral red", "coral", "red"],
    "pink": ["blush pink", "rose", "blush", "pink"],
    "copper": ["rose copper", "copper"],
    "gold": ["satin gold", "gold"],
    "steel": ["stainless steel", "steel", "stainless"],
}
_COLOR_PHRASES = sorted(((ph, fam) for fam, phs in COLOR_FAMILIES.items() for ph in phs), key=lambda x: -len(x[0]))
# "silver titanium" is titanium, not silver
_COLOR_PHRASES = [("silver titanium", "titanium")] + [x for x in _COLOR_PHRASES if x[0] != "silver titanium"]

SYN = [(r'"', " inch "), (r"(\d+)-inch", r"\1 inch"), (r"\banc\b", "noise cancelling"), (r"noise-cancelling", "noise cancelling"), (r"\btws\b", "true wireless"),
       (r"true-wireless", "true wireless"), (r"\bbt\b", "bluetooth"), (r"\bvac\b", "vacuum"), (r"\+", " and "),
       (r"\bgray\b", "grey")]


def color_family(text: str) -> str | None:
    t = " " + text.lower() + " "
    for ph, fam in _COLOR_PHRASES:
        if re.search(rf"(?<![a-z]){re.escape(ph)}(?![a-z])", t):
            return fam
    return None


def numbers(text: str) -> dict:
    t = text.lower().replace('"', " inch ")
    out = {}
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:l|liter|litre)\b", t)
    if m:
        out["ml"] = round(float(m.group(1)) * 1000)
    m = re.search(r"(\d{3,4})\s*ml\b", t)
    if m:
        out["ml"] = int(m.group(1))
    m = re.search(r"(\d{2})\s*(?:-?\s*inch|in)\b", t)
    if m:
        out["inch"] = int(m.group(1))
    m = re.search(r"(\d{2})\s*mm\b", t)
    if m:
        out["mm"] = int(m.group(1))
    return out


class Normalizer:
    """Knows our own product line names, so fused tokens like 'halo700' or 'pebblepro' can be split."""

    def __init__(self, line_words: set[str]):
        self.lines = sorted({w.lower() for w in line_words}, key=len, reverse=True)

    def __call__(self, title: str) -> str:
        t = title.lower().replace("–", " ").replace("—", " ")
        for a, b in SYN:
            t = re.sub(a, b, t)
        t = re.sub(r"[(),:/]", " ", t)
        toks = []
        for tok in t.split():
            for ln in self.lines:
                if tok.startswith(ln) and len(tok) > len(ln) and tok[len(ln)].isalnum():
                    toks += [ln, tok[len(ln):]]
                    break
            else:
                toks.append(tok)
        t = " ".join(toks)
        t = re.sub(r"(\d+)-(cup|pack)", r"\1\2", t)
        t = re.sub(r"\bgen\s*(\d)", r"gen\1", t)
        t = re.sub(r"\bsize\s*(\d+)", r"size\1", t)
        t = re.sub(r"(\d+)\s*mm\b", r"\1mm", t)
        return re.sub(r"\s+", " ", t).strip()


def model_token(p: dict, norm: Normalizer) -> str:
    return norm(p["model"]).replace(" ", "")


def model_check(ours: str, siblings: set[str], their_tokens: set[str]) -> str:
    if ours in their_tokens:
        return "ok"
    if siblings & their_tokens:
        return "conflict"
    return "unknown"


def score_pair(p, L, ntitle_p, ntitle_l, cos, model_state):
    fz = fuzz.token_set_ratio(ntitle_p, ntitle_l) / 100
    mscore = {"ok": 1.0, "unknown": 0.5, "conflict": 0.0}[model_state]
    s = 0.45 * cos + 0.25 * fz + 0.30 * mscore
    cp, cl = color_family(p["title"]), color_family(L["title"])
    np_, nl = numbers(p["title"]), numbers(L["title"])
    conflicts = []
    if model_state == "conflict":
        conflicts.append("model")
    if cp and cl and cp != cl:
        conflicts.append("colour")
    for k in ("ml", "inch", "mm"):
        if k in np_ and k in nl and np_[k] != nl[k]:
            conflicts.append(k)
    color_state = "ok" if (cp and cl and cp == cl) else ("missing" if cp and not cl else ("conflict" if cp and cl else "n/a"))
    if conflicts:
        s *= 0.35
    elif color_state == "missing":                  # their title has no colour, ours does: let a person decide
        s *= 0.78
    ev = {"tfidf": round(float(cos), 3), "fuzzy": round(fz, 3), "model": model_state, "colour": color_state,
          "colour_ours": cp, "colour_theirs": cl, "conflicts": conflicts}
    return min(s, 0.98), ev


def match(products: list[dict], listings: list[dict]) -> list[dict]:
    """Return one decision per listing: {store, listing_id, sku, score, method, status, evidence}."""
    norm = Normalizer({p["line"] for p in products})
    by_gtin = {p["gtin"]: p for p in products}
    by_mpn = {p["mpn"]: p for p in products}
    brand_key = lambda b: re.sub(r"[^a-z]", "", (b or "").lower())
    by_brand = defaultdict(list)
    for p in products:
        by_brand[brand_key(p["brand"])].append(p)
    line_models = defaultdict(set)
    for p in products:
        line_models[(p["brand"], p["line"])].add(model_token(p, norm))

    np_titles = {p["sku"]: norm(p["title"]) for p in products}
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
    vec.fit(list(np_titles.values()) + [norm(L["title"]) for L in listings])
    P = {p["sku"]: vec.transform([np_titles[p["sku"]]]) for p in products}

    decisions = []
    for store in sorted({L["store"] for L in listings}):
        Ls = [L for L in listings if L["store"] == store]
        fixed, rest = [], []
        for L in Ls:
            if L.get("gtin") and L["gtin"] in by_gtin:
                fixed.append((L, by_gtin[L["gtin"]], 1.0, "gtin", {"gtin": True}))
            elif L.get("mpn") and L["mpn"] in by_mpn:
                fixed.append((L, by_mpn[L["mpn"]], 0.99, "mpn", {"mpn": True}))
            else:
                rest.append(L)
        taken = {p["sku"] for _, p, *_ in fixed}
        for L, p, s, m, ev in fixed:
            decisions.append(dict(store=store, listing_id=L["listing_id"], sku=p["sku"], score=s, method=m,
                                  status="matched", evidence=ev))
        cands = [p for p in products if p["sku"] not in taken]
        idx = {p["sku"]: i for i, p in enumerate(cands)}
        S = np.zeros((len(rest), len(cands)))
        EV = {}
        for i, L in enumerate(rest):
            nl = norm(L["title"])
            toks = set(nl.split())
            vl = vec.transform([nl])
            bk = brand_key(L.get("brand"))
            if bk:                                              # a brand we don't sell is never our product
                pool = by_brand.get(bk, [])
            else:                                               # no brand field: look for our brands in the title
                pool = [p for p in cands if brand_key(p["brand"]) in re.sub(r"[^a-z]", "", nl)]
            for p in pool:
                if p["sku"] not in idx:
                    continue
                mt = model_token(p, norm)
                sib = line_models[(p["brand"], p["line"])] - {mt}
                ms = model_check(mt, sib, toks)
                cos = float((P[p["sku"]] @ vl.T).toarray()[0, 0])
                s, ev = score_pair(p, L, np_titles[p["sku"]], nl, cos, ms)
                S[i, idx[p["sku"]]] = s
                EV[(i, idx[p["sku"]])] = ev
        if rest:
            r_ind, c_ind = linear_sum_assignment(-S)
            assigned = {}
            for i, j in zip(r_ind, c_ind):
                assigned[i] = j
            for i, L in enumerate(rest):
                j = assigned.get(i)
                s = S[i, j] if j is not None else 0.0
                if j is None or s < REVIEW:
                    best = int(np.argmax(S[i])) if S.shape[1] else None
                    decisions.append(dict(store=store, listing_id=L["listing_id"], sku=None, score=round(float(s), 3),
                                          method="model", status="unmatched",
                                          evidence=EV.get((i, best), {}) if best is not None else {}))
                    continue
                decisions.append(dict(store=store, listing_id=L["listing_id"], sku=cands[j]["sku"],
                                      score=round(float(s), 3), method="model",
                                      status="matched" if s >= AUTO else "review", evidence=EV.get((i, j), {})))
    return decisions


def baseline(products: list[dict], listings: list[dict], threshold=85) -> list[dict]:
    """What most scrapers do: fuzzy title match to the nearest product, no blocking, no attribute checks."""
    out = []
    titles = [p["title"].lower() for p in products]
    for L in listings:
        sc = [fuzz.token_set_ratio(L["title"].lower(), t) for t in titles]
        j = int(np.argmax(sc))
        out.append(dict(store=L["store"], listing_id=L["listing_id"], sku=products[j]["sku"] if sc[j] >= threshold else None,
                        score=sc[j] / 100))
    return out


def evaluate(decisions: list[dict], truth: dict[tuple, str | None], status_ok=("matched",)) -> dict:
    tp = fp = fn = 0
    for d in decisions:
        t = truth[(d["store"], d["listing_id"])]
        pred = d["sku"] if d.get("status", "matched") in status_ok else None
        if pred is not None and pred == t:
            tp += 1
        elif pred is not None:
            fp += 1
            if t is not None:
                fn += 1
        elif t is not None:
            fn += 1
    prec = tp / (tp + fp) if tp + fp else 1.0
    rec = tp / (tp + fn) if tp + fn else 1.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0}
