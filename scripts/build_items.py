#!/usr/bin/env python3
"""Genera data/items.js con los objetos que compra el Mercado Negro.

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
        out.append({"id": uid, "es": es, "en": en, "c": cat, "s": sub, "t": tier, "e": levels})

out.sort(key=lambda x: (x["c"], x["s"], x["id"]))
dst = os.path.join(os.path.dirname(__file__), "..", "data", "items.js")
with open(dst, "w", encoding="utf-8") as f:
    # Se guarda como .js para que index.html funcione abierto con doble clic (sin servidor).
    f.write("// Generado por scripts/build_items.py - no editar a mano\n")
    f.write("window.ALBION_ITEMS = ")
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    f.write(";\n")
print(len(out), "objetos base,", sum(len(x["e"]) for x in out), "variantes ->", dst)
