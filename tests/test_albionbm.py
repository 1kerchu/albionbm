import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

import photon_builder as pb  # noqa: E402
from albionbm import calc, photon  # noqa: E402
from albionbm import api
from albionbm.api import chunk_ids, history_to_volumes, rows_to_prices  # noqa: E402
from albionbm.game import BLACK_MARKET, GameListener, order_books, parse_orders, resolve_location
from albionbm.export import build_report  # noqa: E402
from albionbm.items import Catalog, load_items  # noqa: E402
from albionbm.store import PriceStore  # noqa: E402


def order(item, price, kind="request", q=1, ench=0, loc=None, amount=1):
    return json.dumps({"Id": 1, "ItemTypeId": item, "ItemGroupTypeId": item.split("@")[0], "LocationId": loc,
                       "QualityLevel": q, "EnchantmentLevel": ench, "UnitPriceSilver": price * 10000,
                       "Amount": amount, "AuctionType": kind, "Expires": "2026-12-01T00:00:00"})


class Collector:
    def __init__(self):
        self.prices, self.status, self.books = [], [], []
        self.listener = GameListener(lambda s, l, p, b: (self.prices.append((s, l, p)), self.books.append(b)),
                                     lambda k, v: self.status.append((k, v)))


class PhotonTests(unittest.TestCase):
    def test_market_orders_in_debug_slot(self):
        c = Collector()
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(2, {8: "3003", 2: "Pepe"}))), "193.169.238.10")
        orders = [order("T4_BAG", 3000), order("T4_BAG", 3500), order("T5_MAIN_SWORD@1", 9000, ench=1, q=2)]
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(82, {}, debug_slot=orders))))
        self.assertIn(("server", "europe"), c.status)
        self.assertIn(("location", BLACK_MARKET), c.status)
        server, loc, prices = c.prices[-1]
        self.assertEqual(server, "europe")
        self.assertEqual(prices[("T4_BAG", 1, BLACK_MARKET, "request")], 3500)  # orden de compra más alta
        self.assertEqual(prices[("T5_MAIN_SWORD@1", 2, BLACK_MARKET, "request")], 9000)

    def test_market_orders_in_param_table(self):
        c = Collector()
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(2, {8: "1002", 2: "Pepe"}))))
        orders = [order("T4_BAG", 2000, "offer"), order("T4_BAG", 1800, "offer")]
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(81, {0: orders}))))
        _, loc, prices = c.prices[-1]
        self.assertEqual(loc, "Lymhurst")
        self.assertEqual(prices[("T4_BAG", 1, "Lymhurst", "offer")], 1800)  # venta más barata

    def test_fragmented_and_coalesced(self):
        c = Collector()
        orders = [order(f"T6_HEAD_PLATE_SET{i % 3 + 1}", 10000 + i, "offer", loc="4002") for i in range(60)]
        frags = pb.fragments(3, pb.response(81, {}, debug_slot=orders), size=300)
        self.assertGreater(len(frags), 3)
        # todos los fragmentos menos el último en un datagrama con varios paquetes Photon pegados
        payload = b"".join(pb.packet(f) for f in frags[:-1])
        c.listener.feed(payload)
        self.assertEqual(c.prices, [])
        c.listener.feed(pb.packet(frags[-1]))
        _, _, prices = c.prices[-1]
        self.assertEqual(prices[("T6_HEAD_PLATE_SET1", 1, "Fort Sterling", "offer")], 10000)

    def test_duplicate_packets_ignored(self):
        c = Collector()
        orders = [order("T4_BAG", 100 + i, "offer", loc="0007") for i in range(40)]
        frags = pb.fragments(3, pb.response(81, {}, debug_slot=orders), size=400)
        c.listener.feed(pb.packet(frags[0]))
        c.listener.feed(pb.packet(frags[0]))  # duplicado: no debe contar dos veces
        self.assertEqual(c.prices, [])
        for f in frags[1:]:
            c.listener.feed(pb.packet(f))
        self.assertEqual(len(c.prices), 1)
        self.assertEqual(c.prices[0][2][("T4_BAG", 1, "Thetford", "offer")], 100)

    def test_crc_packet(self):
        c = Collector()
        cmd = pb.reliable(3, pb.response(81, {}, debug_slot=[order("T4_BAG", 1, "offer", loc="0007")]))
        hdr = bytearray(pb.packet(cmd, flags=0xCC)[:12]) + b"\0\0\0\0" + cmd
        crc = photon.calculate_crc(bytes(hdr))
        hdr[12:16] = crc.to_bytes(4, "big")
        c.listener.feed(bytes(hdr))
        self.assertEqual(len(c.prices), 1)
        hdr[-3] ^= 0xFF  # corrompido -> descartado
        c.listener.feed(bytes(hdr))
        self.assertEqual(len(c.prices), 1)

    def test_encryption_detected_after_market_request(self):
        c = Collector()
        c.listener.feed(pb.packet(pb.reliable(2, pb.request(81, {1: "weapons"}))))
        c.listener.feed(pb.packet(pb.reliable(131, b"\x01\x02\x03")))
        self.assertTrue(c.listener.encrypted)
        self.assertEqual(c.status[-1][0], "encrypted")

    def test_garbage_does_not_crash(self):
        c = Collector()
        for data in [b"", b"\x00" * 5, os.urandom(200), pb.packet(pb.reliable(3, b"\x51\x00"))]:
            c.listener.feed(data)
        self.assertEqual(c.prices, [])

    def test_join_to_non_market_clears_location(self):
        c = Collector()
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(2, {8: "3005", 2: "Pepe"}))))
        self.assertEqual(c.listener.location, "Caerleon")
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(2, {8: "1234@RANDOMDUNGEON", 2: "Pepe"}))))
        self.assertIsNone(c.listener.location)


