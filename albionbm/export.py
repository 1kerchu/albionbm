"""Informe en Markdown con las oportunidades, pensado para pegárselo a Claude (u otro asistente)
y preguntarle en qué invertir."""
from __future__ import annotations

import os
import time
from typing import List, Optional

from . import __version__
from .calc import (PROFILES, QUALITY_NAMES, SETUP_FEE, STRATEGIES, TAX_NO_PREMIUM, TAX_PREMIUM, Opportunity,
                   plan, plan_routes)

MAX_ROWS = 150
SERVER_NAMES = {"europe": "Europa", "west": "América (West)", "east": "Asia (East)"}


def fmt(n) -> str:
    return "—" if n is None else f"{int(n):,}".replace(",", ".")


def ago(h: float) -> str:
    if h < 1:
        return f"{max(1, round(h * 60))} min"
    if h < 48:
        return f"{round(h)} h"
    return f"{round(h / 24)} d"


def _units(o: Opportunity) -> str:
    return ("~" if o.estimated else "") + fmt(o.units)


def _vol(o: Opportunity) -> str:
    if o.daily_volume is None:
        return "—"
    return f"{o.daily_volume:.1f}".replace(".", ",") if o.daily_volume < 10 else fmt(o.daily_volume)


def _src(o: Opportunity) -> str:
    a, b = o.buy_source, o.bm_source
    return "juego" if a == b == "juego" else ("API" if a == b == "api" else f"{a}/{b}".replace("api", "API"))


def select_rows(opps: List[Opportunity], limit: int = MAX_ROWS) -> List[Opportunity]:
    """Las mejores por % y las mejores por beneficio total, sin repetir."""
    by_pct = sorted(opps, key=lambda o: -o.percent)
    by_total = sorted((o for o in opps if o.total_profit), key=lambda o: -o.total_profit)
    seen, out = set(), []
    for o in [x for pair in zip(by_pct, by_total) for x in pair] + by_pct + by_total:
        k = (o.item_id, o.quality, o.city, o.sell_city)
        if k not in seen:
            seen.add(k)
            out.append(o)
        if len(out) >= limit:
            break
    return sorted(out, key=lambda o: -o.percent)


