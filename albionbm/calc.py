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


def compute(entries: Dict[Tuple[str, int, str, str], Tuple[int, float, str]],
            cities: Iterable[str], qualities: Iterable[int], premium: bool = True,
            buy_mode: str = "instant", now: Optional[float] = None) -> List[Opportunity]:
    """
    entries: {(item, calidad, ubicación, "offer"|"request"): (precio, timestamp, origen)}

    - Se vende a las órdenes de compra del Mercado Negro.
    - Una orden de calidad Q acepta objetos de calidad >= Q: se usa la mejor orden con calidad <= la del objeto.
    - Vender a una orden paga impuesto de venta; comprar con orden de compra paga la tasa de publicación.
    """
    now = now or time.time()
    tax = TAX_PREMIUM if premium else TAX_NO_PREMIUM
    cities = list(cities)
    qualities = list(qualities)

    bm: Dict[str, Dict[int, Tuple[int, float, str]]] = {}
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
                bq, (bprice, bts, bsrc) = best
                revenue = bprice * (1 - tax)
                profit = revenue - cost
                result.append(Opportunity(
                    item, q, city, bq, round(cost), bprice, round(revenue), round(profit),
                    profit / cost * 100, max(0.0, (now - c[1]) / 3600), max(0.0, (now - bts) / 3600), c[2], bsrc))
    return result


def best_per_item(opps: List[Opportunity]) -> List[Opportunity]:
    best: Dict[Tuple[str, int], Opportunity] = {}
    for o in opps:
        k = (o.item_id, o.quality)
        if k not in best or best[k].profit < o.profit:
            best[k] = o
    return list(best.values())
