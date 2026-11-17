"""Avisos a Discord: la app manda un mensaje a un canal mediante un webhook."""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from typing import Callable, List, Optional

from . import __version__
from .api import ssl_context
from .store import default_db_path

CONFIG_FILE = "avisos.json"
DEFAULTS = {"webhook": "", "enabled": False, "min_pct": "20", "min_total": "100000", "favs": True}
WEBHOOK_PREFIXES = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/",
                    "https://ptb.discord.com/api/webhooks/", "https://canary.discord.com/api/webhooks/")
MAX_LEN = 1900  # Discord admite 2000 caracteres por mensaje


def _path() -> str:
    return os.path.join(os.path.dirname(default_db_path()), CONFIG_FILE)


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(_path(), encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def valid_webhook(url: str) -> bool:
    return url.strip().startswith(WEBHOOK_PREFIXES)


def send(webhook: str, text: str, timeout: float = 15) -> Optional[str]:
    """Envía un mensaje. Devuelve None si fue bien, o el motivo del fallo."""
    if not valid_webhook(webhook):
        return "La dirección no parece un webhook de Discord (debe empezar por https://discord.com/api/webhooks/)."
    body = json.dumps({"content": text[:MAX_LEN], "username": "Albion BM"}).encode("utf-8")
    req = urllib.request.Request(webhook.strip(), data=body, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": f"AlbionBM/{__version__} (avisos de mercado)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()):
            return None
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            return "Discord rechazó el webhook: puede que lo hayan borrado. Crea uno nuevo y pégalo otra vez."
        if e.code == 429:
            return "Discord dice que se han enviado demasiados mensajes seguidos; se reintentará en el próximo aviso."
        return f"Discord respondió con un error ({e.code})."
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return f"No se pudo conectar con Discord: {getattr(e, 'reason', e)}"


def send_async(webhook: str, text: str, done: Callable[[Optional[str]], None]) -> None:
    """Envía en segundo plano; `done` recibe None o el error (se llama desde otro hilo)."""
    threading.Thread(target=lambda: done(send(webhook, text)), daemon=True).start()


def opportunities_message(new: List, catalog, fmt) -> str:
    """Mensaje con las mejores oportunidades nuevas (ya filtradas por los mínimos del usuario)."""
    best = sorted(new, key=lambda o: -(o.total_profit if o.total_profit is not None else o.profit))[:5]
    place = lambda c: "Mercado Negro" if c == "Black Market" else c
    lines = [f"🔔 **{len(new)} oportunidad(es) nueva(s)** en Albion"]
    for o in best:
        total = f", total ~{fmt(o.total_profit)}" if o.total_profit else ""
        lines.append(f"• **{catalog.name(o.item_id)}** ({catalog.label(o.item_id)}): {o.city} → {place(o.sell_city)} · "
                     f"compra {fmt(o.buy_price)}, vende {fmt(o.bm_price)} · **+{fmt(o.profit)}/ud. ({o.percent:.0f} %)**{total}")
    if len(new) > len(best):
        lines.append(f"…y {len(new) - len(best)} más en la app.")
    lines.append("_Comprueba el precio en el juego antes de comprar._")
    return "\n".join(lines)


def worth_notifying(o, cfg: dict, num) -> bool:
    total = o.total_profit if o.total_profit is not None else o.profit
    return o.percent >= num(cfg.get("min_pct", ""), 0) and total >= num(cfg.get("min_total", ""), 0)