def build_report(opps: List[Opportunity], catalog, *, server: str, premium: bool, buy_mode: str,
                 max_age_h: float, capital: Optional[float], location: Optional[str],
                 live_count: int, filters_text: str, strategy: str = "bm", profile: str = "max",
                 max_weight: Optional[float] = None) -> str:
    tax = TAX_PREMIUM if premium else TAX_NO_PREMIUM
    rows = select_rows(opps)
    now = time.strftime("%Y-%m-%d %H:%M")
    prof = PROFILES.get(profile, PROFILES["max"])
    dest = "Mercado Negro (Caerleon)" if strategy == "bm" else "otra ciudad"
    L: List[str] = []
    w = L.append

    w("# Informe de oportunidades de comercio · Albion Online")
    w("")
    w(f"Generado por AlbionBM v{__version__} el {now} (hora local).")
    w("")
    w("## Instrucciones para el asistente")
    w("")
    w(f"Soy jugador de Albion Online. Abajo tienes oportunidades de comprar objetos en el mercado de una "
      f"ciudad y venderlos en {dest}. Estrategia: **{STRATEGIES[strategy]}**. Ayúdame a decidir en qué "
      "invertir mi capital para ganar lo máximo con un riesgo razonable. Ten en cuenta:")
    w("")
    w("- **Cantidades:** «Uds.» es cuántas unidades se pueden comprar con beneficio según las órdenes que vi "
      "en el juego, «Inversión máx.» lo que cuesta comprarlas todas y «Benef. total» lo que se ganaría. "
      "Si «Uds.» lleva «~», es una **estimación**: lo que se vende en el destino en un día de media "
      "(«Vol./día», últimos 7 días, de la API) valorado al mejor precio; la cantidad real en las órdenes "
      "es desconocida y el precio empeora al comprar más. «—» = sin datos de cantidad.")
    w("- **Precio medio y sospechosos:** «Media 7d» es el precio medio de venta en el destino esta semana. "
      "Las filas con ⚠ venden a más de 1,6 veces esa media: casi siempre es un dato viejo o una orden "
      "trampa. No las recomiendes salvo que yo las confirme en el juego.")
    w("- **Frescura:** «Datos» es la antigüedad del precio más viejo de los dos. Los precios cambian rápido. "
      "Desconfía de lo que tenga varias horas o salga de la API.")
    w("- **Órdenes compartidas:** una orden de compra acepta la calidad pedida o superior, así que varias "
      "filas del mismo objeto (distinta calidad u origen) pueden competir por las mismas órdenes.")
    if strategy == "city_order":
        w("- **Orden de venta:** aquí se vende poniendo una orden de venta al precio más bajo actual del "
          "destino (tasa de publicación incluida). No es inmediato: puede tardar o no venderse si otros "
          "bajan el precio. «Vol./día» indica cuánto se mueve ese objeto.")
    w("- **Transporte:** vender en Caerleon o en el Mercado Negro obliga a cruzar zona roja (riesgo de "
      "perderlo todo). Entre ciudades reales hay rutas por zona amarilla y azul. «Peso» es el peso por unidad.")
    w("")
    w("Dame un plan concreto: qué comprar, cuántas unidades, dónde comprar y dónde vender, cuánto capital "
      "queda libre y los riesgos principales. Si hay límite de carga, que quepa en un viaje.")
    w("")
    w("## Contexto")
    w("")
    w(f"- **Capital disponible:** {fmt(capital) + ' de plata' if capital else '(indícalo en tu mensaje)'}")
    w(f"- **Capacidad de carga por viaje:** {f'{max_weight:g} kg' if max_weight else 'sin indicar'}")
    w(f"- **Perfil de riesgo elegido:** {prof.name} — {prof.description}")
    w(f"- **Estrategia:** {STRATEGIES[strategy]}")
    w(f"- **Servidor:** {SERVER_NAMES.get(server, server)}")
    w(f"- **Prémium:** {'sí' if premium else 'no'} → impuesto de venta {tax * 100:.0f} %")
    w("- **Modo de compra:** " + ("compra directa a las órdenes de venta de la ciudad" if buy_mode != "order"
                                  else f"poner órdenes de compra en la ciudad (tasa de publicación "
                                       f"{SETUP_FEE * 100:.1f} % incluida; tardan en llenarse)"))
    w(f"- **Ubicación actual del jugador:** {location or 'desconocida'}")
    w(f"- **Precios leídos del juego en las últimas 24 h:** {fmt(live_count)}")
    w(f"- **Filtros:** {filters_text}; datos de hasta {max_age_h:g} h")
    n_susp = sum(1 for o in opps if o.suspicious)
    w(f"- **Oportunidades encontradas:** {fmt(len(opps))} (se muestran {len(rows)}; {n_susp} sospechosas)")
    w("")
    w("Fórmulas: Recibes = precio de venta × (1 − impuesto"
      + (" − tasa de publicación" if strategy == "city_order" else "") +
      "). Beneficio = Recibes − Precio compra. % = Beneficio / Precio compra.")
    w("")

    if capital:
        weight_of = catalog.weight
        routes = plan_routes(opps, capital, profile, max_weight, weight_of)
        if routes:
            w("## Mejores rutas para un solo viaje")
            w("")
            w(f"Mejor cargamento por ruta con el capital{' y la carga' if max_weight else ''} indicados "
              f"(perfil {prof.name}).")
            w("")
            w("| Ruta | Objetos | Inversión | Benef. estimado | % | Peso (kg) |")
            w("|---|--:|--:|--:|--:|--:|")
            for r in routes:
                w(f"| {r.buy_city} → {r.sell_city} | {len(r.lines)} | {fmt(r.invest)} | {fmt(r.profit)} | "
                  f"{r.profit / r.invest * 100:.1f} % | {r.weight:.0f} |")
            w("")
        lines, left = plan(opps, capital, profile=profile, max_weight=max_weight, weight_of=weight_of)
        w("## Reparto automático propuesto por la app")
        w("")
        if lines:
            w(f"Perfil {prof.name}: máximo {prof.max_share * 100:.0f} % del capital por objeto, sin sospechosos, "
              "con cantidades leídas del juego o estimadas («~») por el volumen diario. Mezcla varias rutas. "
              "Úsalo como punto de partida.")
            w("")
            w("| Objeto | ID | Calidad | Comprar en | Vender en | Uds. | Inversión | Benef. estimado | Peso (kg) |")
            w("|---|---|---|---|---|--:|--:|--:|--:|")
            for p in lines:
                o = p.opp
                w(f"| {catalog.name(o.item_id)} ({catalog.label(o.item_id)}) | `{o.item_id}` | "
                  f"{QUALITY_NAMES[o.quality]} | {o.city} | {o.sell_city} | {'~' if o.estimated else ''}{fmt(p.units)} | "
                  f"{fmt(p.invest)} | {fmt(p.profit)} | {p.weight:.0f} |")
            inv = sum(p.invest for p in lines)
            tot = sum(p.profit for p in lines)
            w(f"| **Total** | | | | | | **{fmt(inv)}** | **{fmt(tot)}** ({tot / inv * 100:.1f} %) | "
              f"{sum(p.weight for p in lines):.0f} |")
            w("")
            w(f"Capital sin invertir: {fmt(left)}.")
        else:
            w("No hay oportunidades válidas para este perfil. Pulsa «Actualizar precios» (incluye el volumen "
              "diario), prueba un perfil menos estricto o lee el mercado en el juego.")
        w("")

    w("## Oportunidades")
    w("")
    w("| # | Objeto | ID | Calidad | Comprar en | Vender en | Precio compra | Precio venta | Media 7d | Benef./ud. | % | "
      "Uds. | Inversión máx. | Benef. total | Vol./día | Peso | Datos | Origen |")
    w("|--:|---|---|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|")
    for i, o in enumerate(rows, 1):
        q = QUALITY_NAMES[o.quality] + (f" (orden {QUALITY_NAMES[o.bm_quality]})" if o.bm_quality != o.quality else "")
        weight = catalog.base(o.item_id).get("w")
        w(f"| {i} | {'⚠ ' if o.suspicious else ''}{catalog.name(o.item_id)} ({catalog.label(o.item_id)}) | "
          f"`{o.item_id}` | {q} | {o.city} | {o.sell_city} | {fmt(o.buy_price)} | {fmt(o.bm_price)} | "
          f"{fmt(o.avg_price)} | {fmt(o.profit)} | {o.percent:.1f} % | {_units(o)} | "
          f"{fmt(o.invest)} | {fmt(o.total_profit)} | {_vol(o)} | {weight if weight is not None else '—'} | "
          f"{ago(max(o.buy_age_h, o.bm_age_h))} | {_src(o)} |")
    if not rows:
        w("| | Sin oportunidades con estos filtros | | | | | | | | | | | | | | | | |")
    w("")
    return "\n".join(L)


def export_dir() -> str:
    home = os.path.expanduser("~")
    docs = os.path.join(home, "Documents")
    base = docs if os.path.isdir(docs) else home
    path = os.path.join(base, "AlbionBM")
    os.makedirs(path, exist_ok=True)
    return path


def save_report(text: str) -> str:
    path = os.path.join(export_dir(), time.strftime("informe_albionbm_%Y%m%d_%H%M.md"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path