class DepthTests(unittest.TestCase):
    def test_order_books_aggregate(self):
        orders = parse_orders([order("T4_BAG", 100, "offer", amount=2), order("T4_BAG", 90, "offer", amount=1),
                               order("T4_BAG", 100, "offer", amount=3), order("T4_BAG", 500, "request", amount=4),
                               order("T4_BAG", 600, "request", amount=1)], "Lymhurst")
        books = order_books(orders)
        self.assertEqual(books[("T4_BAG", 1, "Lymhurst", "offer")], [[90, 1], [100, 5]])
        self.assertEqual(books[("T4_BAG", 1, "Lymhurst", "request")], [[600, 1], [500, 4]])

    def test_walk_books_stops_when_unprofitable(self):
        # MN paga 1000 (x2) y 500 (x10); ciudad vende a 400 (x1), 600 (x5), 900 (x10). Impuesto 4 %.
        units, invest, profit = calc.walk_books([[400, 1], [600, 5], [900, 10]], [[1000, 2], [500, 10]], 0.04)
        # 1 ud 400->960, 1 ud 600->960; luego 600 vs 480 ya no compensa
        self.assertEqual((units, invest, profit), (2, 1000, 920))
        self.assertEqual(calc.walk_books(None, [[1, 1]], 0.04), (None, None, None))

    def test_compute_with_depth_and_plan(self):
        now = time.time()
        entries = {
            ("A", 1, "Lymhurst", "offer"): (1000, now, "juego", [[1000, 10], [1500, 10]]),
            ("A", 1, BLACK_MARKET, "request"): (2000, now, "juego", [[2000, 15]]),
            ("B", 1, "Martlock", "offer"): (1000, now, "juego", [[1000, 100]]),
            ("B", 1, BLACK_MARKET, "request"): (1300, now, "juego", [[1300, 100]]),
            ("C", 1, "Thetford", "offer"): (100, now, "api", None),
            ("C", 1, BLACK_MARKET, "request"): (1000, now, "api", None),
        }
        opps = {o.item_id: o for o in calc.compute(entries, ["Lymhurst", "Martlock", "Thetford"], [1], now=now)}
        self.assertEqual((opps["A"].units, opps["A"].invest), (15, 17500))
        self.assertIsNone(opps["C"].units)
        lines, left = calc.plan(list(opps.values()), 50000, max_share=0.35)
        self.assertEqual([l.opp.item_id for l in lines], ["A", "B"])  # C sin cantidades no entra
        self.assertLessEqual(lines[0].invest, 50000 * 0.35)
        self.assertEqual(left, 50000 - sum(l.invest for l in lines))

    def test_report(self):
        now = time.time()
        entries = {("T4_BAG", 1, "Lymhurst", "offer"): (1000, now, "juego", [[1000, 5]]),
                   ("T4_BAG", 1, BLACK_MARKET, "request"): (2000, now, "juego", [[2000, 5]])}
        opps = calc.compute(entries, ["Lymhurst"], [1], now=now)
        text = build_report(opps, Catalog(load_items()), server="europe", premium=True, buy_mode="instant",
                            max_age_h=6, capital=25_000_000, location="Lymhurst", live_count=2, filters_text="x")
        self.assertIn("25.000.000", text)
        self.assertIn("`T4_BAG`", text)
        self.assertIn("Reparto automático", text)
        self.assertIn("| 5 | 5.000 |", text)  # unidades e inversión máx.
        self.assertIn("Mejores rutas", text)
        self.assertIn("Lymhurst → Black Market", text)


