import { sparkline, ring, lineChart, compass, histogram, bars, stacked, heatColor, showTip, hideTip } from "./charts.js";

/* ---------------------------------------------------------------- basics */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const api = (p, o) => fetch(p, o).then((r) => { if (!r.ok) throw new Error(p + " " + r.status); return r.json(); });
const post = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const usd0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const money = (v) => (v == null ? "—" : usd.format(v));
const kmoney = (v) => {
  const a = Math.abs(v), s = v < 0 ? "−$" : "$";
  return a >= 1e6 ? s + (a / 1e6).toFixed(2) + "M" : a >= 1000 ? s + (a / 1000).toFixed(1) + "k" : usd0.format(v);
};
const pct = (v, d = 1) => (v == null ? "—" : (v > 0 ? "+" : "") + v.toFixed(d) + "%");
const STORES = ["Brightcart", "Voltaro", "Hearth & Hollow"];
const SC = { Brightcart: "var(--s-bc)", Voltaro: "var(--s-vo)", "Hearth & Hollow": "var(--s-hh)", ours: "var(--ours)" };
const short = (s) => (s === "Hearth & Hollow" ? "Hearth" : s);
const chip = (s) => `<span class="store-chip"><i style="background:${SC[s]}"></i>${esc(s)}</span>`;
const ICON = {
  error: '<svg viewBox="0 0 24 24"><path d="M12 3l9 16H3zM12 10v4M12 17h.01"/></svg>',
  map: '<svg viewBox="0 0 24 24"><path d="M12 3v18M5 8l7-5 7 5M5 16l7 5 7-5"/></svg>',
  undercut: '<svg viewBox="0 0 24 24"><path d="M3 7l7 7 4-4 7 7M21 11v6h-6"/></svg>',
  stock: '<svg viewBox="0 0 24 24"><path d="M4 7l8-4 8 4v10l-8 4-8-4zM4 7l16 10"/></svg>',
  promo: '<svg viewBox="0 0 24 24"><path d="M20 12l-8 8-9-9V3h8zM7.5 7.5h.01"/></svg>',
  opp: '<svg viewBox="0 0 24 24"><path d="M3 17l6-6 4 4 8-8M15 7h6v6"/></svg>',
  check: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M5 12l5 5 9-10"/></svg>',
};
const state = { meta: null, ov: null, products: null, crawls: null, rules: null };
let L = [], TL = [];                               // day labels (short, long)

/* ---------------------------------------------------------------- preferences (accessibility) */
const PREF_KEY = "northvane.prefs";
const prefs = Object.assign({ theme: "dark", cvd: "default", motion: "system", fs: 1, density: "comfortable", tables: false, announce: true },
  (() => { try { return JSON.parse(localStorage.getItem(PREF_KEY)) || {}; } catch { return {}; } })());
function applyPrefs() {
  const h = document.documentElement;
  h.dataset.theme = prefs.theme;
  h.dataset.cvd = prefs.cvd;
  h.style.setProperty("--fs", prefs.fs);
  h.classList.toggle("reduce-motion", prefs.motion === "reduced");
  h.classList.toggle("force-motion", prefs.motion === "full");
  h.classList.toggle("compact", prefs.density === "compact");
  try { localStorage.setItem(PREF_KEY, JSON.stringify(prefs)); } catch { /* private mode: keep in memory */ }
}
applyPrefs();
const announce = (msg) => { if (!prefs.announce) return; const sr = $("#sr"); sr.textContent = ""; setTimeout(() => (sr.textContent = msg), 40); };
function toast(title, sub = "", icon = ICON.check) {
  const t = document.createElement("div");
  t.className = "toast";
  t.innerHTML = `<span class="ti">${icon}</span><div><b>${esc(title)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</div>`;
  $("#toasts").append(t);
  setTimeout(() => { t.style.transition = "opacity .4s, transform .4s"; t.style.opacity = 0; t.style.transform = "translateY(8px)"; setTimeout(() => t.remove(), 400); }, 3800);
}
function countUp(root) {
  const reduce = document.documentElement.classList.contains("reduce-motion") || (prefs.motion !== "full" && matchMedia("(prefers-reduced-motion: reduce)").matches);
  for (const el of $$("[data-count]", root)) {
    const end = +el.dataset.count, dec = +(el.dataset.dec || 0), pre = el.dataset.pre || "", suf = el.dataset.suf || "";
    const f = (v) => pre + v.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec }) + suf;
    if (reduce) { el.textContent = f(end); continue; }
    const t0 = performance.now(), dur = 1200 + Math.random() * 300;
    const step = (t) => { const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 4); el.textContent = f(end * e); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }
}

