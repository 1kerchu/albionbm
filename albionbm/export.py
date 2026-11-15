"""Informe en Markdown con las oportunidades, pensado para pegárselo a Claude (u otro asistente)
y preguntarle en qué invertir."""
from __future__ import annotations

import os
import time
from typing import List, Optional

from . import __version__
from .calc import QUALITY_NAMES, TAX_NO_PREMIUM, TAX_PREMIUM, SETUP_FEE, Opportunity, plan

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


def _src(o: Opportunity) -> str:
    a, b = o.buy_source, o.bm_source
    return "juego" if a == b == "juego" else ("API" if a == b == "api" else f"{a}/{b}".replace("api", "API"))


def select_rows(opps: List[Opportunity], limit: int = MAX_ROWS) -> List[Opportunity]:
    """Las mejores por % y las mejores por beneficio total, sin repetir."""
    by_pct = sorted(opps, key=lambda o: -o.percent)
    by_total = sorted((o for o in opps if o.total_profit), key=lambda o: -o.total_profit)
    seen, out = set(), []
    for o in [x for pair in zip(by_pct, by_total) for x in pair] + by_pct + by_total:
        k = (o.item_id, o.quality, o.city)
        if k not in seen:
            seen.add(k)
            out.append(o)
        if len(out) >= limit:
            break
    return sorted(out, key=lambda o: -o.percent)


def build_report(opps: List[Opportunity], catalog, *, server: str, premium: bool, buy_mode: str,
                 max_age_h: float, capital: Optional[float], location: Optional[str],
                 live_count: int, filters_text: str) -> str:
    tax = TAX_PREMIUM if premium else TAX_NO_PREMIUM
    rows = select_rows(opps)
    now = time.strftime("%Y-%m-%d %H:%M")
    L: List[str] = []
    w = L.append

    w(f"# Informe de oportunidades · Mercado Negro de Albion Online")
    w("")
    w(f"Generado por AlbionBM v{__version__} el {now} (hora local).")
    w("")
    w("## Instrucciones para el asistente")
    w("")
    w("Soy jugador de Albion Online. Abajo tienes oportunidades de comprar objetos en los mercados de las "
      "ciudades y venderlos a las órdenes de compra del Mercado Negro (Caerleon). Ayúdame a decidir en qué "
      "invertir mi capital para ganar lo máximo con un riesgo razonable. Ten en cuenta:")
    w("")
    w("- **Cantidades:** «Uds.» es cuántas unidades se pueden comprar con beneficio según las órdenes que vi "
      "en el juego, «Inversión máx.» lo que cuesta comprarlas todas y «Benef. total» lo que se ganaría. "
      "Si aparece «—», solo se conoce el mejor precio (datos de la API) y no la cantidad disponible.")
    w("- **Frescura:** «Datos» es la antigüedad del precio más viejo de los dos. Los precios cambian rápido, "
      "sobre todo en el Mercado Negro. Desconfía de lo que tenga varias horas o salga de la API.")
    w("- **Órdenes compartidas:** las órdenes del Mercado Negro aceptan la calidad pedida o superior, así que "
      "varias filas del mismo objeto (distinta calidad o ciudad) pueden competir por las mismas órdenes.")
    w("- **Transporte:** hay que llevar los objetos a Caerleon cruzando zona roja (riesgo de perderlo todo). "
      "«Peso» es el peso por unidad, por si importa la capacidad de la montura. Brecilien y Caerleon "
      "tienen sus propias rutas.")
    w("- **Sospechosos:** márgenes enormes suelen ser datos viejos o un error de precio. Señálalos.")
    w("")
    w("Dame un plan concreto: qué comprar, cuántas unidades, en qué ciudad y por cuánto, cuánto capital "
      "queda libre y los riesgos principales.")
    w("")
    w("## Contexto")
    w("")
    w(f"- **Capital disponible:** {fmt(capital) + ' de plata' if capital else '(indícalo en tu mensaje)'}")
    w(f"- **Servidor:** {SERVER_NAMES.get(server, server)}")
    w(f"- **Prémium:** {'sí' if premium else 'no'} → impuesto de venta {tax * 100:.0f} %")
    w(f"- **Modo de compra:** " + ("compra directa a las órdenes de venta de la ciudad" if buy_mode != "order"
                                   else f"poner órdenes de compra en la ciudad (tasa de publicación "
                                        f"{SETUP_FEE * 100:.1f} % incluida; tardan en llenarse)"))
    w(f"- **Ubicación actual del jugador:** {location or 'desconocida'}")
    w(f"- **Precios leídos del juego en las últimas 24 h:** {fmt(live_count)}")
    w(f"- **Filtros:** {filters_text}; datos de hasta {max_age_h:g} h")
    w(f"- **Oportunidades encontradas:** {fmt(len(opps))} (se muestran {len(rows)})")
    w("")
    w("Fórmulas: Recibes = precio MN × (1 − impuesto). Beneficio = Recibes − Precio compra. "
      "% = Beneficio / Precio compra.")
    w("")

    if capital:
        lines, left = plan(opps, capital)
        w("## Reparto automático propuesto por la app")
        w("")
        if lines:
            w("Primero lo más rentable (beneficio total / inversión), máximo 35 % del capital por objeto, solo con cantidades conocidas. "
              "Úsalo como punto de partida.")
            w("")
            w("| Objeto | ID | Calidad | Comprar en | Uds. | Inversión | Benef. estimado |")
            w("|---|---|---|---|--:|--:|--:|")
            for p in lines:
                o = p.opp
                w(f"| {catalog.name(o.item_id)} ({catalog.label(o.item_id)}) | `{o.item_id}` | "
                  f"{QUALITY_NAMES[o.quality]} | {o.city} | {fmt(p.units)} | {fmt(p.invest)} | {fmt(p.profit)} |")
            inv = sum(p.invest for p in lines)
            prof = sum(p.profit for p in lines)
            w(f"| **Total** | | | | | **{fmt(inv)}** | **{fmt(prof)}** ({prof / inv * 100:.1f} %) |")
            w("")
            w(f"Capital sin invertir: {fmt(left)}.")
        else:
            w("No hay oportunidades con cantidades conocidas. Lee el mercado en el juego para obtenerlas.")
        w("")

    w("## Oportunidades")
    w("")
    w("| # | Objeto | ID | Calidad | Comprar en | Precio compra | Paga MN | Benef./ud. | % | Uds. | "
      "Inversión máx. | Benef. total | Peso | Datos | Origen |")
    w("|--:|---|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|")
    for i, o in enumerate(rows, 1):
        q = QUALITY_NAMES[o.quality] + (f" (orden {QUALITY_NAMES[o.bm_quality]})" if o.bm_quality != o.quality else "")
        weight = catalog.base(o.item_id).get("w")
        w(f"| {i} | {catalog.name(o.item_id)} ({catalog.label(o.item_id)}) | `{o.item_id}` | {q} | {o.city} | "
          f"{fmt(o.buy_price)} | {fmt(o.bm_price)} | {fmt(o.profit)} | {o.percent:.1f} % | {fmt(o.units)} | "
          f"{fmt(o.invest)} | {fmt(o.total_profit)} | {weight if weight is not None else '—'} | "
          f"{ago(max(o.buy_age_h, o.bm_age_h))} | {_src(o)} |")
    if not rows:
        w("| | Sin oportunidades con estos filtros | | | | | | | | | | | | | |")
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