class VolumeTests(unittest.TestCase):
    def test_history_to_volumes(self):
        now = 1_800_000_000.0
        day = lambda d: time.strftime("%Y-%m-%dT00:00:00", time.gmtime(now - d * 86400))
        rows = [{"location": "Black Market", "item_id": "T4_BAG", "quality": 1,
                 "data": [{"item_count": 14, "timestamp": day(1)}, {"item_count": 7, "timestamp": day(3)},
                          {"item_count": 1000, "timestamp": day(30)}]}]  # fuera de la ventana de 7 días
        self.assertEqual(history_to_volumes(rows, now=now), {("T4_BAG", 1): 3.0})

    def test_estimated_units_from_volume(self):
        now = time.time()
        entries = {("A", 2, "Martlock", "offer"): (1000, now, "api", None),
                   ("A", 1, BLACK_MARKET, "request"): (2000, now, "api", None)}
        [o] = calc.compute(entries, ["Martlock"], [2], now=now, volumes={("A", 1): 3.0, ("A", 2): 2.5})
        self.assertTrue(o.estimated)
        self.assertEqual(o.daily_volume, 5.5)
        self.assertEqual((o.units, o.invest, o.total_profit), (5, 5000, 5 * 920))
        lines, _ = calc.plan([o], 1_000_000)
        self.assertEqual(lines[0].units, 5)

    def test_store_stats(self):
        with tempfile.TemporaryDirectory() as d:
            s = PriceStore(os.path.join(d, "p.db"))
            s.upsert_stats("europe", {("A", 1, "Lymhurst"): (4.5, 1200.0), ("A", 1, BLACK_MARKET): (2.0, None)})
            self.assertEqual(s.load_stats("europe"), {("A", 1, "Lymhurst"): (4.5, 1200.0),
                                                      ("A", 1, BLACK_MARKET): (2.0, None)})
            self.assertEqual(s.load_stats("west"), {})
            s.close()

    def test_history_to_stats_avg_price(self):
        now = 1_800_000_000.0
        day = lambda d: time.strftime("%Y-%m-%dT00:00:00", time.gmtime(now - d * 86400))
        rows = [{"location": "Martlock", "item_id": "X", "quality": 2,
                 "data": [{"item_count": 10, "avg_price": 100, "timestamp": day(1)},
                          {"item_count": 30, "avg_price": 200, "timestamp": day(2)}]}]
        self.assertEqual(api.history_to_stats(rows, now=now), {("X", 2, "Martlock"): (40 / 7, 175.0)})

    def test_ssl_context_verifies_with_certifi(self):
        import ssl
        ctx = api.ssl_context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertGreater(len(ctx.get_ca_certs()), 50)  # lista de autoridades cargada

    def test_fetch_uses_chunks_and_query(self):
        calls = []
        orig, orig_pause = api._get_json, api.PAUSE
        api._get_json, api.PAUSE = (lambda url: calls.append(url) or [{"item_id": "x"}]), 0
        try:
            rows = api.fetch_prices("europe", ["T4_BAG@1"] * 300, ["Lymhurst", BLACK_MARKET], [1, 2])
            hist = api.fetch_bm_history("west", ["T4_BAG"], [1])
        finally:
            api._get_json, api.PAUSE = orig, orig_pause
        self.assertEqual(len(rows), len(calls) - 1)
        self.assertGreater(len(calls), 2)
        self.assertTrue(calls[0].startswith("https://europe.albion-online-data.com/api/v2/stats/prices/T4_BAG%401,"))
        self.assertIn("locations=Lymhurst%2CBlack+Market", calls[0])
        self.assertIn("/stats/history/T4_BAG.json?locations=Black+Market&qualities=1&time-scale=24", calls[-1])
        self.assertEqual(hist, [{"item_id": "x"}])


