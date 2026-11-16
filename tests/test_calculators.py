import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from albionbm import calculators as K  # noqa: E402

AXE = {"m": [["PLANKS", 12, 1], ["BAR", 20, 1]], "f": 1715, "n": 1}
VALUES = {"PLANKS": 16, "BAR": 16, "ART": 896}
PRICES = {"PLANKS": 100, "BAR": 200, "ART": 1000}
STEPS = [["RUNE", 384], ["SOUL", 384], ["RELIC", 384]]


class CalculatorTests(unittest.TestCase):
    def test_return_rates(self):
        r = lambda *a: round(K.return_rate(*a), 4)
        self.assertEqual([r("craft", False, False), r("craft", True, False), r("craft", False, True),
                          r("craft", True, True), r("refine", True, False), r("refine", True, True)],
                         [0.1525, 0.2481, 0.4350, 0.4792, 0.3671, 0.5392])

    def test_craft(self):
        c = K.craft(AXE, VALUES, PRICES, 6000, rrr=0.25, fee100=500, quantity=3)
        self.assertEqual((c["gross"], c["returned"], c["item_value"], c["fee"]), (5200, 1300, 512, 288))
        self.assertEqual(c["unit_cost"], 4188)
        self.assertAlmostEqual(c["unit_revenue"], 5610)
        self.assertAlmostEqual(c["unit_profit"], 1422)
        self.assertAlmostEqual(c["total_profit"], 4266)
        self.assertEqual(c["focus"], 5145)
        self.assertAlmostEqual(c["profit_per_focus"], 4266 / 5145)
        self.assertEqual(c["missing"], [])

    def test_craft_artifact_not_returned_and_batch(self):
        r = {"m": AXE["m"] + [["ART", 1, 0]], "f": 100, "n": 5}
        c = K.craft(r, VALUES, PRICES, None, rrr=0.25)
        self.assertEqual((c["gross"], c["returned"], c["unit_cost"], c["units"]), (6200, 1300, 980, 5))
        self.assertIsNone(c["unit_profit"])
        self.assertEqual(K.craft(AXE, VALUES, {"PLANKS": 100}, None, rrr=0)["missing"], ["BAR"])

    def test_trade(self):
        t = K.trade(1000, 1500, 10)
        self.assertEqual((t["unit_revenue"], t["unit_profit"], t["total_profit"]), (1440, 440, 4400))
        self.assertAlmostEqual(t["breakeven"], 1000 / 0.96)
        t = K.trade(1000, 1500, 1, premium=False, buy_order=True, sell_order=True)
        self.assertAlmostEqual(t["unit_cost"], 1025)
        self.assertAlmostEqual(t["unit_profit"], 1500 * (1 - 0.105) - 1025)

    def test_upgrade(self):
        u = K.upgrade(STEPS, 0, 2, 10000, {"RUNE": 10, "SOUL": 50}, 40000)
        self.assertEqual((u["upgrade_cost"], u["total"], u["saving"], u["worth_it"]), (23040, 33040, 6960, True))
        u = K.upgrade(STEPS, 1, 2, 10000, {}, 40000)
        self.assertEqual((u["missing"], u["worth_it"]), (["SOUL"], False))
        with self.assertRaises(ValueError):
            K.upgrade(STEPS, 0, 4, 1, {}, 1)

    def test_rank(self):
        recipes = {"AXE": AXE, "NOPRICE": AXE, "NOMAT": {"m": [["X", 1, 1]], "f": 1, "n": 1}}
        rows = K.rank(recipes, VALUES, ["AXE", "NOPRICE", "NOMAT", "UNKNOWN"], lambda m: PRICES.get(m, 0),
                      lambda i: {"AXE": 6000, "NOMAT": 50}.get(i, 0), rrr=0.25, fee100=500)
        self.assertEqual([r["id"] for r in rows], ["AXE"])
        self.assertAlmostEqual(rows[0]["unit_profit"], 1422)

    def test_history_series(self):
        import time
        from albionbm.api import history_series, week_summary
        now = 1_800_000_000.0
        day = lambda d: time.strftime("%Y-%m-%dT00:00:00", time.gmtime(now - d * 86400))
        rows = [{"location": "Martlock", "item_id": "X", "quality": 1, "data": [
                    {"item_count": 10, "avg_price": 100, "timestamp": day(1)}, {"item_count": 30, "avg_price": 200, "timestamp": day(2)},
                    {"item_count": 5, "avg_price": 999, "timestamp": day(40)}, {"item_count": 0, "avg_price": 50, "timestamp": day(3)}]},
                {"location": "Caerleon", "item_id": "X", "quality": 1, "data": [{"item_count": 7, "avg_price": 300, "timestamp": day(10)}]}]
        s = history_series(rows, now=now)
        self.assertEqual([x["city"] for x in s], ["Caerleon", "Martlock"])
        self.assertEqual(len(s[1]["points"]), 2)
        summ = {c: (last, avg, vol) for c, last, avg, vol in week_summary(s)}
        self.assertEqual(summ["Martlock"], (100, 175.0, 40 / 7))
        self.assertEqual(summ["Caerleon"], (300, None, 0))

    def test_buy_cost_walks_order_book(self):
        book = [[100, 5], [120, 5], [200, 10]]
        q = K.buy_cost(8, 100, book)
        self.assertEqual((q["total"], q["exact"], q["covered"]), (5 * 100 + 3 * 120, True, 8))
        q = K.buy_cost(25, 100, book, daily=None)          # faltan 5: al último precio, sin estimar subida
        self.assertEqual((q["total"], q["exact"], q["covered"], q["no_volume"]), (500 + 600 + 2000 + 5 * 200, False, 20, True))
        self.assertIsNone(K.buy_cost(3, None))

    def test_buy_cost_estimates_slippage_from_daily_volume(self):
        q = K.buy_cost(100, 1000, daily=100, slip=0.30)       # un día de ventas: media casi +15 %
        self.assertAlmostEqual(q["avg"], 1148.5)
        self.assertEqual(K.buy_cost(1, 1000, daily=100, slip=0.30)["avg"], 1000)  # la primera, al precio visto
        self.assertFalse(q["exact"])
        self.assertAlmostEqual(K.buy_cost(10, 1000, daily=100, slip=0.30)["avg"], 1013.5)
        self.assertAlmostEqual(K.buy_cost(10, 1000, daily=100, slip=0)["avg"], 1000)
        self.assertLessEqual(K.buy_cost(10**6, 1000, daily=10, slip=0.30)["avg"], 3000)  # tope ×3

    def test_buy_or_craft(self):
        flat = lambda price: (lambda n: K.buy_cost(n, price))
        mats = lambda m, n: K.buy_cost(n, PRICES.get(m))
        # Fabricar: (12×100 + 20×200) × 0,75 + 288 de tasa = 4.188 por unidad
        r = K.buy_or_craft(AXE, VALUES, 1, flat(4000), mats, rrr=0.25, fee100=500)
        self.assertEqual(r["verdict"], "buy")
        self.assertAlmostEqual(r["craft"]["unit_cost"], 4188)
        self.assertEqual(K.buy_or_craft(AXE, VALUES, 1, flat(5000), mats, rrr=0.25, fee100=500)["verdict"], "craft")
        # El objeto es barato de primeras pero sube rápido: a partir de cierta cantidad gana fabricar
        thin = lambda n: K.buy_cost(n, 4000, daily=20, slip=0.30)
        r = K.buy_or_craft(AXE, VALUES, 1, thin, mats, rrr=0.25, fee100=500)
        self.assertEqual((r["verdict"], r["switch_at"]), ("buy", 10))  # 4000×(1+0,3·(n−1)/40) > 4188 con n ≥ 8
        r = K.buy_or_craft(AXE, VALUES, 50, thin, mats, rrr=0.25, fee100=500)
        self.assertEqual(r["verdict"], "craft")
        self.assertAlmostEqual(r["saving"], (4000 * (1 + 0.3 * 49 / 40) - r["craft"]["unit_cost"]) * 50)
        # Sin precio de algún material no hay veredicto
        r = K.buy_or_craft(AXE, VALUES, 1, flat(4000), lambda m, n: None, rrr=0.25)
        self.assertEqual((r["verdict"], r["craft"]["missing"]), (None, ["PLANKS", "BAR"]))

    def test_craft_cost_buys_only_what_is_not_returned(self):
        c = K.craft_cost({"m": AXE["m"] + [["ART", 1, 0]], "f": 0, "n": 5}, VALUES, 12, lambda m, n: K.buy_cost(n, PRICES[m]), rrr=0.25)
        self.assertEqual((c["crafts"], c["units"]), (3, 15))
        self.assertEqual([(m["need"], m["buy"]) for m in c["materials"]], [(36, 27), (60, 45), (3, 3)])

    def test_recipes_file(self):
        d = K.load_recipes()
        self.assertEqual(d["recipes"]["T4_2H_AXE@2"]["m"], [["T4_PLANKS_LEVEL2@2", 12, 1], ["T4_METALBAR_LEVEL2@2", 20, 1]])
        self.assertEqual(d["recipes"]["T4_PLANKS"]["m"], [["T4_WOOD", 2, 1], ["T3_PLANKS", 1, 1]])
        self.assertEqual(d["upgrades"]["T4_2H_AXE"][0], ["T4_RUNE", 384])
        self.assertEqual(d["values"]["T4_PLANKS"], 16)


if __name__ == "__main__":
    unittest.main()
