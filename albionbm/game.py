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
        out.append(Order(item, int(o.get("QualityLevel") or 1), loc, kind, price, int(o.get("Amount") or 0)))
    return out


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


class GameListener:
    """Conecta el parser Photon con el estado del juego y avisa cuando llegan precios."""

    ENCRYPTION_WINDOW = 3.0

    def __init__(self, on_prices: Callable[[str, Optional[str], Dict[tuple, int]], None],
                 on_status: Optional[Callable[[str, str], None]] = None):
        self.on_prices = on_prices
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
            if orders:
                if self.encrypted:
                    self.encrypted = False
                    self.on_status("encrypted", "")
                self.on_prices(self.server or "", self.location, best_prices(orders))
            return

        # 2) Entrada a una zona (Join): parámetro 8 = ID de ubicación, 2 = nombre del personaje
        code = params.get(253, op_code)
        if isinstance(code, int) and code not in (OP_JOIN,) and ((code << 8) & 0xFFFF | (code >> 8)) == OP_JOIN:
            code = OP_JOIN
        loc_raw = params.get(8)
        if isinstance(loc_raw, str) and (code == OP_JOIN or isinstance(params.get(2), str)):
            loc = resolve_location(loc_raw)
            if code == OP_JOIN or loc:
                if loc != self.location:
                    self.location = loc
                    self.on_status("location", loc or "")