class StrategyTests(unittest.TestCase):
    now = 1_800_000_000.0

    def e(self, price, book=None):
        return (price, self.now, "api", book)

    def test_city_instant_sells_to_other_city_buy_orders(self):
        entries = {("X", 1, "Lymhurst", "offer"): self.e(1000), ("X", 1, "Martlock", "request"): self.e(1500),
                   ("X", 1, "Lymhurst", "request"): self.e(5000),  # misma ciudad: no cuenta
                   ("X", 1, BLACK_MARKET, "request"): self.e(9000)}  # el MN no entra en esta estrategia
        opps = calc.compute(entries, ["Lymhurst", "Martlock"], [1], now=self.now, strategy="city_instant")
        self.assertEqual([(o.city, o.sell_city, o.profit) for o in opps], [("Lymhurst", "Martlock", 440)])

    def test_city_order_uses_lowest_offer_and_setup_fee(self):
        entries = {("X", 1, "Lymhurst", "offer"): self.e(1000), ("X", 1, "Martlock", "offer"): self.e(2000)}
        opps = calc.compute(entries, ["Lymhurst", "Martlock"], [1], now=self.now, strategy="city_order")
        good = [o for o in opps if o.profit > 0]
        self.assertEqual(len(good), 1)
        self.assertEqual((good[0].sell_city, good[0].revenue), ("Martlock", round(2000 * (1 - 0.04 - 0.025))))

    def test_suspicious_price_flagged_and_excluded_from_plan(self):
        entries = {("X", 1, "Lymhurst", "offer"): self.e(1000), ("X", 1, BLACK_MARKET, "request"): self.e(5000),
                   ("Y", 1, "Lymhurst", "offer"): self.e(1000), ("Y", 1, BLACK_MARKET, "request"): self.e(1500)}
        stats = {("X", 1, BLACK_MARKET): (10.0, 1200.0), ("Y", 1, BLACK_MARKET): (10.0, 1400.0)}
        opps = {o.item_id: o for o in calc.compute(entries, ["Lymhurst"], [1], now=self.now, stats=stats)}
        self.assertTrue(opps["X"].suspicious)
        self.assertFalse(opps["Y"].suspicious)
        self.assertEqual(opps["Y"].avg_price, 1400.0)
        lines, _ = calc.plan(list(opps.values()), 1_000_000)
        self.assertEqual([l.opp.item_id for l in lines], ["Y"])

    def test_profiles_and_weight(self):
        entries, stats = {}, {}
        for i, name in enumerate("ABCDEFGHIJ"):
            entries[(name, 1, "Lymhurst", "offer")] = self.e(1000)
            entries[(name, 1, BLACK_MARKET, "request")] = self.e(1500 + i * 10)
            stats[(name, 1, BLACK_MARKET)] = (100.0, 1500.0)
        opps = calc.compute(entries, ["Lymhurst"], [1], now=self.now, stats=stats)
        mx, _ = calc.plan(opps, 100_000, profile="max")
        safe, _ = calc.plan(opps, 100_000, profile="safe")
        self.assertEqual(len(mx), 2)                      # 50 % por objeto
        self.assertTrue(all(l.invest <= 12_000 for l in safe))
        self.assertTrue(all(l.units <= 30 for l in safe))  # 30 % del volumen diario
        self.assertGreater(len(safe), len(mx))
        heavy, _ = calc.plan(opps, 100_000, profile="max", max_weight=20, weight_of=lambda _i: 2.0)
        self.assertEqual(sum(l.units for l in heavy), 10)
        self.assertLessEqual(sum(l.weight for l in heavy), 20)
        old = [calc.Opportunity(**{**o.__dict__, "buy_age_h": 5.0}) for o in opps]
        self.assertEqual(calc.plan(old, 100_000, profile="safe")[0], [])  # datos de 5 h: no para «Seguro»

    def test_plan_routes(self):
        entries = {("A", 1, "Lymhurst", "offer"): self.e(1000, [[1000, 50]]),
                   ("A", 1, "Martlock", "request"): self.e(2000, [[2000, 50]]),
                   ("B", 1, "Thetford", "offer"): self.e(1000, [[1000, 50]]),
                   ("B", 1, "Martlock", "request"): self.e(1200, [[1200, 50]])}
        opps = calc.compute(entries, ["Lymhurst", "Martlock", "Thetford"], [1], now=self.now, strategy="city_instant")
        routes = calc.plan_routes(opps, 40_000)
        self.assertEqual([(r.buy_city, r.sell_city) for r in routes], [("Lymhurst", "Martlock"), ("Thetford", "Martlock")])
        self.assertEqual(routes[0].lines[0].units, 20)  # 50 % de 40.000 a 1.000 por unidad


