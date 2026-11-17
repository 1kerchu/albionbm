"""Lista de «confirmar en el juego»: qué objetos abrir en qué mercado para comprobar las mejores
oportunidades antes de comprar, y si siguen compensando con los precios reales."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .calc import SETUP_FEE, TAX_NO_PREMIUM, TAX_PREMIUM, Opportunity
from .game import BLACK_MARKET

FRESH_MINUTES = 30  # un precio leído del juego cuenta como comprobado durante este tiempo

Key = Tuple[str, int, str, str]  # (objeto, calidad, ubicación, "offer"|"request")


@dataclass
class Check:
    """Un objeto que hay que abrir en un mercado."""
    item: str
    quality: int
    location: str
    kind: str                 # "offer": se ve en la pestaña Comprar; "request": en la pestaña Vender
    api_price: int            # precio que se usó al hacer la lista
    uses: List[int] = field(default_factory=list)  # índices de las oportunidades que dependen de él

    @property
    def key(self) -> Key:
        return (self.item, self.quality, self.location, self.kind)

    @property
    def tab(self) -> str:
        return "Comprar" if self.kind == "offer" else "Vender"


@dataclass
class Checklist:
    opps: List[Opportunity]
    checks: List[Check]
    buy_mode: str
    strategy: str
    created: float = field(default_factory=time.time)


def build(opps: List[Opportunity], buy_mode: str = "instant", strategy: str = "bm") -> Checklist:
    """Para cada oportunidad hay que ver dos precios: el de compra en su ciudad y el de venta en su destino.
    Si dos oportunidades comparten un precio, se comprueba una sola vez."""
    checks: Dict[Key, Check] = {}
    buy_kind = "request" if buy_mode == "order" else "offer"
    sell_kind = "offer" if strategy == "city_order" else "request"
    for i, o in enumerate(opps):
        raw_buy = round(o.buy_price / (1 + SETUP_FEE)) if buy_mode == "order" else o.buy_price
        sell_q = o.quality if strategy == "city_order" else o.bm_quality
        for item, q, loc, kind, price in ((o.item_id, o.quality, o.city, buy_kind, raw_buy),
                                          (o.item_id, sell_q, o.sell_city, sell_kind, o.bm_price)):
            c = checks.setdefault((item, q, loc, kind), Check(item, q, loc, kind, price))
            c.uses.append(i)
    return Checklist(list(opps), list(checks.values()), buy_mode, strategy)


def live_price(entries: dict, key: Key, now: Optional[float] = None) -> Optional[int]:
    """Precio leído del juego en los últimos FRESH_MINUTES minutos, o None si no se ha comprobado."""
    e = entries.get(key)
    now = now or time.time()
    if e and e[2] == "juego" and now - e[1] <= FRESH_MINUTES * 60:
        return int(e[0])
    return None


def verdict(cl: Checklist, i: int, entries: dict, premium: bool = True, now: Optional[float] = None) -> dict:
    """Recalcula una oportunidad con los precios comprobados en el juego (los que falten, con los de la API)."""
    o = cl.opps[i]
    checks = [c for c in cl.checks if i in c.uses]
    buy_c = next(c for c in checks if c.location == o.city and c.item == o.item_id and c.quality == o.quality
                 and c.kind == ("request" if cl.buy_mode == "order" else "offer"))
    sell_c = next(c for c in checks if c is not buy_c)
    buy_live, sell_live = live_price(entries, buy_c.key, now), live_price(entries, sell_c.key, now)
    buy = (buy_live if buy_live is not None else buy_c.api_price) * (1 + (SETUP_FEE if cl.buy_mode == "order" else 0.0))
    sell = sell_live if sell_live is not None else sell_c.api_price
    tax = TAX_PREMIUM if premium else TAX_NO_PREMIUM
    revenue = sell * (1 - tax - (SETUP_FEE if cl.strategy == "city_order" else 0.0))
    profit = revenue - buy
    done = buy_live is not None and sell_live is not None
    return {"buy": buy, "sell": sell, "profit": profit, "percent": profit / buy * 100 if buy else 0.0,
            "confirmed": done, "partial": (buy_live is None) != (sell_live is None),
            "still_good": profit > 0, "change": profit - o.profit}


def groups(cl: Checklist, entries: dict, here: Optional[str] = None, now: Optional[float] = None):
    """Comprobaciones agrupadas por (ubicación, pestaña), con la ubicación actual primero y el
    Mercado Negro al final. Devuelve [((ubicación, pestaña), [(check, precio_juego o None)])]."""
    out: Dict[Tuple[str, str], list] = {}
    for c in cl.checks:
        out.setdefault((c.location, c.tab), []).append((c, live_price(entries, c.key, now)))

    def order(k):
        loc, tab = k
        return (loc != here, loc == BLACK_MARKET, loc, tab)

    return [(k, out[k]) for k in sorted(out, key=order)]
