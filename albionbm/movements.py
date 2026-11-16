"""Historial automático: tus compras y ventas leídas del juego, y el beneficio que dejan."""
from __future__ import annotations

from typing import Dict, List, Tuple

from .calc import SETUP_FEE, TAX_NO_PREMIUM, TAX_PREMIUM

KIND_LABELS = {"buy_direct": "Compra directa", "buy_order": "Compra por orden",
               "quick_sell": "Venta rápida", "sell_order": "Venta por orden"}
BUYS = {"buy_direct", "buy_order"}


def net_silver(kind: str, silver: float, premium: bool) -> float:
    """Plata que de verdad sale o entra, con impuestos y tasas.

    El juego informa de la plata bruta. Las órdenes pagan además un 2,5 % al publicarlas, y toda venta
    paga el impuesto de venta (4 % con prémium, 8 % sin).
    """
    tax = TAX_PREMIUM if premium else TAX_NO_PREMIUM
    if kind == "buy_direct":
        return silver
    if kind == "buy_order":
        return silver * (1 + SETUP_FEE)
    if kind == "quick_sell":
        return silver * (1 - tax)
    return silver * (1 - tax - SETUP_FEE)  # sell_order


def realize(movements: List[dict], premium: bool = True) -> Tuple[List[dict], dict]:
    """Calcula el beneficio de cada venta con el coste medio de lo comprado antes del mismo objeto.

    movements: [{"key", "ts", "kind", "item", "qty", "silver", ...}]
    Devuelve (filas en orden cronológico, resumen). En cada fila añade:
      "net":      plata neta (gastada en compras, ingresada en ventas)
      "profit":   beneficio de la venta, o None si es una compra o no se conoce el coste de nada de lo vendido
      "unknown":  unidades vendidas cuyo coste no se conoce (no se vio su compra)
    """
    stock: Dict[str, List[float]] = {}  # objeto -> [unidades, coste total]
    rows, spent, earned, profit, unknown_revenue = [], 0.0, 0.0, 0.0, 0.0
    for m in sorted(movements, key=lambda x: x["ts"]):
        net = net_silver(m["kind"], m["silver"], premium)
        row = dict(m, net=net, profit=None, unknown=0)
        s = stock.setdefault(m["item"], [0.0, 0.0])
        if m["kind"] in BUYS:
            s[0] += m["qty"]
            s[1] += net
            spent += net
        else:
            earned += net
            matched = min(m["qty"], s[0])
            if matched > 0:
                cost = s[1] / s[0] * matched
                row["profit"] = net * matched / m["qty"] - cost
                profit += row["profit"]
                s[0] -= matched
                s[1] -= cost
            row["unknown"] = m["qty"] - matched
            unknown_revenue += net * row["unknown"] / m["qty"]
        rows.append(row)
    summary = {"spent": spent, "earned": earned, "profit": profit, "unknown_revenue": unknown_revenue,
               "stock_units": sum(s[0] for s in stock.values()), "stock_cost": sum(s[1] for s in stock.values())}
    return rows, summary


def profit_since(rows: List[dict], since_ts: float) -> float:
    return sum(r["profit"] for r in rows if r["profit"] is not None and r["ts"] >= since_ts)