class MovementTests(unittest.TestCase):
    def collector(self):
        c = Collector()
        self.moves = []
        c.listener.on_movement = self.moves.append
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(2, {8: "1002", 2: "Pepe"}))), "193.169.238.10")
        return c

    def order_json(self, oid, item, price, kind, amount=10):
        return json.dumps({"Id": oid, "ItemTypeId": item, "QualityLevel": 2, "EnchantmentLevel": 0,
                           "UnitPriceSilver": price * 10000, "Amount": amount, "AuctionType": kind, "LocationId": None})

    def test_direct_buy_recorded_when_server_confirms(self):
        c = self.collector()
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(81, {}, debug_slot=[self.order_json(900001, "T4_BAG", 1200, "offer")]))))
        c.listener.feed(pb.packet(pb.reliable(2, pb.request(83, {1: 3, 2: 900001}))))
        self.assertEqual(self.moves, [])                       # aún sin confirmar
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(83, {}))))
        [m] = self.moves
        self.assertEqual((m["kind"], m["item"], m["qty"], m["silver"], m["location"], m["server"]),
                         ("buy_direct", "T4_BAG", 3, 3600.0, "Lymhurst", "europe"))

    def test_failed_buy_and_unknown_order_are_ignored(self):
        c = self.collector()
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(81, {}, debug_slot=[self.order_json(900001, "T4_BAG", 1200, "offer")]))))
        c.listener.feed(pb.packet(pb.reliable(2, pb.request(83, {1: 3, 2: 900001}))))
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(83, {}, return_code=-1))))   # el servidor la rechaza
        c.listener.feed(pb.packet(pb.reliable(2, pb.request(83, {1: 3, 2: 555}))))        # id que no es de ninguna orden vista
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(83, {}))))
        self.assertEqual(self.moves, [])

    def test_quick_sell(self):
        c = self.collector()
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(82, {}, debug_slot=[self.order_json(900002, "T4_BAG", 2000, "request")]))))
        c.listener.feed(pb.packet(pb.reliable(2, pb.request(60, {4: 2, 1: 900002}))))
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(60, {}))))
        self.assertEqual([(m["kind"], m["qty"], m["silver"]) for m in self.moves], [("quick_sell", 2, 4000.0)])

    def test_mail_recorded_once_opened(self):
        c = self.collector()
        ticks = 621355968000000000 + 1_800_000_000 * 10_000_000
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(170, {
            3: pb.IntList([71, 72, 73]), 7: ["1002", "3003", "0007"], 12: pb.IntList([ticks, ticks, ticks]),
            11: ["MARKETPLACE_SELLORDER_FINISHED_SUMMARY", "MARKETPLACE_BUYORDER_FINISHED_SUMMARY", "GUILD_INVITE"]}))))
        self.assertEqual(self.moves, [])                       # la lista sola no trae el contenido
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(172, {0: 71, 1: "4|T5_BAG@1|800000000|200000000"}))))
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(172, {0: 72, 1: "10|T4_PLANKS|11000100000|1100010000"}))))
        c.listener.feed(pb.packet(pb.reliable(3, pb.response(172, {0: 73, 1: "hola|que|tal|"}))))   # no es de mercado
        self.assertEqual([(m["key"], m["kind"], m["item"], m["qty"], m["silver"], m["location"], m["ts"]) for m in self.moves],
                         [("mail:71", "sell_order", "T5_BAG@1", 4, 80000.0, "Lymhurst", 1_800_000_000.0),
                          ("mail:72", "buy_order", "T4_PLANKS", 10, 1100010.0, BLACK_MARKET, 1_800_000_000.0)])

    def test_parse_mail_formats(self):
        from albionbm.game import parse_mail
        self.assertEqual(parse_mail("MARKETPLACE_SELLORDER_EXPIRED_SUMMARY", "6|53|4420680000|T6_OFF_HORN_KEEPER@1|"),
                         {"kind": "sell_order", "item": "T6_OFF_HORN_KEEPER@1", "qty": 6, "silver": 442068.0})
        m = parse_mail("MARKETPLACE_BUYORDER_EXPIRED_SUMMARY", "23|100|65450000000|T5_ALCHEMY_RARE_PANTHER|")
        self.assertEqual((m["kind"], m["qty"]), ("buy_order", 23))
        self.assertAlmostEqual(m["silver"], 6545000 / 77 * 23)
        self.assertIsNone(parse_mail("MARKETPLACE_SELLORDER_EXPIRED_SUMMARY", "0|39|0|T7_JOURNAL_HUNTER_FULL|"))  # no se vendió nada
        self.assertIsNone(parse_mail("MARKETPLACE_SELLORDER_FINISHED_SUMMARY", "basura"))

    def test_realized_profit_uses_average_cost(self):
        from albionbm.movements import net_silver, profit_since, realize
        mv = lambda ts, kind, item, qty, silver: {"key": str(ts), "ts": ts, "kind": kind, "item": item, "qty": qty, "silver": silver}
        rows, s = realize([mv(1, "buy_direct", "A", 10, 10000), mv(2, "buy_order", "A", 10, 20000),
                           mv(3, "quick_sell", "A", 5, 10000), mv(4, "sell_order", "B", 1, 1000)], premium=True)
        self.assertAlmostEqual(rows[1]["net"], 20500)                       # +2,5 % por publicar la orden
        avg = (10000 + 20500) / 20
        self.assertAlmostEqual(rows[2]["profit"], 10000 * 0.96 - avg * 5)   # venta rápida: solo el 4 %
        self.assertIsNone(rows[3]["profit"])                                # de B no se vio la compra
        self.assertEqual(rows[3]["unknown"], 1)
        self.assertAlmostEqual(s["profit"], rows[2]["profit"])
        self.assertAlmostEqual(s["unknown_revenue"], 1000 * (1 - 0.04 - 0.025))
        self.assertEqual(s["stock_units"], 15)
        self.assertAlmostEqual(profit_since(rows, 3), rows[2]["profit"])
        self.assertAlmostEqual(net_silver("quick_sell", 1000, False), 920)

    def test_store_movements_deduplicate(self):
        with tempfile.TemporaryDirectory() as d:
            s = PriceStore(os.path.join(d, "p.db"))
            m = {"key": "mail:1", "server": "europe", "ts": 5.0, "kind": "sell_order", "item": "A", "qty": 2, "silver": 100.0, "location": "Lymhurst"}
            self.assertTrue(s.add_movement(m))
            self.assertFalse(s.add_movement(m))                # el mismo correo abierto otra vez
            self.assertEqual(len(s.load_movements("europe")), 1)
            s.delete_movement("mail:1")
            self.assertEqual(s.load_movements("europe"), [])
            s.close()


