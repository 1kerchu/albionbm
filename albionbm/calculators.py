"""Calculadoras: fabricación, refinado, venta manual y mejora de encantamiento.

La versión web tiene el mismo código en web/calculators.js; los tests comprueban que dan lo mismo.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List, Optional

from .calc import SETUP_FEE, TAX_NO_PREMIUM, TAX_PREMIUM

# Retorno de recursos: RRR = 1 - 1 / (1 + bonus de producción)
PB_BASE = 0.18                              # ciudades reales
PB_CITY = {"craft": 0.15, "refine": 0.40}   # ciudad con bonus para ese objeto o recurso
PB_FOCUS = 0.59                             # usando foco
NUTRITION_PER_VALUE = 0.1125                # nutrición que consume fabricar = valor del objeto × 0,1125


def load_recipes() -> dict:
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    with open(os.path.join(base, "data", "recipes.json"), encoding="utf-8") as f:
        return json.load(f)


def return_rate(kind: str = "craft", city_bonus: bool = False, focus: bool = False) -> float:
    """Proporción de materiales que se devuelve (0,152 = 15,2 %)."""
    pb = PB_BASE + (PB_CITY[kind] if city_bonus else 0.0) + (PB_FOCUS if focus else 0.0)
    return 1 - 1 / (1 + pb)


def tax_rate(premium: bool) -> float:
    return TAX_PREMIUM if premium else TAX_NO_PREMIUM


def craft(recipe: dict, values: Dict[str, float], prices: Dict[str, float], sell_price: Optional[float], *,
          rrr: float, fee100: float = 0.0, premium: bool = True, sell_order: bool = True,
          quantity: int = 1) -> dict:
    """Coste y beneficio de fabricar (o refinar) `quantity` veces una receta.

    recipe: {"m": [[material, cantidad, se_devuelve], ...], "f": foco, "n": unidades por fabricación}
    prices: precio de cada material; los que falten se listan en "missing" y cuentan como 0.
    fee100: tasa del taller en plata por cada 100 de nutrición.
    """
    mats, gross, returned, item_value, missing = [], 0.0, 0.0, 0.0, []
    for mid, count, returnable in recipe["m"]:
        price = prices.get(mid)
        if not price:
            missing.append(mid)
            price = 0.0
        cost = price * count
        gross += cost
        if returnable:
            returned += cost * rrr
        item_value += values.get(mid, 0.0) * count
        mats.append({"id": mid, "count": count, "price": price, "cost": cost, "returnable": bool(returnable)})
    n = recipe.get("n", 1) or 1
    fee = item_value * NUTRITION_PER_VALUE * fee100 / 100
    cost_per_craft = gross - returned + fee
    unit_cost = cost_per_craft / n
    out = {"materials": mats, "gross": gross, "returned": returned, "fee": fee, "item_value": item_value,
           "cost_per_craft": cost_per_craft, "units_per_craft": n, "unit_cost": unit_cost,
           "focus": recipe.get("f", 0) * quantity, "units": n * quantity, "total_cost": cost_per_craft * quantity,
           "missing": missing, "unit_revenue": None, "unit_profit": None, "percent": None, "total_profit": None,
           "profit_per_focus": None}
    if sell_price:
        rev = sell_price * (1 - tax_rate(premium) - (SETUP_FEE if sell_order else 0.0))
        profit = rev - unit_cost
        out.update(unit_revenue=rev, unit_profit=profit, percent=(profit / unit_cost * 100 if unit_cost > 0 else None),
                   total_profit=profit * n * quantity)
        if out["focus"]:
            out["profit_per_focus"] = out["total_profit"] / out["focus"]
    return out


def trade(buy_price: float, sell_price: float, quantity: int = 1, *, premium: bool = True,
          buy_order: bool = False, sell_order: bool = False) -> dict:
    """Beneficio de comprar y vender a precios dados, con impuestos y tasas."""
    fees = tax_rate(premium) + (SETUP_FEE if sell_order else 0.0)
    unit_cost = buy_price * (1 + (SETUP_FEE if buy_order else 0.0))
    unit_rev = sell_price * (1 - fees)
    profit = unit_rev - unit_cost
    return {"unit_cost": unit_cost, "unit_revenue": unit_rev, "unit_profit": profit,
            "percent": profit / unit_cost * 100 if unit_cost > 0 else None,
            "total_cost": unit_cost * quantity, "total_revenue": unit_rev * quantity, "total_profit": profit * quantity,
            "fees": sell_price * fees + (unit_cost - buy_price),
            "breakeven": unit_cost / (1 - fees)}  # precio de venta mínimo para no perder


def upgrade(steps: List[list], from_level: int, to_level: int, base_price: Optional[float],
            res_prices: Dict[str, float], target_price: Optional[float]) -> dict:
    """Coste de subir un objeto de encantamiento .from a .to frente a comprarlo ya encantado.

    steps: [[recurso, cantidad] para .1, .2, .3...] (de recipes.json -> upgrades)
    """
    rows, cost, missing = [], 0.0, []
    for lvl in range(from_level + 1, to_level + 1):
        if lvl - 1 >= len(steps):
            raise ValueError(f"Este objeto no se puede mejorar a .{lvl}")
        res, count = steps[lvl - 1]
        price = res_prices.get(res)
        if not price:
            missing.append(res)
            price = 0.0
        rows.append({"level": lvl, "id": res, "count": count, "price": price, "cost": price * count})
        cost += price * count
    if not base_price:
        missing.append("base")
    total = (base_price or 0.0) + cost
    saving = (target_price - total) if target_price else None
    return {"steps": rows, "upgrade_cost": cost, "total": total, "direct": target_price, "saving": saving,
            "missing": missing, "worth_it": bool(saving is not None and saving > 0 and not missing)}
