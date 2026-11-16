"""Catálogo de objetos que compra el Mercado Negro (data/items.json)."""
from __future__ import annotations

import json
import os
import sys
import unicodedata
from typing import Dict, List

CATEGORY_NAMES = {
    "weapons": "Armas", "armors": "Armaduras", "head": "Cascos", "shoes": "Botas",
    "offhands": "Secundarias", "bags": "Bolsas", "capes": "Capas", "gathering": "Recolección",
    # Estas no las compra el Mercado Negro: sirven para comerciar entre ciudades
    "resources": "Recursos", "consumables": "Consumibles", "mounts": "Monturas", "artefacts": "Artefactos",
}
NOT_BLACK_MARKET = {"resources", "consumables", "mounts", "artefacts"}


def _data_path() -> str:
    # Compatible con PyInstaller (los datos se copian junto al ejecutable)
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    return os.path.join(base, "data", "items.json")


def load_items() -> List[dict]:
    with open(_data_path(), encoding="utf-8") as f:
        return json.load(f)


def norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


class Catalog:
    def __init__(self, items: List[dict]):
        self.items = items
        self.by_id: Dict[str, dict] = {i["id"]: i for i in items}

    def base(self, item_id: str) -> dict:
        # Recursos y consumibles se guardan con su id completo (T4_PLANKS_LEVEL1@1); el equipo, por id base.
        return self.by_id.get(item_id) or self.by_id.get(item_id.split("@")[0], {})

    def weight(self, item_id: str) -> float:
        return float(self.base(item_id).get("w") or 0.0)

    def name(self, item_id: str) -> str:
        return self.base(item_id).get("es", item_id)

    def label(self, item_id: str) -> str:
        b = self.base(item_id)
        ench = item_id.split("@")[1] if "@" in item_id else "0"
        return f"T{b.get('t', '?')}.{ench}"

    def matches(self, item_id: str, cats, tiers, enchs, search: str) -> bool:
        b = self.base(item_id)
        if not b:
            return False
        ench = int(item_id.split("@")[1]) if "@" in item_id else 0
        if b["c"] not in cats or b["t"] not in tiers or ench not in enchs:
            return False
        if search:
            q = norm(search)
            return q in norm(b["es"]) or q in norm(b["en"]) or q in norm(b["id"])
        return True

    def variant_ids(self, cats, tiers, enchs, search: str = "") -> List[str]:
        out = []
        q = norm(search) if search else ""
        for it in self.items:
            if it["c"] not in cats or it["t"] not in tiers:
                continue
            if q and q not in norm(it["es"]) and q not in norm(it["en"]) and q not in norm(it["id"]):
                continue
            for e in it["e"]:
                if e in enchs:
                    out.append(it["id"] if it.get("f") or not e else f"{it['id']}@{e}")
        return out
