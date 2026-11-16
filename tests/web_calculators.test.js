// Mismos casos que tests/test_calculators.py: la web y la app deben dar lo mismo.
const test = require("node:test");
const assert = require("node:assert");
const K = require("../web/calculators.js");

const AXE = { m: [["PLANKS", 12, 1], ["BAR", 20, 1]], f: 1715, n: 1 };
const VALUES = { PLANKS: 16, BAR: 16, ART: 896 };
const PRICES = { PLANKS: 100, BAR: 200, ART: 1000 };
const STEPS = [["RUNE", 384], ["SOUL", 384], ["RELIC", 384]];
const near = (a, b) => assert.ok(Math.abs(a - b) < 1e-6, `${a} != ${b}`);

test("retorno de recursos", () => {
  const r = (...a) => Math.round(K.returnRate(...a) * 1e4) / 1e4;
  assert.deepStrictEqual([r("craft", false, false), r("craft", true, false), r("craft", false, true),
    r("craft", true, true), r("refine", true, false), r("refine", true, true)],
  [0.1525, 0.2481, 0.4350, 0.4792, 0.3671, 0.5392]);
});

test("fabricación", () => {
  const c = K.craft(AXE, VALUES, PRICES, 6000, { rrr: 0.25, fee100: 500, quantity: 3 });
  assert.deepStrictEqual([c.gross, c.returned, c.itemValue, c.fee, c.unitCost, c.focus], [5200, 1300, 512, 288, 4188, 5145]);
  near(c.unitRevenue, 5610); near(c.unitProfit, 1422); near(c.totalProfit, 4266); near(c.profitPerFocus, 4266 / 5145);
  const b = K.craft({ m: AXE.m.concat([["ART", 1, 0]]), f: 100, n: 5 }, VALUES, PRICES, null, { rrr: 0.25 });
  assert.deepStrictEqual([b.gross, b.returned, b.unitCost, b.units, b.unitProfit], [6200, 1300, 980, 5, null]);
  assert.deepStrictEqual(K.craft(AXE, VALUES, { PLANKS: 100 }, null, {}).missing, ["BAR"]);
});

test("venta manual", () => {
  let t = K.trade(1000, 1500, 10);
  assert.deepStrictEqual([t.unitRevenue, t.unitProfit, t.totalProfit], [1440, 440, 4400]);
  near(t.breakeven, 1000 / 0.96);
  t = K.trade(1000, 1500, 1, { premium: false, buyOrder: true, sellOrder: true });
  near(t.unitCost, 1025); near(t.unitProfit, 1500 * (1 - 0.105) - 1025);
});

test("mejora de encantamiento", () => {
  let u = K.upgrade(STEPS, 0, 2, 10000, { RUNE: 10, SOUL: 50 }, 40000);
  assert.deepStrictEqual([u.upgradeCost, u.total, u.saving, u.worthIt], [23040, 33040, 6960, true]);
  u = K.upgrade(STEPS, 1, 2, 10000, {}, 40000);
  assert.deepStrictEqual([u.missing, u.worthIt], [["SOUL"], false]);
  assert.strictEqual(K.upgrade(STEPS, 0, 4, 1, {}, 1), null);
});
