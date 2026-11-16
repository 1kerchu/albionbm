#!/usr/bin/env python3
"""Genera data/recipes.json con las recetas de fabricación, refinado y mejora de encantamiento.

Uso:
  python3 scripts/build_recipes.py RUTA/items.json RUTA/formatted_items.json
(mismas fuentes que scripts/build_items.py; ejecútalo después de build_items.py)

Formato:
  recipes:  { id: {"m": [[material, cantidad, se_devuelve(0/1)], ...], "f": foco, "n": unidades por fabricación} }
            El id es el de la API (T4_2H_AXE@1, T4_PLANKS_LEVEL1@1...). Solo la primera receta de cada objeto.
  upgrades: { id_base: [[recurso, cantidad] para .1, .2, .3, .4] }   (runas, almas, reliquias...)
  values:   { material: valor de objeto }   (para la tasa del taller)
  names:    { material: nombre en español } (materiales que no están en items.json)
"""
import json, sys, os

raw, fmt = sys.argv[1], sys.argv[2]
items = json.load(open(raw, encoding="utf-8"))["items"]
here = os.path.dirname(os.path.abspath(__file__))
catalog = {i["id"] for i in json.load(open(os.path.join(here, "..", "data", "items.json"), encoding="utf-8"))}

names, full = {}, {}
for it in json.load(open(fmt, encoding="utf-8")):
    u = it["UniqueName"]
    ln = it.get("LocalizedNames") or {}
    names[u] = ln.get("ES-ES") or ln.get("EN-US") or u
    full.setdefault(u.split("@")[0], []).append(u)


def api_id(name, ench=0):
    """Nombre interno -> id de la API (T4_PLANKS_LEVEL1 -> T4_PLANKS_LEVEL1@1; T4_BAG + 2 -> T4_BAG@2)."""
    variants = full.get(name, [name])
    if ench and f"{name}@{ench}" in variants:
        return f"{name}@{ench}"
    if name in variants:
        return name
    return variants[0]


def first(req):
    return req[0] if isinstance(req, list) else req


def as_list(x):
    return x if isinstance(x, list) else [x]


values = {}
for kind, lst in items.items():
    if isinstance(lst, list):
        for it in lst:
            if isinstance(it, dict) and it.get("@itemvalue"):
                values[api_id(it["@uniquename"])] = float(it["@itemvalue"])


def recipe(req):
    req = first(req)
    if not req or "craftresource" not in req:
        return None
    mats = []
    for r in as_list(req["craftresource"]):
        mid = api_id(r["@uniquename"])
        mats.append([mid, int(r["@count"]), 0 if r.get("@maxreturnamount") == "0" else 1])
    return {"m": mats, "f": int(float(req.get("@craftingfocus", 0) or 0)), "n": int(req.get("@amountcrafted", 1) or 1)}


recipes, upgrades = {}, {}
EQUIP = ("weapon", "equipmentitem", "transformationweapon")
for kind in EQUIP + ("consumableitem",):
    for it in items.get(kind, []):
        uid = it["@uniquename"]
        if uid not in catalog and api_id(uid) not in catalog:
            continue
        r = recipe(it.get("craftingrequirements"))
        if r:
            recipes[api_id(uid)] = r
        ups = []
        for e in as_list((it.get("enchantments") or {}).get("enchantment", [])):
            lvl = int(e["@enchantmentlevel"])
            er = recipe(e.get("craftingrequirements"))
            if er:
                recipes[api_id(uid, lvl)] = er
            up = (e.get("upgraderequirements") or {}).get("upgraderesource")
            if up and kind in EQUIP:
                up = first(up)
                ups.append([api_id(up["@uniquename"]), int(up["@count"])])
        if ups:
            upgrades[uid] = ups

for it in items.get("simpleitem", []):
    if it.get("@shopsubcategory1") == "refinedresources" and int(it.get("@tier", 0)) >= 3:
        r = recipe(it.get("craftingrequirements"))
        if r:
            recipes[api_id(it["@uniquename"])] = r

used = {m[0] for r in recipes.values() for m in r["m"]} | {u[0] for ups in upgrades.values() for u in ups}
used |= {k for k in recipes if k.split("@")[0] not in catalog and k not in catalog}
out = {
    "recipes": recipes, "upgrades": upgrades,
    "values": {k: values[k] for k in sorted(used) if k in values},
    "names": {k: names.get(k, k) for k in sorted(used)},
}
dst = os.path.join(here, "..", "data", "recipes.json")
with open(dst, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(len(recipes), "recetas,", len(upgrades), "mejoras,", len(used), "materiales ->", dst, os.path.getsize(dst) // 1024, "KB")