/* ---------------------------------------------------------------- router */
const VIEWS = {
  pulse: { title: "Market pulse", sub: "Today across 3 competitors", render: renderPulse },
  products: { title: "Products", sub: "198 products · prices crawled daily", render: renderProducts },
  matching: { title: "Matching", sub: "Which competitor listing is which of your products", render: renderMatching },
  repricing: { title: "Repricing studio", sub: "Guard-railed suggestions · nothing is pushed without approval", render: renderRepricing },
  alerts: { title: "Alerts", sub: "Rules tested against the last 30 days before you save them", render: renderAlerts },
  crawler: { title: "Crawler", sub: "Polite, change-aware collection from 3 stores", render: renderCrawler },
};
let firstRoute = true;
async function route() {
  const key = (location.hash.match(/^#\/(\w+)/) || [, "pulse"])[1];
  const v = VIEWS[key] ? key : "pulse";
  $$(".nav a").forEach((a) => { if (a.dataset.view !== v) a.removeAttribute("aria-current"); else a.setAttribute("aria-current", "page"); });
  $("#crumb-sec").textContent = VIEWS[v].title;
  $("#crumb-sub").textContent = VIEWS[v].sub;
  document.title = `${VIEWS[v].title} · Northvane`;
  const view = $("#view");
  view.innerHTML = "";
  hideTip();
  await VIEWS[v].render(view);
  countUp(view);
  if (!firstRoute) { $("#main").focus({ preventScroll: true }); scrollTo({ top: 0 }); announce(`${VIEWS[v].title} page`); }
  firstRoute = false;
}

/* ---------------------------------------------------------------- PULSE */
const SIG = {
  pricing_error: (e) => ({ k: "error", t: "error", h: `Likely pricing error at ${short(e.store)}`, s: `${e.title} listed at ${money(e.price)}, usually ${money(e.typical)} (−${e.drop_pct}%) · ${L[e.day]}` }),
  map_violation: (e) => ({ k: "map", t: "map", h: `Below MAP at ${short(e.store)}`, s: `${e.title}: ${money(e.price)} vs MAP ${money(e.map)} (−${e.below_pct}%) · since ${L[e.since]}` }),
  undercut: (e) => ({ k: "undercut", t: "undercut", h: `New undercut by ${short(e.store)}`, s: `${e.title}: ${money(e.price)} vs your ${money(e.ours)} (−${e.under_pct}%)` }),
  stockout: (e) => ({ k: "stock", t: "stock", h: `Out of stock at ${short(e.store)}`, s: `${e.title} · since ${L[e.since]} · hold your price` }),
  promo: (e) => ({ k: "promo", t: "promo", h: `Flash sale at ${short(e.store)}`, s: `${e.title} −${e.depth_pct}% · ${L[e.start]}${e.end > e.start ? "–" + L[e.end] : ""}` }),
  opportunity: (e) => ({ k: "opp", t: "opp", h: `Room to raise · +${kmoney(e.monthly_gain)}/mo`, s: `${e.title}: you ${money(e.ours)}, lowest rival ${money(e.lowest)} → ${money(e.target)}` }),
};
const FEED_TABS = [["all", "All"], ["error", "Errors"], ["map", "MAP"], ["undercut", "Undercuts"], ["stock", "Stock"], ["promo", "Promos"], ["opp", "Upside"]];

async function renderPulse(view) {
  const ov = (state.ov ||= await api("/api/overview"));
  const k = ov.kpis, d7 = k.price_index - k.price_index_7d;
  const stores = STORES.map((s) => ({ s, now: ov.store_index_series[s].at(-1), series: ov.store_index_series[s] }));
  view.innerHTML = `
  <section class="row r-hero">
    <div class="panel reveal" style="--i:0">
      <div class="ph"><div><div class="eyebrow">Market position</div><h2>Your price index against the market</h2>
        <p>100 means priced exactly at the competitor average, weighted by what you sell. Under 100 is cheaper.</p></div>
        <div class="legend"><span><i style="background:var(--ours)"></i>Lumen &amp; Lane</span><span><i style="background:var(--faint)"></i>Parity</span></div></div>
      <div class="hero-n"><span class="big" data-count="${k.price_index}" data-dec="2">0</span>
        <div><span class="delta ${d7 > 0 ? "up" : "down"}">${d7 > 0 ? "▲" : "▼"} ${Math.abs(d7).toFixed(2)} pts vs 7 days ago</span>
        <div class="legend" style="margin-top:8px">${stores.map((x) => `<span>${chip(x.s)}<b class="num">${x.now?.toFixed(1)}</b></span>`).join("")}</div>
        <small style="color:var(--muted);font-size:.72rem">Store numbers: their price level against yours (100 = same as you)</small></div></div>
      <div id="idx-chart" style="margin-top:6px"></div>
      <div class="tbl-wrap" data-table-for="idx"></div>
    </div>
    <div class="kpis">
      ${kpi(1, "Products tracked", k.products_tracked, `of ${k.catalog} · ${(100 * k.products_tracked / k.catalog).toFixed(1)}% matched`, "products", "", ring(k.products_tracked / k.catalog, { size: 46, stroke: 5, label: false }))}
      ${kpi(2, "New undercuts · 24 h", k.new_undercuts, `${k.undercuts} active in total`, "products", "warn")}
      ${kpi(3, "MAP violations", k.map_violations, `across ${k.map_stores} stores today`, "pulse/map", "bad")}
      ${kpi(4, "Margin headroom", k.opportunity_monthly, `per month · ${k.opportunities} products`, "repricing", "good", "", "$", 0)}
      ${kpi(5, "Pricing errors caught", k.pricing_errors, "in 30 days · both 90% drops", "pulse/error", "bad")}
      ${kpi(6, "Live promotions", k.promos_live, "flash and weekend sales today", "pulse/promo", "")}
    </div>
  </section>
  <section class="row r-21">
    <div class="panel reveal" style="--i:3">
      <div class="ph"><div><div class="eyebrow">Price compass</div><h2>Where each rival sits around you</h2>
        <p>The dashed ring is your price. Inside it, a store is cheaper than you in that category. Outside, pricier.</p></div>
        <div class="legend">${STORES.map((s) => `<span><i style="background:${SC[s]}"></i>${short(s)}</span>`).join("")}</div></div>
      <div style="display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr);gap:16px;align-items:center">
        <div id="compass" class="ring-wrap"></div>
        <div id="compass-list"></div></div>
    </div>
    <div class="panel reveal" style="--i:4">
      <div class="ph"><div><div class="eyebrow">Signals</div><h2>What changed, ranked</h2><p>Every item traces back to a crawled price.</p></div></div>
      <div class="tabs" role="tablist" aria-label="Filter signals">${FEED_TABS.map(([v, l], i) => `<button role="tab" aria-selected="${i === 0}" data-ft="${v}">${l}</button>`).join("")}</div>
      <ul class="feed" id="feed" style="margin-top:12px" aria-label="Signals"></ul>
    </div>
  </section>
  <section class="row r-21">
    <div class="panel reveal" style="--i:5">
      <div class="ph"><div><div class="eyebrow">Gap map</div><h2>Your 22 biggest sellers against every rival</h2><p>Cell = their price minus yours. Arrow keys move, Enter opens the product.</p></div>
        <div class="heat-scale" style="min-width:210px"><span>They undercut</span><span class="bar"></span><span>You're cheaper</span></div></div>
      <div id="heat" class="heat" role="grid" aria-label="Price gap by product and store"></div>
    </div>
    <div class="panel reveal" style="--i:6">
      <div class="ph"><div><div class="eyebrow">Competitor playbook</div><h2>How each rival prices</h2><p>Learned from 30 days of their prices, not set by hand.</p></div></div>
      <div id="playbook" style="display:grid;gap:10px"></div>
    </div>
  </section>
  <section class="row r-2">
    <div class="panel reveal" style="--i:7">
      <div class="ph"><div><div class="eyebrow">Crawler · live</div><h2>Today's crawl, replayed</h2><p>Every line is a real request from the run log.</p></div><span class="chip"><span class="dot live"></span> ${k.requests_30d.toLocaleString()} requests in 30 days</span></div>
      <div class="term" id="term" aria-label="Crawl log" role="log"></div>
    </div>
    <div class="panel reveal" style="--i:8">
      <div class="ph"><div><div class="eyebrow">Matching engine</div><h2>Matched before anything is compared</h2><p>Scored against ground truth on all ${ov.match.listings} listings.</p></div>
        <a class="btn" href="#/matching">Review ${ov.match.review_queue} <span aria-hidden="true">→</span></a></div>
      <div class="versus">
        <div class="vs-card" style="border-color:color-mix(in srgb,var(--mint) 45%,var(--line))"><small style="color:var(--muted)">Northvane</small><br>
          <b class="num" style="color:var(--mint)" data-count="${(ov.match.auto.precision * 100).toFixed(1)}" data-dec="1" data-suf="%">0</b><small style="color:var(--muted)"> precision</small><br>
          <b class="num" data-count="${(ov.match.auto.recall * 100).toFixed(1)}" data-dec="1" data-suf="%">0</b><small style="color:var(--muted)"> recall</small></div>
        <div class="vs-card"><small style="color:var(--muted)">Fuzzy title matching (typical scraper)</small><br>
          <b class="num" style="color:var(--coral)">${(ov.match.baseline_fuzzy.precision * 100).toFixed(1)}%</b><small style="color:var(--muted)"> precision</small><br>
          <b class="num">${(ov.match.baseline_fuzzy.recall * 100).toFixed(1)}%</b><small style="color:var(--muted)"> recall · ${ov.match.baseline_fuzzy.fp} wrong matches</small></div>
      </div>
      <div id="methods" style="margin-top:16px"></div>
    </div>
  </section>`;

  // index chart
  const ic = $("#idx-chart");
  const drawIdx = () => lineChart(ic, {
    labels: L, tipLabels: TL, title: "Price index over 30 days", height: 230, fmt: (v) => v.toFixed(1), yMin: 96.5, yMax: 100.6,
    summary: `Price index ${ov.index_series[0]} on ${TL[0]}, ${k.price_index} today.`,
    series: [{ name: "Price index", color: "var(--ours)", values: ov.index_series, width: 2.6, glow: true, area: true }],
    ref: { y: 100, label: "Parity", color: "var(--faint)" },
    bands: [{ from: ov.response.cut_day, to: ov.response.cut_day + 1, label: `You cut ${ov.response.n_cut} prices`, color: "var(--mint)" }],
  });
  drawIdx();
  tableToggle($('[data-table-for="idx"]'), ["Day", "Price index"], L.map((l, i) => [TL[i], ov.index_series[i]]));
  for (const b of $$(".kpi", view)) b.addEventListener("click", () => {
    const [v, f] = b.dataset.go.split("/");
    if (v === "pulse") { const t = $(`[data-ft="${f}"]`); t && t.click(); $("#feed").scrollIntoView({ behavior: "smooth", block: "center" }); }
    else location.hash = "#/" + v;
  });

  // compass
  const cats = ov.compass.map((c) => c.category);
  compass($("#compass"), { axes: cats, range: [90, 112], series: STORES.map((s, i) => ({ name: s, color: SC[s], main: true, values: ov.compass.map((c) => c.stores[s]) })) });
  $("#compass-list").innerHTML = `<ul style="list-style:none;margin:0;padding:0;display:grid;gap:8px">${ov.compass.map((c) => {
    const lows = STORES.filter((s) => c.stores[s] < 99);
    return `<li style="display:flex;justify-content:space-between;gap:10px;padding:8px 10px;border-radius:11px;border:1px solid var(--line);background:var(--panel-2);font-size:.8rem">
      <span><b style="display:block">${esc(c.category)}</b><small style="color:var(--muted)">index ${c.ours.toFixed(1)} · ${lows.length ? "undercut by " + lows.map(short).join(", ") : "nobody under you"}</small></span>
      <span class="num" style="color:${c.ours > 100 ? "var(--coral)" : "var(--mint)"}">${pct(c.ours - 100, 1)}</span></li>`;
  }).join("")}</ul>`;

  // feed
  const feed = $("#feed");
  const drawFeed = (f) => {
    const items = ov.feed.map((e) => ({ e, v: SIG[e.type](e) })).filter((x) => f === "all" || x.v.k === f);
    feed.innerHTML = items.map(({ e, v }, i) => `<li class="sig reveal ${e.severity === 3 ? "sev3" : ""}" style="--i:${i}" tabindex="0" data-sku="${e.sku}" role="button" aria-label="${esc(v.h + ". " + v.s)}">
      <span class="ic t-${v.t}" aria-hidden="true">${ICON[v.k]}</span>
      <span style="min-width:0"><b>${esc(v.h)}</b><small>${esc(v.s)}</small></span>
      <span aria-hidden="true">${e.their_series ? sparkline(e.ours_series, { w: 86, h: 30, values2: e.their_series, color2: SC[e.store] || "var(--coral)", fill: false }) : sparkline(e.ours_series, { w: 86, h: 30 })}</span></li>`).join("") ||
      `<li class="empty">Nothing in this category today.</li>`;
  };
  drawFeed("all");
  $$(".tabs [data-ft]", view).forEach((t) => t.addEventListener("click", () => {
    $$(".tabs [data-ft]", view).forEach((x) => x.setAttribute("aria-selected", x === t)); drawFeed(t.dataset.ft);
    announce(`${t.textContent} signals: ${$$("#feed .sig").length}`);
  }));
  feed.addEventListener("click", (e) => { const li = e.target.closest(".sig"); if (li?.dataset.sku) openProduct(li.dataset.sku); });
  feed.addEventListener("keydown", (e) => { const li = e.target.closest(".sig"); if (li && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openProduct(li.dataset.sku); } });

  // heatmap
  const hm = await api("/api/heatmap?n=22");
  const heat = $("#heat");
  heat.innerHTML = `<div class="hh" role="columnheader" style="text-align:left">Product</div>${STORES.map((s) => `<div class="hh" role="columnheader">${chip(s)}</div>`).join("")}` +
    hm.map((r, i) => `<div class="hn" role="rowheader" title="${esc(r.title)}">${esc(r.title)}</div>` + STORES.map((s, j) => {
      const g = r.gaps[s];
      const lab = g == null ? "not sold" : g === "oos" ? "out of stock" : pct(g);
      return `<div class="hc" role="gridcell" tabindex="${i === 0 && j === 0 ? 0 : -1}" data-r="${i}" data-c="${j}" data-sku="${r.sku}"
        style="background:${heatColor(g)};animation-delay:${(i * 3 + j) * 12}ms" aria-label="${esc(r.title)}, ${s}: ${lab}">${g == null ? '<span style="color:var(--faint)">·</span>' : g === "oos" ? '<span style="color:var(--muted);font-size:.68rem">OOS</span>' : pct(g)}</div>`;
    }).join("")).join("");
  heat.addEventListener("click", (e) => { const c = e.target.closest(".hc"); if (c) openProduct(c.dataset.sku); });
  heat.addEventListener("keydown", (e) => {
    const c = e.target.closest(".hc"); if (!c) return;
    let r = +c.dataset.r, col = +c.dataset.c;
    const mv = { ArrowRight: [0, 1], ArrowLeft: [0, -1], ArrowDown: [1, 0], ArrowUp: [-1, 0] }[e.key];
    if (e.key === "Enter") { openProduct(c.dataset.sku); return; }
    if (!mv) return;
    e.preventDefault();
    r = Math.max(0, Math.min(hm.length - 1, r + mv[0])); col = Math.max(0, Math.min(2, col + mv[1]));
    const n = $(`.hc[data-r="${r}"][data-c="${col}"]`, heat);
    c.tabIndex = -1; n.tabIndex = 0; n.focus();
  });
  heat.addEventListener("mouseover", (e) => {
    const c = e.target.closest(".hc"); if (!c) return;
    const r = hm[+c.dataset.r], s = STORES[+c.dataset.c], g = r.gaps[s];
    showTip(`<b>${esc(r.title)}</b><div class="tr"><span>${chip(s)}</span>${g == null ? "not sold" : g === "oos" ? "out of stock" : pct(g)}</div>`, e.clientX, e.clientY);
  });
  heat.addEventListener("mouseleave", hideTip);

  // playbook
  const cr = (state.crawls ||= await api("/api/crawls"));
  const mondayShare = (s) => {
    const rows = cr.runs.filter((r) => r.store === s && r.day > 0), tot = rows.reduce((a, r) => a + r.changed_items, 0);
    const mon = rows.filter((r) => new Date(state.meta.days[r.day] + "T12:00:00").getDay() === 1).reduce((a, r) => a + r.changed_items, 0);
    return tot ? Math.round((100 * mon) / tot) : 0;
  };
  const promosBy = (s) => ov.feed.filter((e) => e.type === "promo" && e.store === s).length;
  $("#playbook").innerHTML = STORES.map((s, i) => {
    const idx = ov.store_index_series[s].at(-1), r = ov.response.by_store[s];
    const kind = idx < 98.5 ? ["Undercutter", "var(--coral)"] : idx > 103 ? ["Premium", "var(--violet)"] : ["Steady", "var(--sky)"];
    const lines = [];
    lines.push(`Prices <b class="num">${pct(idx - 100)}</b> against you on shared products`);
    if (r.followed / Math.max(1, r.cut_products) > 0.5) lines.push(`Followed <b>${r.followed} of ${r.cut_products}</b> of your price cuts, median <b>${r.median_lag_days} day</b> later`);
    else lines.push(`Ignored your price cuts: followed <b>${r.followed} of ${r.cut_products}</b>`);
    const ms = mondayShare(s);
    if (ms > 60) lines.push(`<b>${ms}%</b> of its price changes land on Mondays`);
    const pr = promosBy(s);
    if (pr) lines.push(`${pr} promotion${pr > 1 ? "s" : ""} running today`);
    return `<div class="sh reveal" style="--i:${i}"><h4>${chip(s)} <span class="pos" style="color:${kind[1]};background:color-mix(in srgb,${kind[1]} 14%,transparent)">${kind[0]}</span>
      <span style="margin-left:auto">${sparkline(ov.store_index_series[s], { w: 90, h: 26, color: SC[s] })}</span></h4>
      <ul style="margin:8px 0 0;padding-left:18px;color:var(--muted);font-size:.8rem;display:grid;gap:3px">${lines.map((l) => `<li>${l}</li>`).join("")}</ul>
      <div style="display:flex;gap:6px;align-items:center;margin-top:10px;font-size:.72rem;color:var(--muted)">Follows your cuts
        <span style="flex:1;height:6px;border-radius:6px;background:var(--panel-2);overflow:hidden"><i style="display:block;height:100%;width:${(100 * r.followed) / Math.max(1, r.cut_products)}%;background:${SC[s]};border-radius:6px"></i></span>
        <span class="num">${Math.round((100 * r.followed) / Math.max(1, r.cut_products))}%</span></div></div>`;
  }).join("");

  // methods bar
  const bm = ov.match.by_method || {}, tot = Object.values(bm).reduce((a, b) => a + b, 0);
  const MC = { gtin: "var(--mint)", mpn: "var(--sky)", model: "var(--violet)", human: "var(--amber)" };
  const ML = { gtin: "Barcode (GTIN)", mpn: "Part number", model: "AI title model", human: "You" };
  $("#methods").innerHTML = `<div style="display:flex;height:12px;border-radius:8px;overflow:hidden;gap:2px">${Object.entries(bm).map(([m, v]) =>
    `<i style="flex:${v};background:${MC[m]}" title="${ML[m]}: ${v}"></i>`).join("")}</div>
    <div class="legend" style="margin-top:10px">${Object.entries(bm).map(([m, v]) => `<span><i style="background:${MC[m]}"></i>${ML[m]} <b class="num">${v}</b></span>`).join("")}</div>
    <p class="chart-desc">${bm.model || 0} of ${tot} matches had no barcode or part number in common, so they were resolved from the titles.</p>`;

  startTerm($("#term"), cr.log);
  onResize(view, drawIdx);
}
function kpi(i, label, value, sub, go, cls = "", viz = "", pre = "", dec = 0) {
  const v = typeof value === "number" && pre === "$" && value >= 1000 ? { n: (value / 1000).toFixed(1), suf: "k", dec: 1 } : { n: value, suf: "", dec };
  return `<button class="kpi reveal ${cls}" style="--i:${i}" data-go="${go}" type="button">
    <span class="k-l">${esc(label)}</span><span class="k-v num" data-count="${v.n}" data-dec="${v.dec}" data-pre="${pre}" data-suf="${v.suf}">0</span>
    <span class="k-s">${esc(sub)}</span>${viz ? `<span class="k-viz">${viz}</span>` : ""}</button>`;
}
let termTimer = null;
function startTerm(el, log) {
  clearInterval(termTimer);
  if (!el || !log?.length) return;
  const cls = { Brightcart: "who", Voltaro: "vo", "Hearth & Hollow": "hhc" };
  let i = 0;
  const line = (r) => `<div><span class="ms">${(r.t_ms / 1000).toFixed(3)}s</span> <span class="${cls[r.store]}">${short(r.store).padEnd(10, " ").replace(/ /g, "&nbsp;")}</span> <span class="st s${String(r.status)[0]}">${r.status}</span>${esc(r.url)} <span class="ms">${r.ms.toFixed(0)} ms · ${r.bytes ? (r.bytes / 1024).toFixed(1) + " kB" : "no body"}${r.note ? " · " + esc(r.note) : ""}</span></div>`;
  el.innerHTML = log.slice(0, 12).map(line).join("");
  i = 12;
  const reduce = document.documentElement.classList.contains("reduce-motion");
  if (reduce) return;
  termTimer = setInterval(() => {
    if (!document.body.contains(el)) { clearInterval(termTimer); return; }
    el.insertAdjacentHTML("beforeend", line(log[i % log.length]));
    if (el.children.length > 16) el.firstElementChild.remove();
    i++;
  }, 260);
}

/* ---------------------------------------------------------------- PRODUCTS */
const pstate = { q: "", cat: "", pos: "all", sort: "units", dir: -1 };
async function renderProducts(view) {
  const rows = (state.products ||= await api("/api/products"));
  view.innerHTML = `<div class="panel reveal">
    <div class="toolbar">
      <label class="field"><svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>
        <span class="sr-only">Search products</span><input id="pq" type="search" placeholder="Search by name or SKU  ( / )" value="${esc(pstate.q)}"></label>
      <label><span class="sr-only">Category</span><select class="sel" id="pcat"><option value="">All categories</option>${state.meta.categories.map((c) => `<option ${c === pstate.cat ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label>
      <div class="seg" role="group" aria-label="Position">${[["all", "All"], ["cheapest", "Cheapest"], ["matched", "Matched"], ["above", "Above"]].map(([v, l]) => `<button type="button" data-pos="${v}" aria-pressed="${pstate.pos === v}">${l}</button>`).join("")}</div>
      <span class="chip" id="pcount" aria-live="polite"></span>
    </div>
    <div class="scroll-y"><table class="tbl" aria-describedby="pcount"><thead><tr>
      ${th("title", "Product")}${th("ours", "Your price", "r")}${th("lowest", "Lowest rival", "r")}${th("gap_pct", "Gap", "")}
      ${STORES.map((s) => `<th class="r" scope="col">${chip(s)}</th>`).join("")}<th scope="col">30 days</th>${th("position", "Position")}
    </tr></thead><tbody id="pbody"></tbody></table></div></div>`;
  const draw = () => {
    let r = rows.filter((x) => (!pstate.cat || x.category === pstate.cat) && (pstate.pos === "all" || x.position === pstate.pos) &&
      (!pstate.q || (x.title + " " + x.sku).toLowerCase().includes(pstate.q.toLowerCase())));
    const key = pstate.sort, dir = pstate.dir;
    r = r.slice().sort((a, b) => ((a[key] ?? -1e9) > (b[key] ?? -1e9) ? 1 : -1) * dir);
    $("#pcount").textContent = `${r.length} products`;
    $("#pbody").innerHTML = r.map((x) => {
      const g = x.gap_pct, w = Math.min(50, Math.abs(g ?? 0) * 5);
      return `<tr tabindex="0" data-sku="${x.sku}" aria-label="${esc(x.title)}, your price ${money(x.ours)}, ${x.position}">
        <td class="pt"><b>${esc(x.title)}</b><small>${x.sku} · ${esc(x.category)}</small></td>
        <td class="r num"><b>${money(x.ours)}</b></td>
        <td class="r num">${money(x.lowest)}<br><small style="color:var(--muted)">${x.lowest_store ? short(x.lowest_store) : ""}</small></td>
        <td><div style="display:flex;align-items:center;gap:8px"><span class="gapbar"><i style="${g > 0 ? `left:50%;width:${w}%;background:var(--bad)` : `right:50%;width:${w}%;background:var(--good)`}"></i></span>
            <span class="num" style="font-size:.78rem;color:${g > 0 ? "var(--coral)" : "var(--mint)"}">${pct(g)}</span></div></td>
        ${STORES.map((s) => { const c = x.comps[s]; return `<td class="r num">${c ? `<span class="${c.in_stock ? "" : "oos"}">${money(c.price)}</span>${c.in_stock ? "" : '<br><small style="color:var(--sky)">sold out</small>'}` : '<span style="color:var(--faint)">—</span>'}</td>`; }).join("")}
        <td aria-hidden="true">${sparkline(x.spark, { w: 104, h: 30, values2: x.low_spark })}</td>
        <td><span class="pos ${x.position}">${x.position}</span></td></tr>`;
    }).join("");
    $$(".tbl th[data-sort]").forEach((t) => t.setAttribute("aria-sort", t.dataset.sort === pstate.sort ? (pstate.dir > 0 ? "ascending" : "descending") : "none"));
  };
  draw();
  $("#pq").addEventListener("input", (e) => { pstate.q = e.target.value; draw(); });
  $("#pcat").addEventListener("change", (e) => { pstate.cat = e.target.value; draw(); });
  $$("[data-pos]", view).forEach((b) => b.addEventListener("click", () => { pstate.pos = b.dataset.pos; $$("[data-pos]", view).forEach((x) => x.setAttribute("aria-pressed", x === b)); draw(); }));
  $$(".tbl th[data-sort] button", view).forEach((b) => b.addEventListener("click", () => {
    const k = b.parentElement.dataset.sort; pstate.dir = pstate.sort === k ? -pstate.dir : -1; pstate.sort = k; draw();
  }));
  $("#pbody").addEventListener("click", (e) => { const tr = e.target.closest("tr"); if (tr) openProduct(tr.dataset.sku); });
  $("#pbody").addEventListener("keydown", (e) => {
    const tr = e.target.closest("tr"); if (!tr) return;
    if (e.key === "Enter") openProduct(tr.dataset.sku);
    if (e.key === "ArrowDown") { e.preventDefault(); tr.nextElementSibling?.focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); tr.previousElementSibling?.focus(); }
  });
}
const th = (k, l, cls = "") => `<th scope="col" class="${cls}" data-sort="${k}" aria-sort="none"><button type="button">${l} <span aria-hidden="true">↕</span></button></th>`;

/* ---------------------------------------------------------------- PRODUCT DRAWER */
async function openProduct(sku) {
  const d = await api("/api/product/" + sku);
  const p = d.product, pos = d.position;
  const body = $("#drawer-body");
  const comps = STORES.map((s) => ({ s, c: d.comps[s] }));
  const series = [{ name: "Lumen & Lane", color: "var(--ours)", values: d.ours, width: 2.8, glow: true, area: true }]
    .concat(comps.filter((x) => x.c).map(({ s, c }) => ({ name: s, color: SC[s], values: c.series.map((o) => (o ? o[0] : null)), width: 1.7 })));
  const bands = d.events.filter((e) => e.type === "promo").map((e) => ({ from: e.start, to: e.end, label: `${short(e.store)} −${e.depth_pct}%`, color: SC[e.store] }));
  const hatches = [];
  comps.forEach(({ s, c }) => {
    if (!c) return;
    let st = null;
    c.series.forEach((o, i) => {
      if (o && !o[2] && st == null) st = i;
      if ((o?.[2] || i === c.series.length - 1) && st != null) { hatches.push({ from: st, to: o?.[2] ? i - 1 : i, label: `${short(s)} sold out` }); st = null; }
    });
  });
  const markers = d.events.filter((e) => e.type === "pricing_error").map((e) => ({ x: e.day, y: e.price, label: `${short(e.store)} error ${money(e.price)}`, color: "var(--coral)" }));
  const sug = d.suggestion;
  body.innerHTML = `
    <div class="d-head"><div><div class="eyebrow">${esc(p.category)} · ${p.sku}</div><h2 id="drawer-title">${esc(p.title)}</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:6px"><span class="chip">${esc(p.brand)}</span>${pos ? `<span class="pos ${pos.position}">${pos.position}${pos.position === "above" ? " lowest by " + pct(pos.gap_pct) : ""}</span>` : ""}
      ${p.map_price ? `<span class="chip">MAP ${money(p.map_price)}</span>` : '<span class="chip">no MAP policy</span>'}<span class="chip num">cost ${money(p.cost)}</span></div></div>
      <button class="close" data-close aria-label="Close product details">✕</button></div>
    <div class="pcards">
      <div class="pcard ours"><small><i class="pip" style="background:var(--ours)"></i>You</small><b class="num">${money(d.ours.at(-1))}</b><em style="color:var(--muted)">${((1 - p.cost / d.ours.at(-1)) * 100).toFixed(1)}% margin</em></div>
      ${comps.map(({ s, c }) => { if (!c) return `<div class="pcard"><small>${chip(s)}</small><b style="color:var(--faint)">—</b><em style="color:var(--muted)">not sold there</em></div>`;
        const o = c.series.at(-1), dd = ((o[0] - d.ours.at(-1)) / d.ours.at(-1)) * 100;
        return `<div class="pcard"><small>${chip(s)}</small><b class="num ${o[2] ? "" : "oos"}">${money(o[0])}</b><em style="color:${dd < 0 ? "var(--coral)" : "var(--mint)"}">${o[2] ? pct(dd) + " vs you" : "sold out"}${o[1] ? ` · was ${money(o[1])}` : ""}</em></div>`; }).join("")}
    </div>
    <div class="panel" style="padding:14px 16px">
      <div class="ph"><div><h3>30 days of prices</h3><p>${bands.length ? "Shaded: promotions. " : ""}${hatches.length ? "Hatched: a rival was sold out. " : ""}${p.map_price ? "Dashed: the brand's minimum advertised price." : ""}</p></div>
        <div class="legend">${series.map((x) => `<span><i style="background:${x.color}"></i>${esc(short(x.name))}</span>`).join("")}</div></div>
      <div id="pchart"></div><div data-table-for="p"></div></div>
    <h3 style="font:700 1.02rem var(--display);margin:22px 0 10px">Why we think these are the same product</h3>
    <div class="evid">${comps.filter((x) => x.c).map(({ s, c }) => {
      const ev = c.match.evidence, m = c.match.method;
      const why = m === "gtin" ? `Barcode ${esc(c.gtin)} matches exactly` : m === "mpn" ? `Part number ${esc(c.mpn)} matches exactly` :
        m === "human" ? "Confirmed by a person in review" : `Model ${ev.model === "ok" ? "named" : ev.model} · colour ${ev.colour === "ok" ? ev.colour_theirs : ev.colour} · text similarity ${(ev.tfidf * 100).toFixed(0)}% · token overlap ${(ev.fuzzy * 100).toFixed(0)}%`;
      return `<div class="ev-row">${ring(c.match.score, { size: 50, stroke: 5, color: SC[s] })}<div class="t">${chip(s)} <span class="method ${m}">${m === "model" ? "AI title model" : m}</span>
        <div style="margin-top:6px">“${esc(c.title)}”</div><small>${why}</small></div><span class="num" style="color:var(--muted);font-size:.74rem">${c.listing_id}</span></div>`; }).join("")}</div>
    <h3 style="font:700 1.02rem var(--display);margin:22px 0 10px">Suggested price</h3>
    ${sug ? `<div class="sugg"><div><small style="color:var(--muted)">Now</small><div class="num" style="font:700 1.4rem var(--mono)">${money(sug.current)}</div></div><span class="arrow" aria-hidden="true">→</span>
      <div><small style="color:var(--muted)">Suggested</small><div class="num" style="font:700 1.4rem var(--mono);color:var(--mint)">${money(sug.suggested)}</div></div>
      <div style="flex:1;font-size:.84rem;color:var(--muted)">Beat the lowest in-stock rival (${short(sug.lowest_store)}, ${money(sug.lowest)}) by 1%, keep at least 15% margin, never below MAP, move at most 8% a day.
        ${sug.guards.length ? `<div style="margin-top:6px">Held back by ${sug.guards.map((g) => `<span class="guard">${g}</span>`).join("")}</div>` : ""}</div>
      <a class="btn primary" href="#/repricing" data-close>Open studio</a></div>` : `<div class="sugg"><span style="color:var(--muted)">Your price already fits the default strategy. No change suggested.</span></div>`}
    <p class="demo-note" style="margin-top:18px">Demo data. Stores, brands and prices are fictional; the crawl, matching and analysis are real code.</p>`;
  openDialog("drawer");
  const draw = () => lineChart($("#pchart"), {
    labels: L, tipLabels: TL, title: `Prices for ${p.title}`, height: 250, fmt: (v) => "$" + v.toFixed(0), series, bands, hatches, markers, step: true,
    ref: p.map_price ? { y: p.map_price, label: `MAP ${money(p.map_price)}`, color: "var(--amber)" } : null,
    yMin: markers.length ? null : Math.min(...d.ours) * 0.9,
    summary: `Your price ${money(d.ours[0])} on ${TL[0]}, ${money(d.ours.at(-1))} today.`,
  });
  requestAnimationFrame(draw);
  tableToggle($('[data-table-for="p"]', body), ["Day", ...series.map((x) => x.name)], L.map((l, i) => [TL[i], ...series.map((x) => (x.values[i] == null ? "—" : money(x.values[i])))]));
  announce(`Opened ${p.title}`);
}

/* ---------------------------------------------------------------- MATCHING */
async function renderMatching(view) {
  const rv = await api("/api/review");
  const q = rv.quality, items = rv.items;
  let at = 0;
  const done = [];
  view.innerHTML = `
  <section class="tiles">
    <div class="tile reveal" style="--i:0"><small>Auto-matched</small><b class="num" data-count="${rv.counts.matched}">0</b><small>${q.by_method.gtin} by barcode · ${q.by_method.mpn} by part number · ${q.by_method.model} from titles</small></div>
    <div class="tile reveal" style="--i:1"><small>Precision on ground truth</small><b class="num" style="color:var(--mint)" data-count="${(q.auto.precision * 100).toFixed(1)}" data-dec="1" data-suf="%">0</b><small>${q.auto.fp} wrong auto-matches out of ${q.auto.tp + q.auto.fp}</small></div>
    <div class="tile reveal" style="--i:2"><small>Recall</small><b class="num" data-count="${(q.auto.recall * 100).toFixed(1)}" data-dec="1" data-suf="%">0</b><small>${(q.auto_plus_review.recall * 100).toFixed(1)}% once the review queue is cleared</small></div>
    <div class="tile reveal" style="--i:3"><small>Not your products</small><b class="num" data-count="${rv.counts.unmatched}">0</b><small>listings for brands you don't sell, left alone</small></div>
  </section>
  <section class="panel reveal" style="--i:4">
    <div class="ph"><div><div class="eyebrow">Review queue</div><h2 id="rq-h">Listings the model wasn't sure about</h2>
      <p>The engine only asks when evidence conflicts or is missing. Accept with <kbd>A</kbd>, reject with <kbd>R</kbd>, skip with <kbd>S</kbd>.</p></div>
      <div style="min-width:220px"><div class="qbar" id="qbar" aria-hidden="true">${items.map(() => "<i></i>").join("")}</div><small id="qtxt" style="color:var(--muted);font-size:.74rem" aria-live="polite"></small></div></div>
    <div id="stage"></div>
  </section>
  <section class="row r-2">
    <div class="panel reveal" style="--i:5"><div class="ph"><div><div class="eyebrow">Why it beats fuzzy matching</div><h2>Same listings, two approaches</h2><p>F1 on all ${q.listings} crawled listings against the ground truth.</p></div></div>
      <div style="display:grid;gap:14px">
        ${[["Northvane", q.auto.f1, "var(--mint)", `${q.auto.fp} wrong · ${q.auto.fn} missed`], ["Fuzzy title match", q.baseline_fuzzy.f1, "var(--coral)", `${q.baseline_fuzzy.fp} wrong · ${q.baseline_fuzzy.fn} missed`]].map(([n, v, c, s]) => `
        <div><div style="display:flex;justify-content:space-between;font-size:.84rem;margin-bottom:6px"><b>${n}</b><span class="num">F1 ${v.toFixed(3)} <small style="color:var(--muted)">· ${s}</small></span></div>
          <div style="height:12px;border-radius:8px;background:var(--panel-2);overflow:hidden"><i style="display:block;height:100%;width:${v * 100}%;background:${c};border-radius:8px;transform-origin:left;animation:grow 1.2s cubic-bezier(.2,.8,.2,1)"></i></div></div>`).join("")}
      </div>
      <p class="chart-desc">Fuzzy matching confuses siblings: the Halo 700 with the Halo 500, the Black with the Silver, a brand you don't sell with one you do. Northvane checks model, colour, size and capacity before it trusts the text.</p></div>
    <div class="panel reveal" style="--i:6"><div class="ph"><div><div class="eyebrow">How a match is decided</div><h2>Cheapest evidence first</h2></div></div>
      <ol style="margin:0;padding-left:20px;display:grid;gap:10px;font-size:.86rem;color:var(--muted)">
        <li><b style="color:var(--text)">Barcode.</b> Same GTIN, same product. ${q.by_method.gtin} listings.</li>
        <li><b style="color:var(--text)">Manufacturer part number.</b> ${q.by_method.mpn} listings.</li>
        <li><b style="color:var(--text)">Title model.</b> Character n-gram similarity plus token overlap, inside the same brand only.</li>
        <li><b style="color:var(--text)">Attribute guard.</b> Model, colour family, screen size and capacity must agree, or the score collapses.</li>
        <li><b style="color:var(--text)">One-to-one.</b> The Hungarian algorithm stops two listings claiming the same product.</li>
        <li><b style="color:var(--text)">You.</b> Anything between 55 and 80 comes here.</li></ol></div>
  </section>`;
  const stage = $("#stage");
  const toks = (s) => s.toLowerCase().replace(/[–—(),]/g, " ").split(/\s+/).filter(Boolean);
  const hl = (title, other) => {
    const o = new Set(toks(other));
    return title.split(/(\s+)/).map((w) => { const k = w.toLowerCase().replace(/[–—(),]/g, ""); if (!k.trim()) return w; return `<span class="tok ${o.has(k) ? "same" : ""}">${esc(w)}</span>`; }).join("");
  };
  const reason = (ev, it) => {
    if (ev.colour === "missing") return `Their title doesn't say which colour it is. Yours is <b>${esc(it.candidate.variant)}</b>, and this brand sells the same model in other colours. A person should confirm the variant.`;
    if (ev.model === "unknown") return `Their title doesn't name the model, so size, capacity and wording carry the match. Worth a quick look.`;
    if (ev.conflicts?.length) return `Conflicting ${ev.conflicts.join(", ")}: probably a different variant.`;
    const theirWord = (it.listing.title.split(/[–—-]\s*/).pop() || "").trim();
    if (ev.colour === "ok" && !it.listing.title.toLowerCase().includes(it.candidate.variant.toLowerCase()))
      return `Model and colour family agree, but they call the colour <b>${esc(theirWord)}</b> where you say <b>${esc(it.candidate.variant)}</b>. Same family (${esc(ev.colour_theirs)}), different words, so the text score is lower than usual.`;
    return "Every attribute agrees, but the wording is far enough apart that the engine wants a second opinion.";
  };
  const draw = () => {
    $$("#qbar i").forEach((b, i) => (b.className = done[i] === "accept" ? "done" : done[i] === "reject" ? "rej" : i === at ? "cur" : ""));
    const left = items.length - done.filter(Boolean).length;
    $("#qtxt").textContent = left ? `${left} of ${items.length} left` : "Queue clear";
    $("#nav-review").textContent = left;
    if (at >= items.length) {
      stage.innerHTML = `<div class="empty"><div class="big-ok">✓</div><b style="color:var(--text);font-size:1.1rem">Queue clear</b><span>${done.filter((x) => x === "accept").length} accepted, ${done.filter((x) => x === "reject").length} rejected. New prices for these listings start flowing tonight.</span></div>`;
      return;
    }
    const it = items[at], ev = it.evidence;
    stage.innerHTML = `<div class="match-stage">
      <article class="mcard" id="mc-l" aria-label="Competitor listing">${chip(it.store)} <span class="chip num">${it.listing_id}</span>
        <h4>${hl(it.listing.title, it.candidate.title)}</h4>
        <dl><dt>Brand</dt><dd>${esc(it.listing.brand || "—")}</dd><dt>Price</dt><dd>${money(it.listing.price)}</dd><dt>Barcode</dt><dd>${esc(it.listing.gtin || "not shown")}</dd><dt>Part no.</dt><dd>${esc(it.listing.mpn || "not shown")}</dd></dl></article>
      <div class="scorebox">${ring(it.score, { size: 96, stroke: 8, color: "var(--amber)" })}<small style="color:var(--muted);text-align:center">confidence<br>auto-match needs 80</small>
        <div class="bars">${[["Text", ev.tfidf], ["Tokens", ev.fuzzy], ["Model", ev.model === "ok" ? 1 : ev.model === "unknown" ? 0.5 : 0], ["Colour", ev.colour === "ok" ? 1 : ev.colour === "missing" ? 0.4 : ev.colour === "n/a" ? 1 : 0]]
          .map(([n, v]) => `<div>${n}<span class="tr"><i style="width:${v * 100}%"></i></span><span class="num">${Math.round(v * 100)}</span></div>`).join("")}</div></div>
      <article class="mcard" id="mc-r" aria-label="Your product"><span class="store-chip"><i style="background:var(--ours)"></i>Lumen &amp; Lane</span> <span class="chip num">${it.candidate.sku}</span>
        <h4>${hl(it.candidate.title, it.listing.title)}</h4>
        <dl><dt>Brand</dt><dd>${esc(it.candidate.brand)}</dd><dt>Price</dt><dd>${money(it.candidate.price)}</dd><dt>Barcode</dt><dd>${esc(it.candidate.gtin)}</dd><dt>Part no.</dt><dd>${esc(it.candidate.mpn)}</dd></dl></article></div>
      <p class="why">${reason(ev, it)}</p>
      <div class="actions"><button class="btn danger" data-d="reject" type="button">Not the same <kbd>R</kbd></button>
        <button class="btn" data-d="skip" type="button">Skip <kbd>S</kbd></button>
        <button class="btn primary" data-d="accept" type="button">Same product <kbd>A</kbd></button></div>`;
    $$("[data-d]", stage).forEach((b) => b.addEventListener("click", () => decide(b.dataset.d)));
  };
  const decide = async (dch) => {
    if (at >= items.length) return;
    const it = items[at];
    if (dch !== "skip") {
      $("#mc-l")?.classList.add(dch === "accept" ? "fly-right" : "fly-left");
      $("#mc-r")?.classList.add(dch === "accept" ? "fly-left" : "fly-right");
      const counts = await post(`/api/review/${encodeURIComponent(it.store)}/${it.listing_id}`, { decision: dch });
      done[at] = dch;
      state.ov = null; state.products = null;
      announce(`${dch === "accept" ? "Accepted" : "Rejected"}. ${counts.review} left.`);
      if (dch === "accept") toast("Match confirmed", `${it.listing.title} → ${it.candidate.sku}`);
      await new Promise((r) => setTimeout(r, 380));
    }
    at++;
    draw();
  };
  view._keys = (e) => { const k = e.key.toLowerCase(); if (k === "a") decide("accept"); if (k === "r") decide("reject"); if (k === "s") decide("skip"); };
  draw();
}

/* ---------------------------------------------------------------- REPRICING */
const rp = { strategy: "beat_lowest", beat: 1, index: 100, min_margin: 15, max_move: 8, respect_map: true, category: "" };
let lastReprice = null;
async function renderRepricing(view) {
  view.innerHTML = `<section class="row r-12">
    <div class="panel reveal ctrl" style="--i:0;align-self:start">
      <div class="ph"><div><div class="eyebrow">Strategy</div><h2>Tell it how to price</h2><p>Every change is recalculated live on today's crawl.</p></div></div>
      <div class="seg" role="group" aria-label="Strategy" style="width:100%">${[["beat_lowest", "Beat lowest"], ["match_lowest", "Match lowest"], ["index", "Index target"]].map(([v, l]) => `<button type="button" style="flex:1" data-st="${v}" aria-pressed="${rp.strategy === v}">${l}</button>`).join("")}</div>
      ${slider("beat", "Beat the lowest rival by", 0, 5, 0.5, "%")}${slider("index", "Index target (100 = market average)", 95, 105, 0.5, "")}
      ${slider("min_margin", "Minimum margin", 5, 40, 1, "%")}${slider("max_move", "Largest move per day", 2, 20, 1, "%")}
      <div class="switch"><span>Respect MAP<small>Never price under a brand's minimum advertised price</small></span><button type="button" role="switch" id="rmap" aria-checked="${rp.respect_map}" aria-label="Respect MAP"></button></div>
      <label><span class="lbl">Category</span><select class="sel" id="rcat" style="width:100%"><option value="">All categories</option>${state.meta.categories.map((c) => `<option ${c === rp.category ? "selected" : ""}>${esc(c)}</option>`).join("")}</select></label>
    </div>
    <div style="display:grid;gap:18px;min-width:0">
      <div class="tiles" id="rtiles"></div>
      <div class="panel reveal" style="--i:2"><div class="ph"><div><div class="eyebrow">Distribution</div><h2>How far prices would move</h2><p>Coral bars are cuts, mint bars are increases.</p></div>
        <div style="display:flex;gap:8px"><button class="btn" id="rexp" type="button">Export CSV</button><button class="btn primary" id="rsend" type="button">Send for approval</button></div></div><div id="rhist"></div></div>
      <div class="panel reveal" style="--i:3"><div class="scroll-y" style="max-height:440px"><table class="tbl"><thead><tr><th scope="col">Product</th><th class="r" scope="col">Now</th><th class="r" scope="col">Suggested</th><th class="r" scope="col">Change</th><th class="r" scope="col">Lowest rival</th><th class="r" scope="col">Margin</th><th scope="col">Guardrails</th></tr></thead><tbody id="rbody"></tbody></table></div></div>
    </div></section>`;
  let tmr = null;
  const run = async () => {
    const qs = new URLSearchParams({ strategy: rp.strategy, beat: rp.beat, index: rp.index, min_margin: rp.min_margin, max_move: rp.max_move, respect_map: rp.respect_map, ...(rp.category ? { category: rp.category } : {}) });
    const r = (lastReprice = await api("/api/reprice?" + qs));
    const dm = r.monthly_margin_delta;
    $("#rtiles").innerHTML = `
      <div class="tile"><small>Prices to change</small><b class="num">${r.changes}</b><small>${r.ups} up · ${r.downs} down</small></div>
      <div class="tile"><small>Held by a guardrail</small><b class="num" style="color:var(--amber)">${r.guard_hits}</b><small>margin, MAP or max move</small></div>
      <div class="tile"><small>Monthly margin change</small><b class="num" style="color:${dm >= 0 ? "var(--mint)" : "var(--coral)"}">${dm >= 0 ? "+" : "−"}${kmoney(Math.abs(dm))}</b><small>at current volume</small></div>
      <div class="tile"><small>Monthly margin after</small><b class="num">${kmoney(r.monthly_margin_new)}</b><small>from ${kmoney(r.monthly_margin_now)}</small></div>`;
    histogram($("#rhist"), r.hist);
    $("#rbody").innerHTML = r.rows.slice(0, 80).map((x) => `<tr tabindex="0" data-sku="${x.sku}"><td class="pt"><b>${esc(x.title)}</b><small>${x.sku}</small></td>
      <td class="r num">${money(x.current)}</td><td class="r num"><b style="color:var(--mint)">${money(x.suggested)}</b></td>
      <td class="r num" style="color:${x.delta < 0 ? "var(--coral)" : "var(--mint)"}">${pct(x.delta_pct)}</td>
      <td class="r num">${money(x.lowest)} <small style="color:var(--muted)">${short(x.lowest_store)}</small></td><td class="r num">${x.margin_pct}%</td>
      <td>${x.guards.map((g) => `<span class="guard">${g}</span>`).join("") || '<span style="color:var(--faint)">—</span>'}</td></tr>`).join("");
    announce(`${r.changes} price changes, margin ${dm >= 0 ? "up" : "down"} ${kmoney(Math.abs(dm))} a month`);
  };
  const later = () => { clearTimeout(tmr); tmr = setTimeout(run, 140); };
  $$("[data-st]", view).forEach((b) => b.addEventListener("click", () => { rp.strategy = b.dataset.st; $$("[data-st]", view).forEach((x) => x.setAttribute("aria-pressed", x === b)); syncSliders(); later(); }));
  $$("input[type=range]", view).forEach((s) => s.addEventListener("input", () => { rp[s.dataset.k] = +s.value; $(`output[for="${s.id}"]`).textContent = s.value + s.dataset.u; later(); }));
  $("#rmap").addEventListener("click", (e) => { rp.respect_map = !rp.respect_map; e.currentTarget.setAttribute("aria-checked", rp.respect_map); later(); });
  $("#rcat").addEventListener("change", (e) => { rp.category = e.target.value; later(); });
  $("#rexp").addEventListener("click", exportCSV);
  $("#rsend").addEventListener("click", () => toast("Sent for approval", `${lastReprice?.changes ?? 0} price changes are waiting for a manager. Nothing changes on the store until then.`));
  $("#rbody").addEventListener("click", (e) => { const tr = e.target.closest("tr"); if (tr) openProduct(tr.dataset.sku); });
  const syncSliders = () => { $("#w-beat").style.display = rp.strategy === "beat_lowest" ? "" : "none"; $("#w-index").style.display = rp.strategy === "index" ? "" : "none"; };
  syncSliders();
  await run();
}
const slider = (k, label, min, max, step, u) => `<div id="w-${k}"><label class="lbl" for="s-${k}">${label}<output for="s-${k}">${rp[k]}${u}</output></label>
  <input type="range" id="s-${k}" data-k="${k}" data-u="${u}" min="${min}" max="${max}" step="${step}" value="${rp[k]}"></div>`;
function exportCSV() {
  const r = lastReprice; if (!r) return;
  const lines = [["sku", "title", "current", "suggested", "change_pct", "lowest_rival", "lowest_store", "margin_pct", "guardrails"]]
    .concat(r.rows.map((x) => [x.sku, `"${x.title.replace(/"/g, '""')}"`, x.current, x.suggested, x.delta_pct, x.lowest, x.lowest_store, x.margin_pct, x.guards.join("|")]));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.map((l) => l.join(",")).join("\n")], { type: "text/csv" }));
  a.download = `northvane-repricing-${state.meta.today}.csv`;
  a.click();
  toast("CSV exported", `${r.rows.length} suggestions`);
}