class LocationTests(unittest.TestCase):
    def test_ids(self):
        self.assertEqual(resolve_location("3003"), BLACK_MARKET)
        self.assertEqual(resolve_location("3005"), "Caerleon")
        self.assertEqual(resolve_location("3013-Auction2"), "Caerleon")
        self.assertEqual(resolve_location("0007"), "Thetford")
        self.assertEqual(resolve_location("5003"), "Brecilien")
        self.assertEqual(resolve_location("BLACKBANK-2004"), "Bridgewatch")
        self.assertEqual(resolve_location("4000-HellDen"), "Fort Sterling")
        self.assertIsNone(resolve_location("@ISLAND@0d7a8b0e-0000-0000-0000-000000000000"))
        self.assertIsNone(resolve_location(None))

    def test_parse_orders_enchant_suffix(self):
        o = parse_orders([order("T4_BAG", 100, ench=2)], "Martlock")
        self.assertEqual(o[0].item_id, "T4_BAG@2")
        self.assertEqual(o[0].price, 100)


class CalcTests(unittest.TestCase):
    now = 1_800_000_000.0

    def e(self, price, src="juego", age_h=1):
        return (price, self.now - age_h * 3600, src)

    def test_profit_premium_instant(self):
        entries = {("T4_BAG", 1, "Lymhurst", "offer"): self.e(1000),
                   ("T4_BAG", 1, BLACK_MARKET, "request"): self.e(2000, "api", 2)}
        [o] = calc.compute(entries, ["Lymhurst"], [1], now=self.now)
        self.assertEqual((o.revenue, o.profit), (1920, 920))
        self.assertAlmostEqual(o.percent, 92)
        self.assertEqual((o.buy_source, o.bm_source), ("juego", "api"))
        self.assertAlmostEqual(o.bm_age_h, 2)

    def test_no_premium_buy_order(self):
        entries = {("T4_BAG", 1, "Lymhurst", "request"): self.e(1000),
                   ("T4_BAG", 1, BLACK_MARKET, "request"): self.e(2000)}
        [o] = calc.compute(entries, ["Lymhurst"], [1], premium=False, buy_mode="order", now=self.now)
        self.assertEqual((o.buy_price, o.revenue, o.profit), (1025, 1840, 815))

    def test_higher_quality_sells_to_lower_order(self):
        entries = {("X", 3, "Martlock", "offer"): self.e(1000),
                   ("X", 1, BLACK_MARKET, "request"): self.e(3000),
                   ("X", 2, BLACK_MARKET, "request"): self.e(2500),
                   ("X", 4, BLACK_MARKET, "request"): self.e(9000)}
        [o] = calc.compute(entries, ["Martlock"], [3], now=self.now)
        self.assertEqual((o.bm_price, o.bm_quality), (3000, 1))

    def test_best_per_item(self):
        entries = {("X", 1, "Martlock", "offer"): self.e(1000), ("X", 1, "Thetford", "offer"): self.e(800),
                   ("X", 1, BLACK_MARKET, "request"): self.e(3000)}
        opps = calc.best_per_item(calc.compute(entries, ["Martlock", "Thetford"], [1], now=self.now))
        self.assertEqual([o.city for o in opps], ["Thetford"])


