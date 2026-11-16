#!/usr/bin/env python3
"""Genera data/items.json con los objetos que compra el Mercado Negro.

Uso:
  python3 scripts/build_items.py RUTA/items.json RUTA/formatted_items.json
Fuentes (ao-data/ao-bin-dumps):
  https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/items.json
  https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.json
"""
import json, sys, os

CATS = {"weapons", "armors", "head", "shoes", "offhands", "bags", "capes", "gathering"}
KINDS = ("weapon", "equipmentitem", "transformationweapon")

raw, fmt = sys.argv[1], sys.argv[2]
items = json.load(open(raw, encoding="utf-8"))["items"]
names = {}
for it in json.load(open(fmt, encoding="utf-8")):
    ln = it.get("LocalizedNames") or {}
    names[it["UniqueName"]] = (ln.get("ES-ES") or ln.get("EN-US"), ln.get("EN-US"))

out = []
for kind in KINDS:
    for it in items.get(kind, []):
        cat, sub = it.get("@shopcategory"), it.get("@shopsubcategory1")
        uid = it["@uniquename"]
        tier = int(it.get("@tier", 0))
        if cat not in CATS or sub in (None, "other") or tier < 4 or not uid.startswith("T"):
            continue
        if "VANITY" in uid or "ARENA" in uid:
            continue
        ench = it.get("enchantments", {}).get("enchantment", [])
        if isinstance(ench, dict):
            ench = [ench]
        levels = [0] + sorted(int(e["@enchantmentlevel"]) for e in ench if int(e["@enchantmentlevel"]) <= 4)
        es, en = names.get(uid, (uid, uid))
        out.append({"id": uid, "es": es, "en": en, "c": cat, "s": sub, "t": tier, "e": levels,
                    "w": float(it.get("@weight", 0) or 0)})

# Mercancías que no compra el Mercado Negro pero sirven para comerciar entre ciudades.
EXTRA = {("simpleitem", "crafting", "refinedresources"): "resources", ("simpleitem", "crafting", "resources"): "resources",
         ("consumableitem", "consumables", "food"): "consumables", ("consumableitem", "consumables", "potions"): "consumables"}
extra_base = {}
for kind in ("simpleitem", "consumableitem", "mount"):
    for it in items.get(kind, []):
        cat, sub = it.get("@shopcategory"), it.get("@shopsubcategory1")
        mine = EXTRA.get((kind, cat, sub))
        if kind == "simpleitem" and cat == "artefacts":
            mine = "artefacts"
        if kind == "mount" and cat == "mounts":
            mine = "mounts"
        uid = it["@uniquename"]
        if mine and uid.startswith("T") and int(it.get("@tier", 0)) >= 4:
            extra_base[uid] = (mine, sub, int(it["@tier"]), float(it.get("@weight", 0) or 0))
for it in json.load(open(fmt, encoding="utf-8")):
    full = it["UniqueName"]
    b = extra_base.get(full.split("@")[0])
    if not b or not it.get("LocalizedNames"):
        continue
    es, en = names[full]
    ench = int(full.split("@")[1]) if "@" in full else 0
    # "f": el id ya es el id completo de la API (p. ej. T4_PLANKS_LEVEL1@1)
    out.append({"id": full, "es": es, "en": en, "c": b[0], "s": b[1], "t": b[2], "e": [ench], "w": b[3], "f": 1})

out.sort(key=lambda x: (x["c"], x["s"], x["id"]))
dst = os.path.join(os.path.dirname(__file__), "..", "data", "items.json")
with open(dst, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(len(out), "objetos base,", sum(len(x["e"]) for x in out), "variantes ->", dst)