/* ---------------------------------------------------------------- ALERTS */
const RULE_KEY = "northvane.rules";
const rule = { store: "any", condition: "undercut", threshold: 3, category: "", channel: "Email digest" };
const COND = { undercut: "undercuts me by more than", map: "breaks a brand's MAP", stockout: "runs out of stock", drop: "drops its own price by" };
function loadRules() {
  try { return JSON.parse(localStorage.getItem(RULE_KEY)) || []; } catch { return []; }
}
async function renderAlerts(view) {
  state.rules ||= loadRules();
  view.innerHTML = `<section class="panel reveal" style="--i:0">
      <div class="ph"><div><div class="eyebrow">New rule</div><h2>Write it like a sentence</h2><p>The preview replays the rule over the last 30 days, so you can see how noisy it would have been before you save it.</p></div></div>
      <div class="sentence">When
        <label><span class="sr-only">Store</span><select class="sel" id="a-store"><option value="any">any competitor</option>${STORES.map((s) => `<option value="${s}">${s}</option>`).join("")}</select></label>
        <label><span class="sr-only">Condition</span><select class="sel" id="a-cond">${Object.entries(COND).map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
        <span id="a-thw"><label><span class="sr-only">Threshold percent</span><input id="a-th" type="number" min="1" max="50" step="1" value="${rule.threshold}"></label>%</span>
        in <label><span class="sr-only">Category</span><select class="sel" id="a-cat"><option value="">any category</option>${state.meta.categories.map((c) => `<option>${esc(c)}</option>`).join("")}</select></label>,
        send <label><span class="sr-only">Channel</span><select class="sel" id="a-ch"><option>Email digest</option><option>Instant email</option><option>Webhook</option><option>In-app only</option></select></label></div>
    </section>
    <section class="row r-21">
      <div class="panel reveal" style="--i:1"><div class="ph"><div><div class="eyebrow">Backtest</div><h2 id="a-fires">—</h2><p id="a-sub"></p></div>
        <button class="btn primary" id="a-save" type="button">Save rule</button></div><div id="a-bars"></div><p class="chart-desc">Alerts per day over the last 30 days.</p></div>
      <div class="panel reveal" style="--i:2"><div class="ph"><div><div class="eyebrow">Latest it would have sent</div><h2>Examples</h2></div></div><ul class="feed" id="a-ex" style="max-height:300px"></ul></div>
    </section>
    <section class="panel reveal" style="--i:3"><div class="ph"><div><div class="eyebrow">Your rules</div><h2>Active</h2><p>Saved in this browser for the demo.</p></div></div><div class="rules" id="a-rules"></div></section>`;
  let tmr;
  const run = async () => {
    rule.store = $("#a-store").value; rule.condition = $("#a-cond").value; rule.threshold = +$("#a-th").value || 1; rule.category = $("#a-cat").value; rule.channel = $("#a-ch").value;
    $("#a-thw").style.display = ["undercut", "drop"].includes(rule.condition) ? "" : "none";
    const r = await post("/api/alerts/preview", { store: rule.store, condition: rule.condition, threshold: rule.threshold, category: rule.category || null });
    $("#a-fires").innerHTML = `Would have fired <span class="num" style="color:var(--mint)">${r.fires}</span> times`;
    $("#a-sub").textContent = `on ${r.days_with_alerts} of the last 30 days${r.fires > 60 ? ". That is a lot; a higher threshold or a daily digest keeps it useful." : "."}`;
    bars($("#a-bars"), r.by_day, { labels: L, fmtTip: (v, i) => `<b>${TL[i]}</b><div class="tr"><span>alerts</span>${v}</div>` });
    $("#a-ex").innerHTML = r.examples.map((e) => `<li class="sig" data-sku="${e.sku}" tabindex="0"><span class="ic t-${rule.condition === "map" ? "map" : rule.condition === "stockout" ? "stock" : "undercut"}">${ICON[rule.condition === "map" ? "map" : rule.condition === "stockout" ? "stock" : "undercut"]}</span>
      <span style="min-width:0"><b>${esc(short(e.store))} · ${new Date(e.date + "T12:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}</b><small>${esc(e.title)}${e.price ? " · " + money(e.price) : ""}</small></span><span></span></li>`).join("") || '<li class="empty">Nothing would have fired.</li>';
    announce(`Rule would have fired ${r.fires} times`);
    state.lastFires = r.fires;
  };
  const later = () => { clearTimeout(tmr); tmr = setTimeout(run, 160); };
  $$("#a-store,#a-cond,#a-cat,#a-ch,#a-th", view).forEach((x) => x.addEventListener("input", later));
  $("#a-ex").addEventListener("click", (e) => { const li = e.target.closest(".sig"); if (li?.dataset.sku) openProduct(li.dataset.sku); });
  const drawRules = () => {
    $("#a-rules").innerHTML = state.rules.map((r, i) => `<div class="rule"><div><b>When ${r.store === "any" ? "any competitor" : esc(r.store)} ${COND[r.condition]}${["undercut", "drop"].includes(r.condition) ? " " + r.threshold + "%" : ""}${r.category ? " in " + esc(r.category) : ""}</b>
      <small>${esc(r.channel)} · would have fired ${r.fires} times in 30 days</small></div>
      <div class="switch"><button type="button" role="switch" aria-checked="${r.on}" data-tg="${i}" aria-label="Rule enabled"></button></div>
      <button class="btn" data-rm="${i}" type="button" aria-label="Delete rule">Delete</button></div>`).join("") || '<p style="color:var(--muted);margin:0">No rules yet. Build one above and save it.</p>';
  };
  const persist = () => { try { localStorage.setItem(RULE_KEY, JSON.stringify(state.rules)); } catch { /* ignore */ } };
  $("#a-rules").addEventListener("click", (e) => {
    const t = e.target.closest("[data-tg]"), d = e.target.closest("[data-rm]");
    if (t) { const r = state.rules[+t.dataset.tg]; r.on = !r.on; t.setAttribute("aria-checked", r.on); persist(); announce(`Rule ${r.on ? "enabled" : "paused"}`); }
    if (d) { state.rules.splice(+d.dataset.rm, 1); persist(); drawRules(); announce("Rule deleted"); }
  });
  $("#a-save").addEventListener("click", () => {
    state.rules.unshift({ ...rule, fires: state.lastFires ?? 0, on: true }); persist(); drawRules();
    toast("Rule saved", `${COND[rule.condition]}${rule.category ? " · " + rule.category : ""} → ${rule.channel}`);
  });
  drawRules();
  await run();
}

