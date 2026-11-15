// Lógica pura de cálculo (sin DOM). Funciona en el navegador y en Node (tests).
(function (root) {
  "use strict";

  const BLACK_MARKET = "Black Market";
  const CITIES = ["Caerleon", "Bridgewatch", "Martlock", "Lymhurst", "Fort Sterling", "Thetford", "Brecilien"];
  const QUALITY_NAMES = { 1: "Normal", 2: "Buena", 3: "Notable", 4: "Sobresaliente", 5: "Obra maestra" };

  /** Convierte la fecha de la API (UTC sin zona) a milisegundos, o null si no hay dato. */
  function parseDate(s) {
    if (!s || s.startsWith("0001")) return null;
    const t = Date.parse(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z");
    return Number.isNaN(t) ? null : t;
  }

  /** Antigüedad en horas (Infinity si no hay fecha). */
  function ageHours(s, now) {
    const t = parseDate(s);
    return t == null ? Infinity : Math.max(0, (now - t) / 3600000);
  }

  /** Agrupa las filas de la API por objeto: { itemId: { bm: {q: row}, cities: {city: {q: row}} } } */
  function groupRows(rows) {
    const out = {};
    for (const r of rows) {
      const g = (out[r.item_id] ||= { bm: {}, cities: {} });
      if (r.city === BLACK_MARKET) g.bm[r.quality] = r;
      else (g.cities[r.city] ||= {})[r.quality] = r;
    }
    return out;
  }

  /**
   * Calcula todas las oportunidades ciudad -> Mercado Negro.
   *
   * Reglas del juego aplicadas:
   *  - En el Mercado Negro se vende a las órdenes de compra (buy_price_max).
   *  - Una orden de compra de calidad Q acepta objetos de calidad >= Q, así que un objeto
   *    comprado con calidad q puede venderse a la mejor orden de calidad <= q.
   *  - Vender a una orden paga impuesto de venta (4 % con prémium, 8 % sin prémium).
   *  - Comprar con orden de compra paga además la tasa de publicación (2,5 %).
   *
   * opts: {
   *   now, maxAgeHours, premium, buyMode: "instant" | "order",
   *   setupFee (0.025), taxPremium (0.04), taxNoPremium (0.08),
   *   cities: [..], qualities: [..]
   * }
   */
  function computeOpportunities(rows, opts) {
    const o = Object.assign(
      { now: Date.now(), maxAgeHours: 24, premium: true, buyMode: "instant", setupFee: 0.025,
        taxPremium: 0.04, taxNoPremium: 0.08, cities: CITIES, qualities: [1, 2, 3, 4, 5] },
      opts || {}
    );
    const tax = o.premium ? o.taxPremium : o.taxNoPremium;
    const grouped = groupRows(rows);
    const result = [];

    for (const [itemId, g] of Object.entries(grouped)) {
      for (const city of o.cities) {
        const cityRows = g.cities[city];
        if (!cityRows) continue;
        for (const q of o.qualities) {
          const c = cityRows[q];
          if (!c) continue;

          // Precio de compra en la ciudad
          let cost, costDate;
          if (o.buyMode === "order") {
            if (!c.buy_price_max) continue;
            cost = c.buy_price_max * (1 + o.setupFee);
            costDate = c.buy_price_max_date;
          } else {
            if (!c.sell_price_min) continue;
            cost = c.sell_price_min;
            costDate = c.sell_price_min_date;
          }
          const costAge = ageHours(costDate, o.now);
          if (costAge > o.maxAgeHours) continue;

          // Mejor orden del Mercado Negro que acepte esta calidad
          let best = null;
          for (let bq = 1; bq <= q; bq++) {
            const b = g.bm[bq];
            if (!b || !b.buy_price_max) continue;
            const bAge = ageHours(b.buy_price_max_date, o.now);
            if (bAge > o.maxAgeHours) continue;
            if (!best || b.buy_price_max > best.price) best = { price: b.buy_price_max, quality: bq, age: bAge };
          }
          if (!best) continue;

          const revenue = best.price * (1 - tax);
          const profit = revenue - cost;
          result.push({
            itemId, city, quality: q, bmQuality: best.quality,
            buyPrice: Math.round(cost), bmPrice: best.price,
            revenue: Math.round(revenue), profit: Math.round(profit),
            percent: (profit / cost) * 100,
            buyAge: costAge, bmAge: best.age,
          });
        }
      }
    }
    return result;
  }

  /** Divide la lista de IDs en lotes para no superar la longitud máxima de URL. */
  function chunkIds(ids, maxChars) {
    const limit = maxChars || 1800;
    const chunks = [];
    let cur = [], len = 0;
    for (const id of ids) {
      if (cur.length && len + id.length + 1 > limit) { chunks.push(cur); cur = []; len = 0; }
      cur.push(id); len += id.length + 1;
    }
    if (cur.length) chunks.push(cur);
    return chunks;
  }

  /** ID de API para un objeto base con encantamiento (T4_BAG + 2 -> T4_BAG@2). */
  function variantId(baseId, ench) {
    return ench ? `${baseId}@${ench}` : baseId;
  }

  const api = { BLACK_MARKET, CITIES, QUALITY_NAMES, parseDate, ageHours, groupRows,
    computeOpportunities, chunkIds, variantId };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AlbionCalc = api;
})(typeof window !== "undefined" ? window : globalThis);
