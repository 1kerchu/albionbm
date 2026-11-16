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

  const api = { returnRate, craft, trade, upgrade, taxRate, SETUP_FEE };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AlbionCalculators = api;
})(typeof window !== "undefined" ? window : globalThis);