/* ---------------------------------------------------------------- CRAWLER */
async function renderCrawler(view) {
  const cr = (state.crawls ||= await api("/api/crawls"));
  const c = cr.crawl, method = { Brightcart: "HTML category pages + JSON-LD product pages, conditional GET", Voltaro: "JavaScript storefront: discovered its JSON API, cursor pagination", "Hearth & Hollow": "Hand-written HTML: split prices, strike-through sales, microdata" };
  const per = STORES.map((s) => ({ s, ...c.by_store[s] }));
  view.innerHTML = `<section class="tiles">
    <div class="tile reveal" style="--i:0"><small>Requests · 30 days</small><b class="num" data-count="${c.requests}">0</b><small>${c.seconds} s of crawling in total</small></div>
    <div class="tile reveal" style="--i:1"><small>Answered 304 Not Modified</small><b class="num" style="color:var(--mint)" data-count="${(100 * c.not_modified / c.requests).toFixed(1)}" data-dec="1" data-suf="%">0</b><small>${c.not_modified.toLocaleString()} pages that sent no body</small></div>
    <div class="tile reveal" style="--i:2"><small>Retried, then succeeded</small><b class="num" style="color:var(--amber)" data-count="${c.retries}">0</b><small>${c.errors} failed · 429 and 503 handled with backoff</small></div>
    <div class="tile reveal" style="--i:3"><small>robots.txt respected</small><b class="num" data-count="${c.robots_blocked}">0</b><small>disallowed links seen and not followed</small></div></section>
  <section class="store-health">${per.map((x, i) => `<div class="sh reveal" style="--i:${i + 4}"><h4>${chip(x.s)}</h4><p>${method[x.s]}</p><dl>
    <dt>Listings</dt><dd>${x.listings}</dd><dt>Requests</dt><dd>${x.requests.toLocaleString()}</dd><dt>304s</dt><dd>${x.not_modified.toLocaleString()}</dd><dt>Retries</dt><dd>${x.retries}</dd></dl></div>`).join("")}</section>
  <section class="row r-21">
    <div class="panel reveal" style="--i:7"><div class="ph"><div><div class="eyebrow">Change-aware</div><h2>Day one is the only expensive day</h2><p>${c.day0_requests} requests for the first full crawl, then ${c.steady_requests_per_day} a day: listings first, product pages only when something is new.</p></div>
      <div class="legend">${STORES.map((s) => `<span><i style="background:${SC[s]}"></i>${short(s)}</span>`).join("")}</div></div><div id="cstack"></div></div>
    <div class="panel reveal" style="--i:8"><div class="ph"><div><div class="eyebrow">Data quality</div><h2>Nothing malformed gets stored</h2></div></div>
      <dl style="display:grid;grid-template-columns:1fr auto;gap:10px;margin:0;font-size:.86rem">
        <dt style="color:var(--muted)">Price observations stored</dt><dd class="num" style="margin:0">${c.observations.toLocaleString()}</dd>
        <dt style="color:var(--muted)">Rows quarantined by validation</dt><dd class="num" style="margin:0">${c.quarantined}</dd>
        <dt style="color:var(--muted)">Barcodes check-digit verified</dt><dd class="num" style="margin:0">every one</dd>
        <dt style="color:var(--muted)">Pricing errors flagged, not trusted</dt><dd class="num" style="margin:0">${state.ov?.kpis.pricing_errors ?? 2}</dd>
        <dt style="color:var(--muted)">Data transferred</dt><dd class="num" style="margin:0">${(c.bytes / 1048576).toFixed(1)} MB</dd></dl>
      <p class="chart-desc">A price that is valid but implausible, like a dropped digit, is stored and flagged instead of silently feeding the repricer.</p></div>
  </section>
  <section class="panel reveal" style="--i:9"><div class="ph"><div><div class="eyebrow">Request log</div><h2 id="lg-h">Today's run</h2><p>Every request, as the crawler made it.</p></div>
    <div style="display:flex;gap:8px;flex-wrap:wrap"><div class="seg" role="group" aria-label="Day"><button type="button" data-lday="today" aria-pressed="true">Today</button><button type="button" data-lday="day0" aria-pressed="false">Day 1 (full crawl)</button></div>
    <div class="seg" role="group" aria-label="Status">${[["all", "All"], ["2", "2xx"], ["3", "304"], ["4", "4xx/5xx"]].map(([v, l], i) => `<button type="button" data-lst="${v}" aria-pressed="${i === 0}">${l}</button>`).join("")}</div></div></div>
    <div class="scroll-y" style="max-height:420px"><table class="tbl"><thead><tr><th scope="col">t</th><th scope="col">Store</th><th scope="col">Status</th><th scope="col">Path</th><th class="r" scope="col">Time</th><th class="r" scope="col">Size</th><th scope="col">Note</th></tr></thead><tbody id="lgb"></tbody></table></div></section>`;
  stacked($("#cstack"), Array.from({ length: 30 }, (_, d) => Object.fromEntries(STORES.map((s) => [s, cr.runs.find((r) => r.day === d && r.store === s)?.requests || 0]))), STORES, STORES.map((s) => SC[s]), { labels: L });
  let lday = "today", lst = "all";
  const drawLog = () => {
    const rows = (lday === "today" ? cr.log : cr.log0).filter((r) => lst === "all" || String(r.status)[0] === lst || (lst === "4" && String(r.status)[0] === "5"));
    $("#lg-h").textContent = lday === "today" ? `Today's run · ${cr.log.length} requests` : `Day 1, the full crawl · ${cr.log0.length} requests`;
    $("#lgb").innerHTML = rows.slice(0, 400).map((r) => `<tr><td class="num">${(r.t_ms / 1000).toFixed(3)}s</td><td>${chip(r.store)}</td>
      <td><span class="pos ${r.status < 300 ? "cheapest" : r.status < 400 ? "matched" : "above"}">${r.status}</span></td><td class="num" style="font-size:.76rem">${esc(r.url)}</td>
      <td class="r num">${r.ms.toFixed(0)} ms</td><td class="r num">${r.bytes ? (r.bytes / 1024).toFixed(1) + " kB" : "—"}</td><td style="color:var(--muted)">${esc(r.note || "")}</td></tr>`).join("");
  };
  $$("[data-lday]", view).forEach((b) => b.addEventListener("click", () => { lday = b.dataset.lday; $$("[data-lday]", view).forEach((x) => x.setAttribute("aria-pressed", x === b)); drawLog(); }));
  $$("[data-lst]", view).forEach((b) => b.addEventListener("click", () => { lst = b.dataset.lst; $$("[data-lst]", view).forEach((x) => x.setAttribute("aria-pressed", x === b)); drawLog(); }));
  drawLog();
}

