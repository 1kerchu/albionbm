const test = require("node:test");
const assert = require("node:assert");
const C = require("../js/calc.js");

const now = Date.parse("2026-01-01T12:00:00Z");
const recent = "2026-01-01T11:00:00";
const old = "2025-12-30T00:00:00";
const row = (item_id, city, quality, o) => Object.assign({ item_id, city, quality,
  sell_price_min: 0, sell_price_min_date: "0001-01-01T00:00:00", buy_price_max: 0, buy_price_max_date: "0001-01-01T00:00:00" }, o);

test("beneficio con prémium y compra directa", () => {
  const rows = [
    row("T4_BAG", "Lymhurst", 1, { sell_price_min: 1000, sell_price_min_date: recent }),
    row("T4_BAG", "Black Market", 1, { buy_price_max: 2000, buy_price_max_date: recent }),
  ];
  const [r] = C.computeOpportunities(rows, { now, cities: ["Lymhurst"], qualities: [1] });
  assert.strictEqual(r.revenue, 1920);
  assert.strictEqual(r.profit, 920);
  assert.ok(Math.abs(r.percent - 92) < 1e-9);
});

test("sin prémium 8 % y orden de compra con 2,5 %", () => {
  const rows = [
    row("T4_BAG", "Lymhurst", 1, { buy_price_max: 1000, buy_price_max_date: recent }),
    row("T4_BAG", "Black Market", 1, { buy_price_max: 2000, buy_price_max_date: recent }),
  ];
  const [r] = C.computeOpportunities(rows, { now, premium: false, buyMode: "order", cities: ["Lymhurst"], qualities: [1] });
  assert.strictEqual(r.buyPrice, 1025);
  assert.strictEqual(r.revenue, 1840);
  assert.strictEqual(r.profit, 815);
});

test("una calidad superior puede venderse a la mejor orden de calidad inferior", () => {
  const rows = [
    row("T5_SWORD", "Martlock", 3, { sell_price_min: 1000, sell_price_min_date: recent }),
    row("T5_SWORD", "Black Market", 1, { buy_price_max: 3000, buy_price_max_date: recent }),
    row("T5_SWORD", "Black Market", 2, { buy_price_max: 2500, buy_price_max_date: recent }),
    row("T5_SWORD", "Black Market", 4, { buy_price_max: 9000, buy_price_max_date: recent }),
  ];
  const [r] = C.computeOpportunities(rows, { now, cities: ["Martlock"], qualities: [3] });
  assert.strictEqual(r.bmPrice, 3000);
  assert.strictEqual(r.bmQuality, 1);
});

test("descarta datos antiguos o sin precio", () => {
  const rows = [
    row("T4_BAG", "Lymhurst", 1, { sell_price_min: 1000, sell_price_min_date: old }),
    row("T4_BAG", "Thetford", 1, { sell_price_min: 0, sell_price_min_date: recent }),
    row("T4_BAG", "Black Market", 1, { buy_price_max: 2000, buy_price_max_date: recent }),
  ];
  assert.deepStrictEqual(C.computeOpportunities(rows, { now, maxAgeHours: 6, cities: ["Lymhurst", "Thetford"], qualities: [1] }), []);
});

test("chunkIds respeta el límite", () => {
  const ids = Array.from({ length: 500 }, (_, i) => "T4_MAIN_SWORD@" + (i % 4));
  const chunks = C.chunkIds(ids, 300);
  assert.strictEqual(chunks.flat().length, 500);
  for (const c of chunks) assert.ok(c.join(",").length <= 300);
});
