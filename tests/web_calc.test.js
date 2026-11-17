// Comprueba que el cálculo de la versión web coincide con el de la app (tests/test_albionbm.py).
const test = require("node:test");
const assert = require("node:assert");
const C = require("../web/calc.js");

const now = 1_800_000_000;
const E = (obj) => new Map(Object.entries(obj).map(([k, p]) => [k, { p, ts: now, src: "api" }]));
const base = { cities: ["Lymhurst", "Martlock"], qualities: [1, 2, 3], premium: true, now };

test("ciudad → Mercado Negro con prémium", () => {
  const [o] = C.compute(E({ "X|1|Lymhurst|offer": 1000, "X|1|Black Market|request": 2000 }), null, { ...base, qualities: [1] });
  assert.deepStrictEqual([o.revenue, o.profit, o.sellCity], [1920, 920, "Black Market"]);
});

test("calidad superior vende a la mejor orden inferior", () => {
  const e = E({ "X|3|Martlock|offer": 1000, "X|1|Black Market|request": 3000, "X|2|Black Market|request": 2500, "X|4|Black Market|request": 9000 });
  const [o] = C.compute(e, null, { ...base, qualities: [3] });
  assert.deepStrictEqual([o.sellPrice, o.sellQuality], [3000, 1]);
});

test("entre ciudades: venta rápida y orden de venta", () => {
  const e = E({ "X|1|Lymhurst|offer": 1000, "X|1|Martlock|request": 1500, "X|1|Martlock|offer": 2000, "X|1|Black Market|request": 9000 });
  const fast = C.compute(e, null, { ...base, qualities: [1], strategy: "city_instant" });
  assert.deepStrictEqual(fast.map((o) => [o.city, o.sellCity, o.profit]), [["Lymhurst", "Martlock", 440]]);
  const order = C.compute(e, null, { ...base, qualities: [1], strategy: "city_order" }).filter((o) => o.profit > 0);
  assert.deepStrictEqual([order[0].sellCity, order[0].revenue], ["Martlock", Math.round(2000 * (1 - 0.04 - 0.025))]);
});

test("sospechosos, estimación por volumen y plan", () => {
  const e = E({ "X|1|Lymhurst|offer": 1000, "X|1|Black Market|request": 5000, "Y|1|Lymhurst|offer": 1000, "Y|1|Black Market|request": 1500 });
  const stats = new Map([["X|1|Black Market", { daily: 10, avg: 1200 }], ["Y|1|Black Market", { daily: 10, avg: 1400 }]]);
  const opps = C.compute(e, stats, { ...base, qualities: [1] });
  const by = Object.fromEntries(opps.map((o) => [o.itemId, o]));
  assert.ok(by.X.suspicious && !by.Y.suspicious);
  assert.deepStrictEqual([by.Y.units, by.Y.invest, by.Y.totalProfit], [10, 10000, 4400]);
  const { lines, left } = C.plan(opps, 1_000_000, { profile: "max" });
  assert.deepStrictEqual(lines.map((l) => [l.opp.itemId, l.units]), [["Y", 10]]);
  assert.strictEqual(left, 990000);
  const heavy = C.plan(opps, 1_000_000, { profile: "max", maxWeight: 6, weightOf: () => 2 });
  assert.strictEqual(heavy.lines[0].units, 3);
});

test("historial y precios de la API", () => {
  const day = (d) => new Date((now - d * 86400) * 1000).toISOString().slice(0, 19);
  const stats = new Map();
  C.mergeHistory(stats, [{ location: "Martlock", item_id: "X", quality: 2, data: [
    { item_count: 10, avg_price: 100, timestamp: day(1) }, { item_count: 30, avg_price: 200, timestamp: day(2) },
    { item_count: 999, avg_price: 1, timestamp: day(30) }] }], now);
  assert.deepStrictEqual(stats.get("X|2|Martlock"), { daily: 40 / 7, avg: 175 });
  const entries = new Map();
  C.mergePrices(entries, [{ item_id: "X", city: "Black Market", quality: 1, sell_price_min: 0, sell_price_min_date: "0001-01-01T00:00:00",
    buy_price_max: 5000, buy_price_max_date: "2026-01-01T10:00:00" }]);
  assert.deepStrictEqual([...entries.keys()], ["X|1|Black Market|request"]);
});

test("riesgo del transporte y dónde vender", () => {
  assert.strictEqual(C.routeRisky("Caerleon", "Black Market"), false);
  assert.strictEqual(C.routeRisky("Lymhurst", "Black Market"), true);
  assert.strictEqual(C.routeRisky("Lymhurst", "Martlock"), false);
  const e = E({ "A|1|Lymhurst|offer": 1000, "A|1|Black Market|request": 1600, "B|1|Caerleon|offer": 1000, "B|1|Black Market|request": 1300 });
  const stats = new Map([["A|1|Black Market", { daily: 100, avg: 1600 }], ["B|1|Black Market", { daily: 100, avg: 1300 }]]);
  const opps = C.compute(e, stats, { cities: ["Lymhurst", "Caerleon"], qualities: [1], premium: true, now });
  assert.strictEqual(C.plan(opps, 50000, { profile: "max" }).lines[0].opp.itemId, "A");
  const risky = C.plan(opps, 50000, { profile: "max", risk: 0.4 }).lines;
  assert.deepStrictEqual(risky.map((l) => [l.opp.itemId, l.risky, l.expected === l.profit]), [["B", false, true]]);
  const some = C.plan(opps, 50000, { profile: "max", risk: 0.05, maxRisk: 10000 }).lines.find((l) => l.opp.itemId === "A");
  assert.ok(some.invest <= 10000 && some.risky);
  assert.deepStrictEqual(C.planRoutes(opps, 50000, { risk: 0.4 }).map((r) => [r.buyCity, r.sellCity, r.risky]), [["Caerleon", "Black Market", false]]);
  const s = E({ "X|1|Lymhurst|request": 900, "X|3|Lymhurst|request": 5000, "X|2|Martlock|offer": 1200, "X|1|Black Market|request": 1100, "X|2|Black Market|offer": 99999 });
  assert.deepStrictEqual(C.sellingPlaces("X", 2, s, ["Lymhurst", "Martlock", "Black Market"], true).map((x) => [x.location, x.mode, x.price]),
    [["Martlock", "order", 1200], ["Black Market", "quick", 1100], ["Lymhurst", "quick", 900]]);
});