/* ---------------------------------------------------------------- shared: table view of chart data */
function tableToggle(host, head, rows) {
  if (!host) return;
  const id = "t" + Math.random().toString(36).slice(2, 7);
  host.innerHTML = `<button class="tbl-toggle" type="button" aria-expanded="${prefs.tables}" aria-controls="${id}">${prefs.tables ? "Hide" : "View"} data as a table</button>
    <div id="${id}" class="data-table" ${prefs.tables ? "" : "hidden"}><table class="tbl"><thead><tr>${head.map((h) => `<th scope="col">${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${r.map((c, i) => (i ? `<td class="num">${esc(c)}</td>` : `<th scope="row" style="position:static;text-transform:none;letter-spacing:0">${esc(c)}</th>`)).join("")}</tr>`).join("")}</tbody></table></div>`;
  const b = host.querySelector("button"), t = host.querySelector(".data-table");
  b.addEventListener("click", () => { t.hidden = !t.hidden; b.setAttribute("aria-expanded", !t.hidden); b.textContent = (t.hidden ? "View" : "Hide") + " data as a table"; });
}
function onResize(view, fn) {
  let w = view.clientWidth, t;
  const ro = new ResizeObserver(() => { if (Math.abs(view.clientWidth - w) > 30) { w = view.clientWidth; clearTimeout(t); t = setTimeout(fn, 150); } });
  ro.observe(view);
}

/* ---------------------------------------------------------------- dialogs, palette, shortcuts, a11y panel */
let lastFocus = null;
function openDialog(id) {
  const d = document.getElementById(id);
  if (d.hidden) lastFocus = document.activeElement;
  d.hidden = false;
  const f = d.querySelector("input, .drawer-panel, button");
  setTimeout(() => f?.focus(), 30);
}
function closeDialog(d) {
  d.hidden = true; hideTip();
  if (lastFocus && document.body.contains(lastFocus)) lastFocus.focus();
}
document.addEventListener("click", (e) => {
  const op = e.target.closest("[data-open]");
  if (op) { const id = op.dataset.open; if (id === "a11y") renderA11y(); if (id === "palette") openPalette(); else if (id === "shortcuts") renderShortcuts(); openDialog(id); }
  const cl = e.target.closest("[data-close]");
  if (cl) { const d = cl.closest(".drawer, .palette"); if (d) closeDialog(d); }
  if (e.target.closest("[data-theme-toggle]")) { prefs.theme = prefs.theme === "light" ? "dark" : "light"; applyPrefs(); rerenderCharts(); announce(`${prefs.theme} theme`); }
});
function trap(e) {
  const d = [...document.querySelectorAll(".drawer:not([hidden]), .palette:not([hidden])")].pop();
  if (!d || e.key !== "Tab") return;
  const f = [...d.querySelectorAll('button, [href], input, select, [tabindex]:not([tabindex="-1"])')].filter((x) => !x.hidden && x.offsetParent !== null);
  if (!f.length) return;
  if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f.at(-1).focus(); }
  else if (!e.shiftKey && document.activeElement === f.at(-1)) { e.preventDefault(); f[0].focus(); }
}
document.addEventListener("keydown", (e) => {
  trap(e);
  const open = [...document.querySelectorAll(".drawer:not([hidden]), .palette:not([hidden])")].pop();
  if (e.key === "Escape" && open) { closeDialog(open); return; }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); openDialog("palette"); return; }
  const typing = /INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName);
  if (open || typing || e.ctrlKey || e.metaKey || e.altKey) return;
  if (/^[1-6]$/.test(e.key)) { location.hash = "#/" + Object.keys(VIEWS)[+e.key - 1]; return; }
  if (e.key === "?") { renderShortcuts(); openDialog("shortcuts"); return; }
  if (e.key === "/") { const q = $("#pq"); if (q) { e.preventDefault(); q.focus(); } else { e.preventDefault(); openPalette(); openDialog("palette"); } return; }
  if (e.key.toLowerCase() === "t") { prefs.theme = prefs.theme === "light" ? "dark" : "light"; applyPrefs(); rerenderCharts(); return; }
  $("#view")._keys?.(e);
});
function rerenderCharts() { if (!$("#drawer").hidden) return; route(); }

