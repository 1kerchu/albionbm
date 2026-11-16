// Calculadoras: fabricación, refinado, venta manual y mejora de encantamiento.
// Mismo cálculo que albionbm/calculators.py (los tests comprueban que coinciden).
(function (root) {
  "use strict";
  const SETUP_FEE = 0.025, TAX_PREMIUM = 0.04, TAX_NO_PREMIUM = 0.08;
  const PB_BASE = 0.18, PB_CITY = { craft: 0.15, refine: 0.40 }, PB_FOCUS = 0.59, NUTRITION_PER_VALUE = 0.1125;

  const taxRate = (premium) => (premium === false ? TAX_NO_PREMIUM : TAX_PREMIUM);

  /** Proporción de materiales que se devuelve (0,152 = 15,2 %). */
  function returnRate(kind, cityBonus, focus) {
    const pb = PB_BASE + (cityBonus ? PB_CITY[kind || "craft"] : 0) + (focus ? PB_FOCUS : 0);
    return 1 - 1 / (1 + pb);
  }

  /** opts: { rrr, fee100, premium, sellOrder, quantity } */
  function craft(recipe, values, prices, sellPrice, opts) {
    const o = Object.assign({ rrr: 0, fee100: 0, premium: true, sellOrder: true, quantity: 1 }, opts);
    const materials = [], missing = [];
    let gross = 0, returned = 0, itemValue = 0;
    for (const [id, count, returnable] of recipe.m) {
      let price = prices[id];
      if (!price) { missing.push(id); price = 0; }
      const cost = price * count;
      gross += cost;
      if (returnable) returned += cost * o.rrr;
      itemValue += (values[id] || 0) * count;
      materials.push({ id, count, price, cost, returnable: !!returnable });
    }
    const n = recipe.n || 1;
    const fee = itemValue * NUTRITION_PER_VALUE * o.fee100 / 100;
    const costPerCraft = gross - returned + fee, unitCost = costPerCraft / n;
    const out = { materials, gross, returned, fee, itemValue, costPerCraft, unitsPerCraft: n, unitCost,
      focus: (recipe.f || 0) * o.quantity, units: n * o.quantity, totalCost: costPerCraft * o.quantity, missing,
      unitRevenue: null, unitProfit: null, percent: null, totalProfit: null, profitPerFocus: null };
    if (sellPrice) {
      const rev = sellPrice * (1 - taxRate(o.premium) - (o.sellOrder ? SETUP_FEE : 0));
      const profit = rev - unitCost;
      out.unitRevenue = rev; out.unitProfit = profit;
      out.percent = unitCost > 0 ? (profit / unitCost) * 100 : null;
      out.totalProfit = profit * n * o.quantity;
      if (out.focus) out.profitPerFocus = out.totalProfit / out.focus;
    }
    return out;
  }

  /** opts: { premium, buyOrder, sellOrder } */
  function trade(buyPrice, sellPrice, quantity, opts) {
    const o = Object.assign({ premium: true, buyOrder: false, sellOrder: false }, opts);
    quantity = quantity || 1;
    const fees = taxRate(o.premium) + (o.sellOrder ? SETUP_FEE : 0);
    const unitCost = buyPrice * (1 + (o.buyOrder ? SETUP_FEE : 0));
    const unitRevenue = sellPrice * (1 - fees), profit = unitRevenue - unitCost;
    return { unitCost, unitRevenue, unitProfit: profit, percent: unitCost > 0 ? (profit / unitCost) * 100 : null,
      totalCost: unitCost * quantity, totalRevenue: unitRevenue * quantity, totalProfit: profit * quantity,
      fees: sellPrice * fees + (unitCost - buyPrice), breakeven: unitCost / (1 - fees) };
  }

  /** steps: [[recurso, cantidad] para .1, .2, .3]. Devuelve null si no se puede mejorar a ese nivel. */
  function upgrade(steps, fromLevel, toLevel, basePrice, resPrices, targetPrice) {
    const rows = [], missing = [];
    let cost = 0;
    for (let lvl = fromLevel + 1; lvl <= toLevel; lvl++) {
      if (lvl - 1 >= steps.length) return null;
      const [id, count] = steps[lvl - 1];
      let price = resPrices[id];
      if (!price) { missing.push(id); price = 0; }
      rows.push({ level: lvl, id, count, price, cost: price * count });
      cost += price * count;
    }
    if (!basePrice) missing.push("base");
    const total = (basePrice || 0) + cost;
    const saving = targetPrice ? targetPrice - total : null;
    return { steps: rows, upgradeCost: cost, total, direct: targetPrice || null, saving, missing,
      worthIt: saving != null && saving > 0 && !missing.length };
  }

  // ------------------------------------------------------------ comprar o fabricar
  const DEFAULT_SLIP = 0.30, MAX_SLIP = 2.0;

  /**
   * Coste de comprar n unidades con subida de precio. book: [[precio, cantidad], ...] de barata a cara
   * (órdenes reales). Lo que no cubran se estima: el precio sube en línea recta hasta +slip al comprar
   * `daily` unidades (ventas de un día). Devuelve { total, avg, exact, covered, noVolume } o null.
   */
  function buyCost(n, best, book, daily, slip) {
    if (slip == null) slip = DEFAULT_SLIP;
    if (n <= 0) return { total: 0, avg: 0, exact: true, covered: 0, noVolume: false };
    let total = 0, left = n, last = best;
    for (const [price, amount] of book || []) {
      const take = Math.min(left, amount);
      if (take > 0) { total += take * price; left -= take; last = price; }
      if (left === 0) break;
    }
    if (!last) return null;
    const covered = n - left;
    let noVolume = false;
    if (left) {
      if (daily > 0) {
        const xCap = slip > 0 ? (MAX_SLIP * daily) / slip : Infinity, a = Math.min(left, xCap);
        total += last * (a + (slip > 0 ? (slip * a * (a - 1)) / (2 * daily) : 0)) + last * (1 + MAX_SLIP) * (left - a);
      } else { total += last * left; noVolume = true; }
    }
    return { total, avg: total / n, exact: left === 0, covered, noVolume };
  }

  /** quote(material, cantidad) -> buyCost() o null. opts: { rrr, fee100 } */
  function craftCost(recipe, values, units, quote, opts) {
    const o = Object.assign({ rrr: 0, fee100: 0 }, opts);
    const per = recipe.n || 1, crafts = Math.ceil(units / per);
    const materials = [], missing = [];
    let total = 0, exact = true, noVolume = false, itemValue = 0;
    for (const [id, count, returnable] of recipe.m) {
      const need = count * crafts, buy = returnable ? Math.ceil(need * (1 - o.rrr)) : need;
      const q = quote(id, buy);
      itemValue += (values[id] || 0) * count;
      if (!q) { missing.push(id); materials.push({ id, need, buy, avg: null, total: 0, exact: false }); continue; }
      total += q.total; exact = exact && q.exact; noVolume = noVolume || q.noVolume;
      materials.push({ id, need, buy, avg: q.avg, total: q.total, exact: q.exact });
    }
    const fee = itemValue * NUTRITION_PER_VALUE * o.fee100 / 100 * crafts, made = crafts * per;
    return { materials, materialsTotal: total, fee, total: total + fee, crafts, units: made, unitCost: (total + fee) / made,
      missing, exact, noVolume };
  }

  /** Compara comprar `units` con fabricarlas, y busca a partir de qué cantidad cambia la respuesta. */
  function buyOrCraft(recipe, values, units, quoteItem, quoteMat, opts) {
    const craftRes = craftCost(recipe, values, units, quoteMat, opts), buy = quoteItem(units);
    const out = { units, buy, craft: craftRes, verdict: null, saving: null, switchAt: null };
    if (!buy || craftRes.missing.length) return out;
    out.verdict = craftRes.unitCost < buy.avg ? "craft" : "buy";
    out.saving = Math.abs(buy.avg - craftRes.unitCost) * units;
    const better = (n) => {
      const b = quoteItem(n), c = craftCost(recipe, values, n, quoteMat, opts);
      return !b || c.missing.length ? null : c.unitCost < b.avg ? "craft" : "buy";
    };
    for (let scale = 1; scale <= 10000; scale *= 10) {
      for (const cand of [scale, scale * 2, scale * 5]) {
        if (cand > units && cand <= 10000) {
          const v = better(cand);
          if (v && v !== out.verdict) { out.switchAt = cand; return out; }
        }
      }
    }
    return out;
  }

  const api = { returnRate, craft, trade, upgrade, taxRate, SETUP_FEE, buyCost, craftCost, buyOrCraft, DEFAULT_SLIP };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AlbionCalculators = api;
})(typeof window !== "undefined" ? window : globalThis);
