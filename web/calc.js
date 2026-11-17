// Lógica de cálculo de la versión web (sin DOM). Es un port de albionbm/calc.py y albionbm/api.py.
// Funciona en el navegador (window.AlbionCalc) y en Node (tests).
(function (root) {
  "use strict";

  const BLACK_MARKET = "Black Market";
  const CITIES = ["Caerleon", "Bridgewatch", "Martlock", "Lymhurst", "Fort Sterling", "Thetford", "Brecilien"];
  const SETUP_FEE = 0.025, TAX_PREMIUM = 0.04, TAX_NO_PREMIUM = 0.08, SUSPICIOUS_FACTOR = 1.6;
  const QUALITY_NAMES = { 1: "Normal", 2: "Buena", 3: "Notable", 4: "Sobresaliente", 5: "Obra maestra" };
  const STRATEGIES = {
    bm: "Ciudad → Mercado Negro",
    city_instant: "Entre ciudades · venta rápida",
    city_order: "Entre ciudades · orden de venta",
  };
  const PROFILES = {
    max: { name: "Máximo beneficio", maxShare: 0.5, volumeFraction: 1.0, maxAgeH: null, needVolume: false,
      description: "Concentra el capital en lo más rentable. Más ganancia esperada, más riesgo." },
    balanced: { name: "Equilibrado", maxShare: 0.25, volumeFraction: 0.6, maxAgeH: 6, needVolume: false,
      description: "Reparte entre más objetos y no intenta colocar más del 60 % del volumen diario." },
    safe: { name: "Seguro", maxShare: 0.12, volumeFraction: 0.3, maxAgeH: 2, needVolume: true,
      description: "Solo datos de menos de 2 h, objetos con ventas diarias conocidas y mucho reparto." },
  };

  const key = (...parts) => parts.join("|");

  /** Fecha de la API (UTC sin zona) -> segundos, o null. */
  function parseApiDate(s) {
    if (!s || s.startsWith("0001")) return null;
    const t = Date.parse(/[zZ]$/.test(s) ? s : s + "Z");
    return Number.isNaN(t) ? null : t / 1000;
  }

  function chunkIds(ids, maxChars) {
    const limit = maxChars || 1800, chunks = [];
    let cur = [], len = 0;
    for (const id of ids) {
      if (cur.length && len + id.length + 1 > limit) { chunks.push(cur); cur = []; len = 0; }
      cur.push(id); len += id.length + 1;
    }
    if (cur.length) chunks.push(cur);
    return chunks;
  }

  /** Filas de /stats/prices -> añade a `entries` (Map) si el dato es más reciente. Devuelve cuántas se guardaron. */
  function mergePrices(entries, rows) {
    let n = 0;
    for (const r of rows) {
      if (r.city !== BLACK_MARKET && !CITIES.includes(r.city)) continue;
      const q = r.quality || 1;
      for (const [kind, pf, df] of [["offer", "sell_price_min", "sell_price_min_date"],
                                    ["request", "buy_price_max", "buy_price_max_date"]]) {
        const price = r[pf] || 0, ts = parseApiDate(r[df]);
        if (price <= 0 || !ts) continue;
        const k = key(r.item_id, q, r.city, kind), old = entries.get(k);
        if (!old || ts >= old.ts) { entries.set(k, { p: price, ts, src: "api" }); n++; }
      }
    }
    return n;
  }

  /** Filas de /stats/history -> añade a `stats` (Map): { daily, avg } de los últimos `days` días. */
  function mergeHistory(stats, rows, now, days) {
    days = days || 7;
    const since = (now || Date.now() / 1000) - days * 86400;
    const acc = new Map();
    for (const r of rows) {
      const k = key(r.item_id, r.quality || 1, r.location || BLACK_MARKET);
      const a = acc.get(k) || [0, 0];
      for (const d of r.data || []) {
        const ts = parseApiDate(d.timestamp), n = d.item_count || 0;
        if (ts && ts >= since && n > 0) { a[0] += n; a[1] += n * (d.avg_price || 0); }
      }
      acc.set(k, a);
    }
    for (const [k, [n, total]] of acc) stats.set(k, { daily: n / days, avg: n && total ? total / n : null });
    return acc.size;
  }

  /**
   * Oportunidades. entries: Map "item|q|loc|kind" -> {p, ts, src}; stats: Map "item|q|loc" -> {daily, avg}.
   * opts: { cities, qualities, premium, buyMode: "instant"|"order", strategy, now, maxAgeH }
   */
  function compute(entries, stats, opts) {
    const now = opts.now || Date.now() / 1000;
    const tax = opts.premium === false ? TAX_NO_PREMIUM : TAX_PREMIUM;
    const strategy = opts.strategy || "bm";
    const cities = opts.cities, qualities = opts.qualities;
    const sellLocs = strategy === "bm" ? [BLACK_MARKET] : cities;
    const minTs = opts.maxAgeH ? now - opts.maxAgeH * 3600 : -Infinity;
    const buyKind = opts.buyMode === "order" ? "request" : "offer";
    stats = stats || new Map();

    const items = new Set();
    for (const k of entries.keys()) items.add(k.slice(0, k.indexOf("|")));
    const get = (item, q, loc, kind) => {
      const e = entries.get(key(item, q, loc, kind));
      return e && e.ts >= minTs ? e : null;
    };

    const result = [];
    for (const item of items) {
      for (const city of cities) {
        for (const q of qualities) {
          const c = get(item, q, city, buyKind);
          if (!c || c.p <= 0) continue;
          const cost = opts.buyMode === "order" ? c.p * (1 + SETUP_FEE) : c.p;
          for (const sell of sellLocs) {
            if (sell === city) continue;
            let b, bq, revenue, st = [];
            if (strategy === "city_order") {
              b = get(item, q, sell, "offer");
              if (!b) continue;
              bq = q; revenue = b.p * (1 - tax - SETUP_FEE);
              st = [stats.get(key(item, q, sell))];
            } else {
              for (let qq = 1; qq <= q; qq++) {
                const bb = get(item, qq, sell, "request");
                if (bb && (!b || bb.p > b.p)) { b = bb; bq = qq; }
                st.push(stats.get(key(item, qq, sell)));
              }
              if (!b) continue;
              revenue = b.p * (1 - tax);
            }
            const profit = revenue - cost;
            st = st.filter(Boolean);
            const vol = st.length ? st.reduce((s, x) => s + x.daily, 0) : null;
            const ref = stats.get(key(item, bq, sell));
            const avg = ref ? ref.avg : null;
            let units = null, invest = null, total = null;
            if (vol && profit > 0) {
              units = Math.max(1, Math.floor(vol));
              invest = Math.round(units * cost); total = Math.round(units * profit);
            }
            result.push({
              itemId: item, quality: q, city, sellCity: sell, sellQuality: bq,
              buyPrice: Math.round(cost), sellPrice: b.p, revenue: Math.round(revenue), profit: Math.round(profit),
              percent: (profit / cost) * 100,
              buyAgeH: Math.max(0, (now - c.ts) / 3600), sellAgeH: Math.max(0, (now - b.ts) / 3600),
              units, invest, totalProfit: total, dailyVolume: vol, avgPrice: avg,
              suspicious: !!(avg && b.p > avg * SUSPICIOUS_FACTOR),
            });
          }
        }
      }
    }
    return result;
  }

  function bestPerItem(opps) {
    const best = new Map();
    for (const o of opps) {
      const k = key(o.itemId, o.quality);
      if (!best.has(k) || best.get(k).profit < o.profit) best.set(k, o);
    }
    return [...best.values()];
  }

  // Riesgo del transporte: llegar a Caerleon (y su Mercado Negro) o a Brecilien cruza zona roja o la niebla.
  const RISKY = new Set(["Caerleon", BLACK_MARKET, "Brecilien"]), SAME_CITY = new Set(["Caerleon", BLACK_MARKET]);
  function routeRisky(buy, sell) {
    if (SAME_CITY.has(buy) && SAME_CITY.has(sell)) return false;  // comprar en Caerleon y vender en su MN
    return RISKY.has(buy) || RISKY.has(sell);
  }
  /** Beneficio esperado si con probabilidad `risk` pierdes la carga entera. */
  const expectedProfit = (invest, profit, risk) => (invest + profit) * (1 - risk) - invest;

  /** Reparto voraz del capital. opts: { profile, maxShare, maxWeight, weightOf, risk (0-1), maxRisk }.
   *  Devuelve { lines: [{opp, units, invest, profit, weight, expected, risky}], left }. */
  function plan(opps, capital, opts) {
    opts = opts || {};
    const p = PROFILES[opts.profile] || PROFILES.max;
    const share = opts.maxShare != null ? opts.maxShare : p.maxShare;
    const maxWeight = opts.maxWeight || null;
    const weightOf = opts.weightOf || (() => 0);
    const cands = [];
    for (const o of opps) {
      if (o.suspicious || !o.units || !o.invest || !o.totalProfit || o.totalProfit <= 0) continue;
      if (p.maxAgeH != null && Math.max(o.buyAgeH, o.sellAgeH) > p.maxAgeH) continue;
      if (p.needVolume && !o.dailyVolume) continue;
      let cap = o.units;
      if (o.dailyVolume) cap = Math.min(cap, Math.max(1, Math.floor(o.dailyVolume * p.volumeFraction)));
      const unitCost = o.invest / o.units, unitProfit = o.totalProfit / o.units, w = weightOf(o.itemId) || 0;
      const risky = routeRisky(o.city, o.sellCity);
      const unitExpected = risky ? expectedProfit(unitCost, unitProfit, opts.risk || 0) : unitProfit;
      if (unitExpected <= 0) continue;
      const density = unitExpected / (unitCost / capital + (maxWeight ? w / maxWeight : 0));
      cands.push({ density, o, cap, unitCost, unitProfit, w, risky, unitExpected });
    }
    cands.sort((a, b) => b.density - a.density);
    let left = capital, weightLeft = maxWeight, riskyLeft = opts.maxRisk || null;
    const lines = [], used = new Set();
    for (const c of cands) {
      if (left <= 0) break;
      const k = key(c.o.itemId, c.o.sellCity);
      if (used.has(k)) continue;
      let n = Math.min(c.cap, Math.floor(Math.min(left, capital * share) / c.unitCost));
      if (weightLeft != null && c.w > 0) n = Math.min(n, Math.floor(weightLeft / c.w));
      if (c.risky && riskyLeft != null) n = Math.min(n, Math.floor(riskyLeft / c.unitCost));
      if (n <= 0) continue;
      const inv = Math.round(n * c.unitCost);
      lines.push({ opp: c.o, units: n, invest: inv, profit: Math.round(n * c.unitProfit), weight: n * c.w,
        expected: Math.round(n * c.unitExpected), risky: c.risky });
      used.add(k);
      left -= inv;
      if (c.risky && riskyLeft != null) riskyLeft -= inv;
      if (weightLeft != null) weightLeft -= n * c.w;
    }
    return { lines, left: Math.round(left) };
  }

  /** Mejor cargamento por ruta (compra → venta), ordenado por beneficio. */
  function planRoutes(opps, capital, opts, top) {
    const byRoute = new Map();
    for (const o of opps) {
      const k = key(o.city, o.sellCity);
      if (!byRoute.has(k)) byRoute.set(k, []);
      byRoute.get(k).push(o);
    }
    const out = [];
    for (const [k, list] of byRoute) {
      const { lines } = plan(list, capital, opts);
      if (!lines.length) continue;
      const [buyCity, sellCity] = k.split("|");
      const sum = (f) => lines.reduce((s, l) => s + l[f], 0);
      out.push({ buyCity, sellCity, lines, invest: sum("invest"), profit: sum("profit"), weight: sum("weight"),
        expected: sum("expected"), risky: routeRisky(buyCity, sellCity) });
    }
    out.sort((a, b) => b.expected - a.expected);
    return out.slice(0, top || 8);
  }

  /** Dónde sacar más por un objeto que ya tienes: venta rápida (mejor orden de compra que acepte tu calidad)
   *  u orden de venta (igualando la más barata, +2,5 %). Ordenado por plata neta por unidad. */
  function sellingPlaces(item, quality, entries, locations, premium) {
    const tax = premium === false ? TAX_NO_PREMIUM : TAX_PREMIUM, out = [];
    for (const loc of locations) {
      let best = null;
      for (let q = 1; q <= quality; q++) {
        const e = entries.get(key(item, q, loc, "request"));
        if (e && e.p > 0 && (!best || e.p > best.p)) best = e;
      }
      if (best) out.push({ location: loc, mode: "quick", price: best.p, net: best.p * (1 - tax), ts: best.ts });
      if (loc !== BLACK_MARKET) {
        const e = entries.get(key(item, quality, loc, "offer"));
        if (e && e.p > 0) out.push({ location: loc, mode: "order", price: e.p, net: e.p * (1 - tax - SETUP_FEE), ts: e.ts });
      }
    }
    return out.sort((a, b) => b.net - a.net);
  }

  const api = { routeRisky, expectedProfit, sellingPlaces, BLACK_MARKET, CITIES, QUALITY_NAMES, STRATEGIES, PROFILES, SETUP_FEE, TAX_PREMIUM, TAX_NO_PREMIUM,
    parseApiDate, chunkIds, mergePrices, mergeHistory, compute, bestPerItem, plan, planRoutes };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AlbionCalc = api;
})(typeof window !== "undefined" ? window : globalThis);
