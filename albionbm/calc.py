"""Cálculo de oportunidades: comprar en una ciudad y vender al Mercado Negro."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from .game import BLACK_MARKET

SETUP_FEE = 0.025      # tasa por publicar una orden
TAX_PREMIUM = 0.04     # impuesto de venta con prémium
TAX_NO_PREMIUM = 0.08  # impuesto de venta sin prémium

QUALITY_NAMES = {1: "Normal", 2: "Buena", 3: "Notable", 4: "Sobresaliente", 5: "Obra maestra"}


@dataclass
class Opportunity:
    item_id: str
    quality: int
    city: str
    bm_quality: int
    buy_price: int
    bm_price: int
    revenue: int
    profit: int
    percent: float
    buy_age_h: float
    bm_age_h: float
    buy_source: str
    bm_source: str
    # Según la profundidad de órdenes leída del juego (None si no se conoce, p. ej. datos de la API):
    units: Optional[int] = None         # unidades que se pueden comprar y vender con beneficio
    invest: Optional[int] = None        # plata necesaria para comprarlas todas
    total_profit: Optional[int] = None  # beneficio total vendiéndolas al MN


def walk_books(buy_book: Optional[list], bm_book: Optional[list], tax: float):
    """Cruza las órdenes de venta de la ciudad (más baratas primero) con las de compra del MN
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
            buy_mode: str = "instant", now: Optional[float] = None) -> List[Opportunity]:
    """
    entries: {(item, calidad, ubicación, "offer"|"request"): (precio, timestamp, origen[, profundidad])}

    - Se vende a las órdenes de compra del Mercado Negro.
    - Una orden de calidad Q acepta objetos de calidad >= Q: se usa la mejor orden con calidad <= la del objeto.
    - Vender a una orden paga impuesto de venta; comprar con orden de compra paga la tasa de publicación.
    """
    now = now or time.time()
    tax = TAX_PREMIUM if premium else TAX_NO_PREMIUM
    cities = list(cities)
    qualities = list(qualities)

    bm: Dict[str, Dict[int, tuple]] = {}
    items = set()
    for (item, q, loc, kind), val in entries.items():
        if loc == BLACK_MARKET and kind == "request":
            bm.setdefault(item, {})[q] = val
        items.add(item)

    result: List[Opportunity] = []
    for item, bm_q in bm.items():
        for city in cities:
            for q in qualities:
                if buy_mode == "order":
                    c = entries.get((item, q, city, "request"))
                    if not c:
                        continue
                    cost = c[0] * (1 + SETUP_FEE)
                else:
                    c = entries.get((item, q, city, "offer"))
                    if not c:
                        continue
                    cost = float(c[0])
                best = None
                for bq in range(1, q + 1):
                    b = bm_q.get(bq)
                    if b and (best is None or b[0] > best[1][0]):
                        best = (bq, b)
                if not best or cost <= 0:
                    continue
                bq, b = best
                bprice, bts, bsrc = b[0], b[1], b[2]
                revenue = bprice * (1 - tax)
                profit = revenue - cost
                units = invest = total = None
                if buy_mode != "order":
                    # Órdenes del MN que aceptan esta calidad (todas las de calidad <= q), de mayor a menor precio
                    levels = []
                    for qq in range(1, q + 1):
                        bb = bm_q.get(qq)
                        if bb and len(bb) > 3 and bb[3]:
                            levels.extend(bb[3])
                    if levels and len(c) > 3:
                        levels.sort(key=lambda x: -x[0])
                        units, invest, total = walk_books(c[3], levels, tax)
                result.append(Opportunity(
                    item, q, city, bq, round(cost), bprice, round(revenue), round(profit),
                    profit / cost * 100, max(0.0, (now - c[1]) / 3600), max(0.0, (now - bts) / 3600), c[2], bsrc,
                    units, invest, total))
    return result


def best_per_item(opps: List[Opportunity]) -> List[Opportunity]:
    best: Dict[Tuple[str, int], Opportunity] = {}
    for o in opps:
        k = (o.item_id, o.quality)
        if k not in best or best[k].profit < o.profit:
            best[k] = o
    return list(best.values())


@dataclass
class PlanLine:
    opp: Opportunity
    units: int
    invest: int
    profit: int


def plan(opps: List[Opportunity], capital: float, max_share: float = 0.35) -> Tuple[List[PlanLine], int]:
    """Reparto simple del capital: primero lo más rentable (beneficio total / inversión, contando todas
    las unidades disponibles y no solo la primera), sin poner más de `max_share`
    del capital en un mismo objeto y usando solo oportunidades con cantidades conocidas.
    Devuelve (líneas, capital sin invertir)."""
    left = capital
    lines: List[PlanLine] = []
    used_items = set()
    def avg_return(o: Opportunity) -> float:
        return o.total_profit / o.invest if o.invest and o.total_profit else -1.0

    for o in sorted(opps, key=lambda x: -avg_return(x)):
        if left <= 0:
            break
        if not o.units or not o.invest or o.total_profit is None or o.total_profit <= 0:
            continue
        if o.item_id in used_items:  # las órdenes del MN se comparten entre calidades y ciudades
            continue
        per_unit = o.invest / o.units
        budget = min(left, o.invest, capital * max_share)
        n = int(budget // per_unit)
        if n <= 0:
            continue
        inv = round(n * per_unit)
        prof = round(o.total_profit * n / o.units)
        lines.append(PlanLine(o, n, inv, prof))
        used_items.add(o.item_id)
        left -= inv
    return lines, round(left)
