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

test("comprar o fabricar: subida de precio", () => {
  const book = [[100, 5], [120, 5], [200, 10]];
  let q = K.buyCost(8, 100, book);
  assert.deepStrictEqual([q.total, q.exact, q.covered], [860, true, 8]);
  q = K.buyCost(25, 100, book, null);
  assert.deepStrictEqual([q.total, q.exact, q.covered, q.noVolume], [4100, false, 20, true]);
  assert.strictEqual(K.buyCost(3, null), null);
  near(K.buyCost(100, 1000, null, 100, 0.30).avg, 1148.5);
  assert.strictEqual(K.buyCost(1, 1000, null, 100, 0.30).avg, 1000);
  near(K.buyCost(10, 1000, null, 100, 0.30).avg, 1013.5);
  assert.ok(K.buyCost(1e6, 1000, null, 10, 0.30).avg <= 3000);
});

test("comprar o fabricar: veredicto y cambio", () => {
  const flat = (price) => (n) => K.buyCost(n, price);
  const mats = (m, n) => K.buyCost(n, PRICES[m]);
  const o = { rrr: 0.25, fee100: 500 };
  let r = K.buyOrCraft(AXE, VALUES, 1, flat(4000), mats, o);
  assert.strictEqual(r.verdict, "buy"); near(r.craft.unitCost, 4188);
  assert.strictEqual(K.buyOrCraft(AXE, VALUES, 1, flat(5000), mats, o).verdict, "craft");
  const thin = (n) => K.buyCost(n, 4000, null, 20, 0.30);
  r = K.buyOrCraft(AXE, VALUES, 1, thin, mats, o);
  assert.deepStrictEqual([r.verdict, r.switchAt], ["buy", 10]);
  r = K.buyOrCraft(AXE, VALUES, 50, thin, mats, o);
  assert.strictEqual(r.verdict, "craft"); near(r.saving, (4000 * (1 + 0.3 * 49 / 40) - r.craft.unitCost) * 50);
  r = K.buyOrCraft(AXE, VALUES, 1, flat(4000), () => null, { rrr: 0.25 });
  assert.deepStrictEqual([r.verdict, r.craft.missing], [null, ["PLANKS", "BAR"]]);
  const c = K.craftCost({ m: AXE.m.concat([["ART", 1, 0]]), f: 0, n: 5 }, VALUES, 12, (m, n) => K.buyCost(n, PRICES[m]), { rrr: 0.25 });
  assert.deepStrictEqual([c.crafts, c.units, c.materials.map((m) => [m.need, m.buy])], [3, 15, [[36, 27], [60, 45], [3, 3]]]);
});
