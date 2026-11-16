"""Cálculo de oportunidades de comercio y planificación de la inversión.

Estrategias:
  - "bm":           comprar en una ciudad y vender a las órdenes de compra del Mercado Negro.
  - "city_instant": comprar en una ciudad y vender al momento a las órdenes de compra de otra ciudad.
  - "city_order":   comprar en una ciudad y poner una orden de venta en otra (más margen, más lento).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .game import BLACK_MARKET

SETUP_FEE = 0.025      # tasa por publicar una orden
TAX_PREMIUM = 0.04     # impuesto de venta con prémium
TAX_NO_PREMIUM = 0.08  # impuesto de venta sin prémium
SUSPICIOUS_FACTOR = 1.6  # precio de venta > 1,6 × media de 7 días => sospechoso

QUALITY_NAMES = {1: "Normal", 2: "Buena", 3: "Notable", 4: "Sobresaliente", 5: "Obra maestra"}
STRATEGIES = {
    "bm": "Ciudad → Mercado Negro",
    "city_instant": "Entre ciudades · venta rápida",
    "city_order": "Entre ciudades · orden de venta",
}


@dataclass
class Opportunity:
    item_id: str
    quality: int
    city: str            # dónde se compra
    bm_quality: int      # calidad de la orden a la que se vende
    buy_price: int
    bm_price: int        # precio de venta (orden de compra del destino, u orden de venta propia)
    revenue: int         # lo que se recibe tras impuestos y tasas
    profit: int
    percent: float
    buy_age_h: float
    bm_age_h: float
    buy_source: str
    bm_source: str
    # Según la profundidad de órdenes leída del juego (None si no se conoce, p. ej. datos de la API):
    units: Optional[int] = None         # unidades que se pueden comprar y vender con beneficio
    invest: Optional[int] = None        # plata necesaria para comprarlas todas
    total_profit: Optional[int] = None  # beneficio total vendiéndolas
    daily_volume: Optional[float] = None  # unidades vendidas al día en el destino (historial de la API)
    estimated: bool = False             # True si units/invest/total salen del volumen diario y no del juego
    sell_city: str = BLACK_MARKET       # dónde se vende
    avg_price: Optional[float] = None   # precio medio de 7 días en el destino (historial de la API)
    suspicious: bool = False            # precio de venta muy por encima de la media: probable dato viejo o trampa


def walk_books(buy_book: Optional[list], bm_book: Optional[list], tax: float):
    """Cruza las órdenes de venta del origen (más baratas primero) con las de compra del destino
    (más caras primero) y devuelve (unidades, inversión, beneficio) mientras haya beneficio."""
    if not buy_book or not bm_book:
        return None, None, None
    buy = [list(x) for x in buy_book if x[1] > 0]
    bm = [list(x) for x in bm_book if x[1] > 0]
    units = invest = profit = 0.0
    i = j = 0
    while i < len(buy) and j < len(bm):
        cost, rev = buy[i][0], bm[j][0] * (1 - tax)
        if rev <= cost:
            break
        n = min(buy[i][1], bm[j][1])
        units += n
        invest += n * cost
        profit += n * (rev - cost)
        buy[i][1] -= n
        bm[j][1] -= n
        if buy[i][1] == 0:
            i += 1
        if bm[j][1] == 0:
            j += 1
    return int(units), round(invest), round(profit)


def compute(entries: Dict[Tuple[str, int, str, str], tuple],
            cities: Iterable[str], qualities: Iterable[int], premium: bool = True,
            buy_mode: str = "instant", now: Optional[float] = None,
            volumes: Optional[Dict[Tuple[str, int], float]] = None,
            strategy: str = "bm", sell_cities: Optional[Iterable[str]] = None,
            stats: Optional[Dict[Tuple[str, int, str], Tuple[float, Optional[float]]]] = None) -> List[Opportunity]:
    """
    entries: {(item, calidad, ubicación, "offer"|"request"): (precio, timestamp, origen[, profundidad])}
    stats:   {(item, calidad, ubicación): (unidades vendidas al día, precio medio 7 días)}
    volumes: forma antigua de pasar solo el volumen del Mercado Negro: {(item, calidad): unidades/día}

    Reglas del juego:
    - Una orden de compra de calidad Q acepta objetos de calidad >= Q.
    - Vender paga impuesto de venta (4 % prémium, 8 % sin). Publicar una orden paga además un 2,5 %.
    """
    now = now or time.time()
    tax = TAX_PREMIUM if premium else TAX_NO_PREMIUM
    cities = list(cities)
    qualities = list(qualities)
    sell_locs = [BLACK_MARKET] if strategy == "bm" else list(sell_cities if sell_cities is not None else cities)
    stats = dict(stats or {})
    for (item, q), v in (volumes or {}).items():
        stats.setdefault((item, q, BLACK_MARKET), (v, None))

    by_item: Dict[str, Dict[Tuple[int, str, str], tuple]] = {}
    for (item, q, loc, kind), val in entries.items():
        by_item.setdefault(item, {})[(q, loc, kind)] = val

    buy_kind = "request" if buy_mode == "order" else "offer"
    result: List[Opportunity] = []
    for item, d in by_item.items():
        for city in cities:
            for q in qualities:
                c = d.get((q, city, buy_kind))
                if not c or c[0] <= 0:
                    continue
                cost = c[0] * (1 + SETUP_FEE) if buy_mode == "order" else float(c[0])
                for sell in sell_locs:
                    if sell == city:
                        continue
                    if strategy == "city_order":
                        b = d.get((q, sell, "offer"))
                        if not b:
                            continue
                        bq, levels = q, None
                        revenue = b[0] * (1 - tax - SETUP_FEE)
                        st = [stats.get((item, q, sell))]
                    else:
                        best, levels = None, []
                        for qq in range(1, q + 1):
                            bb = d.get((qq, sell, "request"))
                            if not bb:
                                continue
                            if best is None or bb[0] > best[1][0]:
                                best = (qq, bb)
                            if len(bb) > 3 and bb[3]:
                                levels.extend(bb[3])
                        if not best:
                            continue
                        bq, b = best
                        revenue = b[0] * (1 - tax)
                        st = [stats.get((item, qq, sell)) for qq in range(1, q + 1)]
                    profit = revenue - cost
                    units = invest = total = None
                    if buy_mode != "order" and levels and len(c) > 3:
                        levels.sort(key=lambda x: -x[0])
                        units, invest, total = walk_books(c[3], levels, tax)
                    st = [x for x in st if x]
                    vol = sum(x[0] for x in st) if st else None
                    ref = stats.get((item, bq, sell))
                    avg = ref[1] if ref else None
                    suspicious = bool(avg and b[0] > avg * SUSPICIOUS_FACTOR)
                    estimated = False
                    if units is None and vol and profit > 0:
                        units = max(1, int(vol))
                        invest, total, estimated = round(units * cost), round(units * profit), True
                    result.append(Opportunity(
                        item, q, city, bq, round(cost), b[0], round(revenue), round(profit),
                        profit / cost * 100, max(0.0, (now - c[1]) / 3600), max(0.0, (now - b[1]) / 3600),
                        c[2], b[2], units, invest, total, vol, estimated, sell, avg, suspicious))
    return result


def best_per_item(opps: List[Opportunity]) -> List[Opportunity]:
    """La mejor ruta (ciudad de compra y de venta) para cada objeto y calidad."""
    best: Dict[Tuple[str, int], Opportunity] = {}
    for o in opps:
        k = (o.item_id, o.quality)
        if k not in best or best[k].profit < o.profit:
            best[k] = o
    return list(best.values())


# ---------------------------------------------------------------------------- planificación

@dataclass
class Profile:
    name: str
    max_share: float            # parte máxima del capital en un mismo objeto
    volume_fraction: float      # parte del volumen diario del destino que se intenta colocar
    max_age_h: Optional[float]  # antigüedad máxima de los datos
    need_volume: bool           # exigir historial de ventas en el destino
    description: str


PROFILES: Dict[str, Profile] = {
    "max": Profile("Máximo beneficio", 0.50, 1.0, None, False,
                   "Concentra el capital en lo más rentable. Más ganancia esperada, más riesgo."),
    "balanced": Profile("Equilibrado", 0.25, 0.6, 6, False,
                        "Reparte entre más objetos y no intenta colocar más del 60 % del volumen diario."),
    "safe": Profile("Seguro", 0.12, 0.3, 2, True,
                    "Solo datos de menos de 2 h, objetos con ventas diarias conocidas y mucho reparto."),
}


@dataclass
class PlanLine:
    opp: Opportunity
    units: int
    invest: int
    profit: int
    weight: float = 0.0


@dataclass
class RoutePlan:
    buy_city: str
    sell_city: str
    lines: List[PlanLine]
    invest: int
    profit: int
    weight: float


def plan(opps: List[Opportunity], capital: float, max_share: Optional[float] = None,
         profile: str = "max", max_weight: Optional[float] = None,
         weight_of: Optional[Callable[[str], float]] = None) -> Tuple[List[PlanLine], int]:
    """Reparte el capital entre las oportunidades (voraz por rentabilidad).

    - No pone más de `max_share` del capital en un mismo objeto (por defecto, el del perfil).
    - Solo usa oportunidades con cantidades conocidas o estimadas, y nunca las sospechosas.
    - Si hay límite de peso (capacidad de carga), prioriza el beneficio por plata y por kilo.
    Devuelve (líneas, capital sin invertir).
    """
    p = PROFILES.get(profile, PROFILES["max"])
    share = max_share if max_share is not None else p.max_share
    weight_of = weight_of or (lambda _id: 0.0)

    candidates = []
    for o in opps:
        if o.suspicious or not o.units or not o.invest or not o.total_profit or o.total_profit <= 0:
            continue
        if p.max_age_h is not None and max(o.buy_age_h, o.bm_age_h) > p.max_age_h:
            continue
        if p.need_volume and not o.daily_volume:
            continue
        cap = o.units
        if o.daily_volume:
            cap = min(cap, max(1, int(o.daily_volume * p.volume_fraction)))
        unit_cost = o.invest / o.units
        unit_profit = o.total_profit / o.units
        w = weight_of(o.item_id) or 0.0
        density = unit_profit / (unit_cost / capital + (w / max_weight if max_weight else 0.0))
        candidates.append((density, o, cap, unit_cost, unit_profit, w))

    left, weight_left = capital, max_weight
    lines: List[PlanLine] = []
    used = set()
    for _, o, cap, unit_cost, unit_profit, w in sorted(candidates, key=lambda x: -x[0]):
        if left <= 0:
            break
        key = (o.item_id, o.sell_city)  # las órdenes del destino se comparten entre calidades y orígenes
        if key in used:
            continue
        n = min(cap, int(min(left, capital * share) // unit_cost))
        if weight_left is not None and w > 0:
            n = min(n, int(weight_left // w))
        if n <= 0:
            continue
        inv = round(n * unit_cost)
        lines.append(PlanLine(o, n, inv, round(n * unit_profit), n * w))
        used.add(key)
        left -= inv
        if weight_left is not None:
            weight_left -= n * w
    return lines, round(left)


def plan_routes(opps: List[Opportunity], capital: float, profile: str = "max",
                max_weight: Optional[float] = None,
                weight_of: Optional[Callable[[str], float]] = None, top: int = 8) -> List[RoutePlan]:
    """El mejor cargamento para cada ruta (ciudad de compra → ciudad de venta), ordenado por beneficio.
    Sirve para decidir un único viaje con tu capital y tu capacidad de carga."""
    by_route: Dict[Tuple[str, str], List[Opportunity]] = {}
    for o in opps:
        by_route.setdefault((o.city, o.sell_city), []).append(o)
    out = []
    for (buy, sell), lst in by_route.items():
        lines, _ = plan(lst, capital, profile=profile, max_weight=max_weight, weight_of=weight_of)
        if lines:
            out.append(RoutePlan(buy, sell, lines, sum(l.invest for l in lines), sum(l.profit for l in lines),
                                 sum(l.weight for l in lines)))
    out.sort(key=lambda r: -r.profit)
    return out[:top]
