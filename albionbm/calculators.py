"""Calculadoras: fabricación, refinado, venta manual y mejora de encantamiento.

La versión web tiene el mismo código en web/calculators.js; los tests comprueban que dan lo mismo.
"""
from __future__ import annotations

import json
import math
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


def rank(recipes: Dict[str, dict], values: Dict[str, float], ids: List[str], buy_price, sell_price, **opts) -> List[dict]:
    """Ranking de qué fabricar: calcula todas las recetas de `ids` y devuelve las que tienen todos los precios.

    buy_price(material) y sell_price(objeto) devuelven el precio o 0 si no se conoce.
    opts: los mismos de craft() (rrr, fee100, premium, sell_order).
    """
    out = []
    for item_id in ids:
        r = recipes.get(item_id)
        sp = sell_price(item_id) if r else 0
        if not r or not sp:
            continue
        c = craft(r, values, {m[0]: buy_price(m[0]) for m in r["m"]}, sp, **opts)
        if not c["missing"]:
            c["id"], c["sell_price"] = item_id, sp
            out.append(c)
    return out


# ---------------------------------------------------------------------------- comprar o fabricar

DEFAULT_SLIP = 0.30  # cuánto sube el precio de la última unidad al comprar lo que se vende en un día
MAX_SLIP = 2.0       # tope de la subida estimada (precio marginal como mucho ×3)


def buy_cost(n: int, best: Optional[float], book: Optional[list] = None, daily: Optional[float] = None,
             slip: float = DEFAULT_SLIP) -> Optional[dict]:
    """Coste de comprar `n` unidades teniendo en cuenta que el precio sube al agotar las órdenes baratas.

    - book: órdenes de venta leídas del juego, [[precio, cantidad], ...] de barata a cara. Se recorren tal cual.
    - Lo que no cubran las órdenes (o todo, si no hay) se ESTIMA: el precio de cada unidad sube en línea recta
      hasta +slip al comprar `daily` unidades (lo que se vende en un día). Sin `daily` no se estima subida.
    Devuelve {"total", "avg", "exact" (todo salió de órdenes reales), "covered" (unidades de órdenes reales),
              "no_volume" (hubo que estimar sin datos de ventas)} o None si no hay precio.
    """
    if n <= 0:
        return {"total": 0.0, "avg": 0.0, "exact": True, "covered": 0, "no_volume": False}
    total, left, last = 0.0, n, best
    for price, amount in book or []:
        take = min(left, amount)
        if take > 0:
            total += take * price
            left -= take
            last = price
        if left == 0:
            break
    if not last:
        return None
    covered, no_volume = n - left, False
    if left:
        if daily and daily > 0:
            # la unidad k (0, 1, 2...) cuesta last × (1 + slip·k/daily), con tope; la primera sale al precio visto
            x_cap = MAX_SLIP * daily / slip if slip > 0 else float("inf")
            a = min(left, x_cap)
            total += last * (a + (slip * a * (a - 1) / (2 * daily) if slip > 0 else 0.0)) + last * (1 + MAX_SLIP) * (left - a)
        else:
            total += last * left
            no_volume = True
    return {"total": total, "avg": total / n, "exact": left == 0, "covered": covered, "no_volume": no_volume}


def craft_cost(recipe: dict, values: Dict[str, float], units: int, quote, *, rrr: float, fee100: float = 0.0) -> dict:
    """Coste de fabricar al menos `units` unidades comprando los materiales (con subida de precio).

    quote(material, cantidad) -> resultado de buy_cost() o None si no hay precio.
    Con el retorno de recursos, de cada material retornable solo hay que comprar la parte que no vuelve.
    """
    per = recipe.get("n", 1) or 1
    crafts = math.ceil(units / per)
    mats, total, missing, exact, no_volume, item_value = [], 0.0, [], True, False, 0.0
    for mid, count, returnable in recipe["m"]:
        need = count * crafts
        to_buy = math.ceil(need * (1 - rrr)) if returnable else need
        q = quote(mid, to_buy)
        item_value += values.get(mid, 0.0) * count
        if q is None:
            missing.append(mid)
            mats.append({"id": mid, "need": need, "buy": to_buy, "avg": None, "total": 0.0, "exact": False})
            continue
        total += q["total"]
        exact = exact and q["exact"]
        no_volume = no_volume or q["no_volume"]
        mats.append({"id": mid, "need": need, "buy": to_buy, "avg": q["avg"], "total": q["total"], "exact": q["exact"]})
    fee = item_value * NUTRITION_PER_VALUE * fee100 / 100 * crafts
    made = crafts * per
    return {"materials": mats, "materials_total": total, "fee": fee, "total": total + fee, "crafts": crafts,
            "units": made, "unit_cost": (total + fee) / made, "missing": missing, "exact": exact, "no_volume": no_volume}


def buy_or_craft(recipe: dict, values: Dict[str, float], units: int, quote_item, quote_mat, *, rrr: float,
                 fee100: float = 0.0, max_scan: int = 10000) -> dict:
    """Compara comprar `units` unidades del objeto con fabricarlas. Devuelve además a partir de qué
    cantidad cambia la respuesta ("switch_at"), porque comprar se encarece más rápido que fabricar.

    quote_item(cantidad) y quote_mat(material, cantidad) devuelven buy_cost() o None.
    """
    craft = craft_cost(recipe, values, units, quote_mat, rrr=rrr, fee100=fee100)
    buy = quote_item(units)
    out = {"units": units, "buy": buy, "craft": craft, "verdict": None, "saving": None, "switch_at": None}
    if buy is None or craft["missing"]:
        return out
    buy_unit = buy["avg"]
    out["verdict"] = "craft" if craft["unit_cost"] < buy_unit else "buy"
    out["saving"] = abs(buy_unit - craft["unit_cost"]) * units

    def better(n: int) -> Optional[str]:
        b, c = quote_item(n), craft_cost(recipe, values, n, quote_mat, rrr=rrr, fee100=fee100)
        if b is None or c["missing"]:
            return None
        return "craft" if c["unit_cost"] < b["avg"] else "buy"

    # Primera cantidad mayor (en saltos 1-2-5) en la que pasa a ganar la otra opción; es aproximada
    scale = 1
    while scale <= max_scan:
        for cand in (scale, scale * 2, scale * 5):
            if units < cand <= max_scan:
                v = better(cand)
                if v and v != out["verdict"]:
                    out["switch_at"] = cand
                    return out
        scale *= 10
    return out