class StoreAndApiTests(unittest.TestCase):
    def test_store_keeps_newest(self):
        with tempfile.TemporaryDirectory() as d:
            s = PriceStore(os.path.join(d, "p.db"))
            k = ("T4_BAG", 1, "Lymhurst", "offer")
            now = time.time()
            s.upsert("europe", {k: 100}, ts=now, source="juego")
            s.upsert("europe", {k: 999}, source="api", timestamps={k: now - 3600})  # más antiguo: se ignora
            self.assertEqual(s.load("europe", 24)[k][:1], (100,))
            s.upsert("europe", {k: 110}, ts=now + 1, books={k: [[110, 3]]})
            self.assertEqual(s.load("europe", 24)[k][3], [[110, 3]])
            s.upsert("europe", {k: 120}, ts=now + 5)
            self.assertEqual(s.load("europe", 24)[k][0], 120)
            self.assertEqual(s.load("west", 24), {})
            s.close()

    def test_rows_to_prices(self):
        rows = [{"item_id": "T4_BAG", "city": "Black Market", "quality": 1, "sell_price_min": 0,
                 "sell_price_min_date": "0001-01-01T00:00:00", "buy_price_max": 5000,
                 "buy_price_max_date": "2026-01-01T10:00:00"},
                {"item_id": "T4_BAG", "city": "Lymhurst", "quality": 1, "sell_price_min": 3000,
                 "sell_price_min_date": "2026-01-01T11:00:00", "buy_price_max": 0,
                 "buy_price_max_date": "0001-01-01T00:00:00"}]
        prices, stamps = rows_to_prices(rows)
        self.assertEqual(prices, {("T4_BAG", 1, BLACK_MARKET, "request"): 5000,
                                  ("T4_BAG", 1, "Lymhurst", "offer"): 3000})
        self.assertEqual(len(stamps), 2)

    def test_chunks(self):
        ids = ["T4_MAIN_SWORD@1"] * 500
        chunks = chunk_ids(ids, 300)
        self.assertEqual(sum(map(len, chunks)), 500)
        self.assertTrue(all(len(",".join(c)) <= 300 for c in chunks))


class CatalogTests(unittest.TestCase):
    def test_catalog(self):
        c = Catalog(load_items())
        self.assertGreater(len(c.items), 1000)
        ids = c.variant_ids({"bags"}, {4}, {0, 1}, "")
        self.assertIn("T4_BAG", ids)
        self.assertIn("T4_BAG@1", ids)
        self.assertTrue(c.matches("T4_BAG@1", {"bags"}, {4}, {1}, "bolsa"))
        self.assertEqual(c.label("T6_BAG@3"), "T6.3")
        # Mercancías extra: el id completo ya lleva el encantamiento
        self.assertEqual(c.variant_ids({"resources"}, {4}, {0, 1}, "planks"), ["T4_PLANKS", "T4_PLANKS_LEVEL1@1"])
        self.assertTrue(c.matches("T4_PLANKS_LEVEL1@1", {"resources"}, {4}, {1}, ""))
        self.assertGreater(c.weight("T5_MOUNT_HORSE"), 0)


if __name__ == "__main__":
    unittest.main()