const PAGES = Object.entries(VIEWS).map(([k, v], i) => ({ g: "Go to", label: v.title, hint: String(i + 1), run: () => (location.hash = "#/" + k) }));
const ACTIONS = [
  { g: "Actions", label: "Switch to high-contrast theme", run: () => { prefs.theme = "contrast"; applyPrefs(); route(); } },
  { g: "Actions", label: "Switch light / dark theme", hint: "T", run: () => { prefs.theme = prefs.theme === "light" ? "dark" : "light"; applyPrefs(); route(); } },
  { g: "Actions", label: "Use colour-blind safe palette", run: () => { prefs.cvd = "safe"; applyPrefs(); route(); } },
  { g: "Actions", label: "Reduce motion", run: () => { prefs.motion = "reduced"; applyPrefs(); } },
  { g: "Actions", label: "Open accessibility settings", run: () => { renderA11y(); openDialog("a11y"); } },
  { g: "Actions", label: "Show keyboard shortcuts", hint: "?", run: () => { renderShortcuts(); openDialog("shortcuts"); } },
  { g: "Actions", label: "Review uncertain matches", run: () => (location.hash = "#/matching") },
];
let palItems = [], palSel = 0;
async function openPalette() {
  state.products ||= await api("/api/products");
  const q = $("#palette-q");
  q.value = "";
  drawPalette("");
  q.oninput = () => drawPalette(q.value);
  q.onkeydown = (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); palSel = (palSel + (e.key === "ArrowDown" ? 1 : -1) + palItems.length) % palItems.length; drawPalette(q.value, true); }
    if (e.key === "Enter" && palItems[palSel]) { e.preventDefault(); const it = palItems[palSel]; closeDialog($("#palette")); it.run(); }
  };
}
function drawPalette(q, keep) {
  const s = q.trim().toLowerCase();
  const prods = (state.products || []).filter((p) => s && (p.title + " " + p.sku).toLowerCase().includes(s)).slice(0, 7)
    .map((p) => ({ g: "Products", label: p.title, hint: `${p.sku} · ${money(p.ours)}`, run: () => openProduct(p.sku) }));
  palItems = [...PAGES, ...ACTIONS].filter((x) => !s || x.label.toLowerCase().includes(s)).concat(prods);
  if (s) palItems.sort((a, b) => (a.g === "Products") - (b.g === "Products"));
  if (!keep) palSel = 0;
  let g = null;
  $("#palette-list").innerHTML = palItems.map((it, i) => {
    const head = it.g !== g ? `<li class="grp" role="presentation">${it.g}</li>` : "";
    g = it.g;
    return head + `<li role="option" id="po${i}" aria-selected="${i === palSel}" data-i="${i}">${esc(it.label)}${it.hint ? `<small>${esc(it.hint)}</small>` : ""}</li>`;
  }).join("") || `<li class="grp">No results for “${esc(q)}”</li>`;
  $("#palette-q").setAttribute("aria-activedescendant", "po" + palSel);
  $("#po" + palSel)?.scrollIntoView({ block: "nearest" });
  $$("#palette-list [data-i]").forEach((li) => li.addEventListener("click", () => { const it = palItems[+li.dataset.i]; closeDialog($("#palette")); it.run(); }));
}
function renderShortcuts() {
  const rows = [["Open command palette", "Ctrl K"], ["Go to a page", "1 – 6"], ["Search products", "/"], ["Toggle light / dark", "T"], ["Show this list", "?"],
    ["Accept match (review)", "A"], ["Reject match (review)", "R"], ["Skip match (review)", "S"], ["Read a chart day by day", "← →"], ["Move in the gap map", "Arrow keys"], ["Close a panel", "Esc"]];
  $("#sc-body").innerHTML = `<div class="sc-grid">${rows.map(([a, k]) => `<div><span>${a}</span><kbd>${k}</kbd></div>`).join("")}</div>`;
}
function renderA11y() {
  const opt = (group, val, label, sub, sw) => `<button type="button" class="opt" role="radio" aria-checked="${prefs[group] === val}" data-pg="${group}" data-pv="${val}">
    <span class="sw" style="${sw.bg}">${sw.bars.map((c) => `<i style="background:${c};height:${20 + Math.random() * 60}%"></i>`).join("")}</span>${label}<small>${sub}</small></button>`;
  $("#a11y-body").innerHTML = `<div class="a11y"><div class="d-head" style="margin:0"><div><div class="eyebrow">Accessibility</div><h2 id="a11y-title">Make Northvane yours</h2></div>
      <button class="close" data-close aria-label="Close accessibility settings">✕</button></div>
    <p>Saved on this device. Charts, colours and motion update instantly.</p>
    <fieldset><legend>Theme</legend><div class="opt-grid" role="radiogroup" aria-label="Theme">
      ${opt("theme", "dark", "Dark", "default", { bg: "background:#0b0f16", bars: ["#5eead4", "#a78bfa", "#fbbf24"] })}
      ${opt("theme", "light", "Light", "bright rooms", { bg: "background:#f4f6fa", bars: ["#0d9488", "#7c3aed", "#d97706"] })}
      ${opt("theme", "contrast", "High contrast", "WCAG AAA text", { bg: "background:#000;border-color:#fff", bars: ["#00ffd0", "#ffe500", "#ff9cf3"] })}</div></fieldset>
    <fieldset><legend>Colour vision</legend><div class="opt-grid" role="radiogroup" aria-label="Colour vision">
      ${opt("cvd", "default", "Default", "mint and coral", { bg: "background:var(--panel-2)", bars: ["#5eead4", "#fb7185", "#a78bfa"] })}
      ${opt("cvd", "safe", "Colour-blind safe", "Okabe–Ito palette", { bg: "background:var(--panel-2)", bars: ["#56b4e9", "#e69f00", "#cc79a7"] })}
      ${opt("cvd", "mono", "Monochrome", "values in text", { bg: "background:var(--panel-2)", bars: ["#ccc", "#888", "#555"] })}</div></fieldset>
    <fieldset><legend>Text size <output id="fs-out" class="num" style="color:var(--mint);margin-left:6px">${Math.round(prefs.fs * 100)}%</output></legend>
      <input type="range" id="fs" min="0.9" max="1.4" step="0.05" value="${prefs.fs}" aria-label="Text size"></fieldset>
    <fieldset><legend>Motion</legend><div class="seg" role="group" aria-label="Motion">${[["system", "Follow system"], ["reduced", "Reduced"], ["full", "Full"]].map(([v, l]) => `<button type="button" data-mo="${v}" aria-pressed="${prefs.motion === v}">${l}</button>`).join("")}</div></fieldset>
    <div class="switch"><span>Show charts as tables<small>Every chart gets its numbers in a table underneath</small></span><button type="button" role="switch" data-sw="tables" aria-checked="${prefs.tables}" aria-label="Show charts as tables"></button></div>
    <div class="switch"><span>Compact density<small>More rows on screen</small></span><button type="button" role="switch" data-sw="density" aria-checked="${prefs.density === "compact"}" aria-label="Compact density"></button></div>
    <div class="switch"><span>Screen reader announcements<small>Speak changes like new matches and saved rules</small></span><button type="button" role="switch" data-sw="announce" aria-checked="${prefs.announce}" aria-label="Screen reader announcements"></button></div>
    <p class="demo-note" style="margin-top:16px">Keyboard: every control is reachable with Tab. Press <kbd>?</kbd> for shortcuts.</p></div>`;
  const body = $("#a11y-body");
  $$("[data-pg]", body).forEach((b) => b.addEventListener("click", () => {
    prefs[b.dataset.pg] = b.dataset.pv; applyPrefs();
    $$(`[data-pg="${b.dataset.pg}"]`, body).forEach((x) => x.setAttribute("aria-checked", x === b));
    route(); announce(`${b.textContent.trim().split("\n")[0]} on`);
  }));
  $("#fs", body).addEventListener("input", (e) => { prefs.fs = +e.target.value; applyPrefs(); $("#fs-out").textContent = Math.round(prefs.fs * 100) + "%"; });
  $("#fs", body).addEventListener("change", () => route());
  $$("[data-mo]", body).forEach((b) => b.addEventListener("click", () => { prefs.motion = b.dataset.mo; applyPrefs(); $$("[data-mo]", body).forEach((x) => x.setAttribute("aria-pressed", x === b)); announce(`Motion ${b.textContent}`); }));
  $$("[data-sw]", body).forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.sw;
    if (k === "density") prefs.density = prefs.density === "compact" ? "comfortable" : "compact"; else prefs[k] = !prefs[k];
    b.setAttribute("aria-checked", k === "density" ? prefs.density === "compact" : prefs[k]); applyPrefs(); if (k === "tables") route();
  }));
}

/* ---------------------------------------------------------------- boot */
(async function boot() {
  state.meta = await api("/api/meta");
  const fmt = (d, o) => new Date(d + "T12:00:00").toLocaleDateString("en-US", o);
  L = state.meta.days.map((d) => fmt(d, { month: "short", day: "numeric" }));
  TL = state.meta.days.map((d) => fmt(d, { weekday: "short", month: "short", day: "numeric" }));
  $("#today-chip").textContent = fmt(state.meta.today, { weekday: "short", month: "short", day: "numeric", year: "numeric" }) + " · day 30";
  api("/api/review").then((r) => ($("#nav-review").textContent = r.counts.review));
  addEventListener("hashchange", route);
  route();
})();
