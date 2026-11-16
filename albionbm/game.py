"""Interpreta los mensajes Photon del juego: ubicación del jugador, servidor y órdenes de mercado."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from .photon import PhotonParser

BLACK_MARKET = "Black Market"
CITIES = ["Caerleon", "Bridgewatch", "Martlock", "Lymhurst", "Fort Sterling", "Thetford", "Brecilien"]

# IDs de ubicación del juego -> mercado (fuente: ao-bin-dumps world.json y AFMDataClientCore)
LOCATION_IDS: Dict[int, str] = {
    7: "Thetford", 0: "Thetford", 6: "Thetford", 301: "Thetford",
    1002: "Lymhurst", 1000: "Lymhurst", 1001: "Lymhurst", 1301: "Lymhurst",
    2004: "Bridgewatch", 2000: "Bridgewatch", 2003: "Bridgewatch", 2301: "Bridgewatch",
    3008: "Martlock", 3004: "Martlock", 3007: "Martlock", 3301: "Martlock",
    4002: "Fort Sterling", 4000: "Fort Sterling", 4001: "Fort Sterling", 4301: "Fort Sterling",
    5003: "Brecilien", 5000: "Brecilien", 5001: "Brecilien", 5002: "Brecilien",
    3005: "Caerleon", 3013: "Caerleon", 3006: "Caerleon",
    3003: BLACK_MARKET,
}
HELLDEN = {"0000": "Thetford", "1000": "Lymhurst", "2000": "Bridgewatch", "3004": "Martlock",
           "3003": "Caerleon", "4000": "Fort Sterling", "5000": "Brecilien"}

# Rangos de IP de los servidores de juego (fuente: albiondata-client)
SERVER_IPS = {"5.188.125.": "west", "5.45.187.": "east", "193.169.238.": "europe"}

OP_JOIN = 2


def resolve_location(raw) -> Optional[str]:
    """Convierte un ID de ubicación del juego en el nombre del mercado, o None si no es un mercado conocido."""
    if raw is None:
        return None
    s = str(raw).strip().strip("\"'.,")
    if not s:
        return None
    if s.upper() in ("BLACK_MARKET", "BLACKMARKET"):
        return BLACK_MARKET
    for part in [s] + list(reversed(s.split("@"))):
        part = part.strip()
        if not part:
            continue
        p = re.sub(r"-Auction2$", "", part, flags=re.I)
        p = re.sub(r"^BLACKBANK-", "", p, flags=re.I)
        m = re.match(r"^(\d{4})-HellDen$", p, flags=re.I)
        if m:
            return HELLDEN.get(m.group(1))
        if re.fullmatch(r"\d{1,6}", p):
            return LOCATION_IDS.get(int(p))
    return None


def server_from_ip(ip: str) -> Optional[str]:
    for prefix, name in SERVER_IPS.items():
        if ip.startswith(prefix):
            return name
    return None


@dataclass
class Order:
    item_id: str        # con encantamiento, p. ej. T4_BAG@1
    quality: int
    location: str
    kind: str           # "offer" = orden de venta, "request" = orden de compra
    price: int          # plata por unidad
    amount: int
    order_id: int = 0   # identificador de la orden en el juego (para reconocer tus compras y ventas)


def parse_orders(strings: List[str], default_location: Optional[str]) -> List[Order]:
    """Convierte los JSON de órdenes de mercado del juego en objetos Order."""
    out: List[Order] = []
    for s in strings:
        try:
            o = json.loads(s)
        except (ValueError, TypeError):
            continue
        if not isinstance(o, dict) or "UnitPriceSilver" not in o or "ItemTypeId" not in o:
            continue
        loc = resolve_location(o.get("LocationId")) or default_location
        if not loc:
            continue
        item = str(o["ItemTypeId"])
        ench = int(o.get("EnchantmentLevel") or 0)
        if ench and "@" not in item:
            item = f"{item}@{ench}"
        kind = str(o.get("AuctionType", "")).lower()
        if kind not in ("offer", "request"):
            continue
        price = int(o["UnitPriceSilver"]) // 10000  # el juego usa céntimos de céntimo
        if price <= 0:
            continue
        try:
            oid = int(o.get("Id") or 0)
        except (TypeError, ValueError):
            oid = 0
        out.append(Order(item, int(o.get("QualityLevel") or 1), loc, kind, price, int(o.get("Amount") or 0), oid))
    return out


# ---------------------------------------------------------------------------- tus compras y ventas

MAIL_TYPES = {
    "MARKETPLACE_SELLORDER_FINISHED_SUMMARY": "sell_order",
    "MARKETPLACE_SELLORDER_EXPIRED_SUMMARY": "sell_order",
    "BLACKMARKET_SELLORDER_EXPIRED_SUMMARY": "sell_order",
    "MARKETPLACE_BUYORDER_FINISHED_SUMMARY": "buy_order",
    "MARKETPLACE_BUYORDER_EXPIRED_SUMMARY": "buy_order",
}
DOTNET_EPOCH_TICKS = 621355968000000000  # ticks de .NET (100 ns desde el año 1) hasta 1970


def parse_mail(mail_type: str, body: str) -> Optional[dict]:
    """Correo de mercado -> {"kind", "item", "qty", "silver"} (plata bruta total), o None si no hubo movimiento.

    Formatos (fuente: AlbionDataAvalonia), con la plata multiplicada por 10.000:
      SELLORDER_FINISHED  CANTIDAD|OBJETO|PLATA_TOTAL|PLATA_UNIDAD
      BUYORDER_FINISHED   CANTIDAD|OBJETO|PLATA_TOTAL|PLATA_UNIDAD
      SELLORDER_EXPIRED   VENDIDAS|TOTAL|PLATA_TOTAL|OBJETO      (también el del Mercado Negro)
      BUYORDER_EXPIRED    COMPRADAS|TOTAL|PLATA_DEVUELTA|OBJETO
    """
    kind = MAIL_TYPES.get(mail_type)
    parts = body.split("|")
    try:
        if kind is None or len(parts) < 4:
            return None
        if mail_type.endswith("FINISHED_SUMMARY"):
            qty, item, silver = int(parts[0]), parts[1], int(parts[2]) / 10000
        elif mail_type == "MARKETPLACE_BUYORDER_EXPIRED_SUMMARY":
            qty, total, refund, item = int(parts[0]), int(parts[1]), int(parts[2]) / 10000, parts[3]
            # No dice lo pagado: se deduce del precio límite (plata devuelta / unidades sin comprar)
            silver = refund / (total - qty) * qty if total > qty else 0.0
        else:
            qty, item, silver = int(parts[0]), parts[3], int(parts[2]) / 10000
    except (ValueError, ZeroDivisionError):
        return None
    if qty <= 0 or not item or silver <= 0:
        return None
    return {"kind": kind, "item": item, "qty": qty, "silver": silver}


def best_prices(orders: List[Order]) -> Dict[tuple, int]:
    """Mejor precio por (objeto, calidad, ubicación, tipo): venta más barata y compra más cara."""
    best: Dict[tuple, int] = {}
    for o in orders:
        k = (o.item_id, o.quality, o.location, o.kind)
        if k not in best:
            best[k] = o.price
        elif o.kind == "offer":
            best[k] = min(best[k], o.price)
        else:
            best[k] = max(best[k], o.price)
    return best


BOOK_LEVELS = 15


def order_books(orders: List[Order]) -> Dict[tuple, List[List[int]]]:
    """Profundidad por (objeto, calidad, ubicación, tipo): [[precio, cantidad], ...] del mejor al peor."""
    agg: Dict[tuple, Dict[int, int]] = {}
    for o in orders:
        lv = agg.setdefault((o.item_id, o.quality, o.location, o.kind), {})
        lv[o.price] = lv.get(o.price, 0) + max(o.amount, 0)
    out = {}
    for k, lv in agg.items():
        levels = sorted(lv.items(), reverse=(k[3] == "request"))
        out[k] = [[p, a] for p, a in levels[:BOOK_LEVELS]]
    return out


class GameListener:
    """Conecta el parser Photon con el estado del juego y avisa cuando llegan precios."""

    ENCRYPTION_WINDOW = 3.0

    def __init__(self, on_prices: Callable[[str, Optional[str], Dict[tuple, int], Dict[tuple, list]], None],
                 on_status: Optional[Callable[[str, str], None]] = None,
                 on_movement: Optional[Callable[[dict], None]] = None):
        self.on_prices = on_prices
        self.on_movement = on_movement or (lambda movement: None)
        self._orders: "OrderedDict[int, Order]" = OrderedDict()  # órdenes vistas, por id
        self._pending: Dict[int, tuple] = {}                     # código de operación -> (movimiento, hora)
        self._mails: Dict[int, tuple] = {}                       # id de correo -> (tipo, ubicación, fecha)
        self.on_status = on_status or (lambda kind, msg: None)
        self.location: Optional[str] = None
        self.server: Optional[str] = None
        self.encrypted = False
        self._last_market_request = 0.0
        self._lock = threading.Lock()
        self._recent: "OrderedDict[bytes, float]" = OrderedDict()
        self.parser = PhotonParser(self._on_request, self._on_response, None, self._on_encrypted)

    # Llamado por el capturador con cada paquete del puerto 5056
    def feed(self, payload: bytes, src_ip: Optional[str] = None) -> None:
        if src_ip:
            srv = server_from_ip(src_ip)
            if srv and srv != self.server:
                self.server = srv
                self.on_status("server", srv)
        with self._lock:
            # El mismo paquete puede capturarse en varias interfaces (VPN, ExitLag...) o retransmitirse:
            # procesarlo dos veces corrompería los mensajes fragmentados.
            now = time.time()
            h = hashlib.blake2b(payload, digest_size=12).digest()
            if h in self._recent and now - self._recent[h] < 5:
                return
            self._recent[h] = now
            self._recent.move_to_end(h)
            while len(self._recent) > 4096:
                self._recent.popitem(last=False)
            self.parser.receive_packet(payload)

    def _on_request(self, op_code: int, params: dict) -> None:
        # Cualquier petición con listas de IDs de objeto suele ser una consulta de mercado.
        self._last_market_request = time.time()
        self._detect_trade(params.get(253, op_code), params)

    def _detect_trade(self, code, params: dict) -> None:
        """Compra directa (parámetros 1 = cantidad, 2 = id de orden de venta) o venta rápida
        (4 = cantidad, 1 = id de orden de compra). Se reconoce porque el id es de una orden que acabas de
        ver en el mercado, así no depende de los códigos de operación. Queda pendiente hasta que el
        servidor confirma."""
        is_int = lambda v: isinstance(v, int) and not isinstance(v, bool)
        for kind, amount_key, order_key, order_kind in (("buy_direct", 1, 2, "offer"), ("quick_sell", 4, 1, "request")):
            amount, oid = params.get(amount_key), params.get(order_key)
            order = self._orders.get(oid) if is_int(oid) else None
            if order and order.kind == order_kind and is_int(amount) and amount > 0:
                now = time.time()
                self._pending[code] = ({
                    "key": f"trade:{oid}:{amount}:{int(now)}", "ts": now, "kind": kind, "item": order.item_id,
                    "quality": order.quality, "qty": amount, "silver": float(order.price * amount),
                    "location": order.location}, now)
                return

    def _on_encrypted(self) -> None:
        if not self.encrypted and time.time() - self._last_market_request < self.ENCRYPTION_WINDOW:
            self.encrypted = True
            self.on_status("encrypted", "El juego está cifrando los datos de mercado: se usarán precios de la API.")

    def _on_response(self, op_code: int, return_code: int, debug: str, params: dict) -> None:
        # 1) Órdenes de mercado: lista de JSON en el parámetro 0 (se detecta por contenido,
        #    así no depende de los códigos de operación, que cambian con los parches).
        data = params.get(0)
        if isinstance(data, list) and data and all(isinstance(x, str) for x in data) and "UnitPriceSilver" in data[0]:
            orders = parse_orders(data, self.location)
            for o in orders:
                if o.order_id:
                    self._orders[o.order_id] = o
                    self._orders.move_to_end(o.order_id)
            while len(self._orders) > 20000:
                self._orders.popitem(last=False)
            if orders:
                if self.encrypted:
                    self.encrypted = False
                    self.on_status("encrypted", "")
                self.on_prices(self.server or "", self.location, best_prices(orders), order_books(orders))
            return

        code = params.get(253, op_code)

        # 2) Confirmación de una compra directa o venta rápida pendiente
        pending = self._pending.pop(code, None) if isinstance(code, int) else None
        if pending and time.time() - pending[1] < 10 and return_code == 0:
            self.on_movement(dict(pending[0], server=self.server or ""))
            return

        # 3) Correos del mercado: primero llega la lista (ids, tipos, ubicaciones) y, al abrir uno, su contenido
        if self._mail_list(params) or self._mail_body(params):
            return

        # 4) Entrada a una zona (Join): parámetro 8 = ID de ubicación, 2 = nombre del personaje
        if isinstance(code, int) and code not in (OP_JOIN,) and ((code << 8) & 0xFFFF | (code >> 8)) == OP_JOIN:
            code = OP_JOIN
        loc_raw = params.get(8)
        if isinstance(loc_raw, str) and (code == OP_JOIN or isinstance(params.get(2), str)):
            loc = resolve_location(loc_raw)
            if code == OP_JOIN or loc:
                if loc != self.location:
                    self.location = loc
                    self.on_status("location", loc or "")

    def _mail_list(self, params: dict) -> bool:
        str_lists = [v for v in params.values() if isinstance(v, list) and v and all(isinstance(x, str) for x in v)]
        types = next((v for v in str_lists if any(x in MAIL_TYPES for x in v)), None)
        ids = params.get(3)
        if types is None or not isinstance(ids, list) or len(ids) != len(types):
            return False
        locs = next((v for v in str_lists if v is not types and len(v) == len(types)), [None] * len(types))
        ticks = next((v for v in params.values() if isinstance(v, list) and len(v) == len(types) and v
                      and all(isinstance(x, int) and x > DOTNET_EPOCH_TICKS for x in v)), None)
        for i, mail_id in enumerate(ids):
            if types[i] in MAIL_TYPES and isinstance(mail_id, int):
                ts = (ticks[i] - DOTNET_EPOCH_TICKS) / 1e7 if ticks else None
                self._mails[mail_id] = (types[i], resolve_location(locs[i]), ts)
        return True

    def _mail_body(self, params: dict) -> bool:
        mail_id, body = params.get(0), params.get(1)
        info = self._mails.get(mail_id) if isinstance(mail_id, int) and not isinstance(mail_id, bool) else None
        if info is None or not isinstance(body, str):
            return False
        mail_type, location, ts = info
        m = parse_mail(mail_type, body)
        if m:
            self.on_movement(dict(m, key=f"mail:{mail_id}", ts=ts or time.time(), quality=0, location=location or "",
                                  server=self.server or ""))
        return True
