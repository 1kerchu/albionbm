"""Ventana de calculadoras (fabricación, refinado, venta manual y encantar) de la app de escritorio."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable, Dict, List, Optional

from . import calculators as K
from .api import fetch_prices, rows_to_prices
from .calc import QUALITY_NAMES
from .game import BLACK_MARKET, CITIES
from .items import norm

EQUIP = {"weapons", "armors", "head", "shoes", "offhands", "bags", "capes", "gathering"}
BM_LABEL = "Mercado Negro"


def fmt(n) -> str:
    return "—" if n is None else f"{round(n):,}".replace(",", ".")


def num(s: str, default: float = 0.0) -> float:
    try:
        return float(s.strip().replace(".", "").replace(",", ".")) if s.strip() else default
    except ValueError:
        return default


def run_async(app, job: Callable[[], object], done: Callable[[object, Optional[Exception]], None]) -> None:
    """Ejecuta `job` en segundo plano y entrega el resultado en el hilo de la interfaz
    (Tkinter no es seguro entre hilos: se pasa por la cola de la ventana principal)."""
    def work():
        try:
            result, error = job(), None
        except Exception as e:  # se muestra al usuario en `done`
            result, error = None, e
        app.events.put(("call", lambda: done(result, error)))

    threading.Thread(target=work, daemon=True).start()


class ItemPicker(ttk.Frame):
    """Buscador: escribes, eliges en la lista."""

    def __init__(self, parent, label: str, items: Callable[[], List[dict]], on_pick: Callable[[dict], None]):
        super().__init__(parent)
        self.items, self.on_pick, self.found = items, on_pick, []
        ttk.Label(self, text=label).pack(anchor="w")
        self.var = tk.StringVar()
        self.var.trace_add("write", lambda *a: self._search())
        ttk.Entry(self, textvariable=self.var).pack(fill="x")
        self.list = tk.Listbox(self, height=5, exportselection=False)
        self.list.pack(fill="x", pady=(2, 0))
        self.list.bind("<<ListboxSelect>>", self._select)

    def _search(self) -> None:
        q = norm(self.var.get().strip())
        self.list.delete(0, "end")
        self.found = []
        if len(q) < 2:
            return
        for it in self.items():
            if q in norm(it["es"]) or q in norm(it["en"]) or q in norm(it["id"]):
                self.found.append(it)
                self.list.insert("end", f"{it['es']}  (T{it['t']})")
                if len(self.found) >= 40:
                    break

    def _select(self, _e=None) -> None:
        sel = self.list.curselection()
        if sel:
            self.on_pick(self.found[sel[0]])


class PriceRows(ttk.Frame):
    """Tabla de materiales con precio editable."""

    def __init__(self, parent, on_change: Callable[[], None]):
        super().__init__(parent)
        self.on_change = on_change
        self.vars: Dict[str, tk.StringVar] = {}

    def build(self, rows: List[tuple]) -> None:
        """rows: [(id, nombre, cantidad, precio)]"""
        for w in self.winfo_children():
            w.destroy()
        self.vars = {}
        for c, (title, anchor) in enumerate([("Material", "w"), ("Cantidad", "e"), ("Precio/ud.", "e")]):
            ttk.Label(self, text=title, foreground="gray").grid(row=0, column=c, sticky=anchor, padx=4)
        for r, (mid, name, count, price) in enumerate(rows, 1):
            ttk.Label(self, text=name).grid(row=r, column=0, sticky="w", padx=4)
            ttk.Label(self, text=fmt(count)).grid(row=r, column=1, sticky="e", padx=4)
            var = tk.StringVar(value=str(round(price)) if price else "")
            var.trace_add("write", lambda *a: self.on_change())
            ttk.Entry(self, textvariable=var, width=12, justify="right").grid(row=r, column=2, sticky="e", padx=4, pady=1)
            self.vars[mid] = var
        self.columnconfigure(0, weight=1)

    def prices(self) -> Dict[str, float]:
        return {k: num(v.get()) for k, v in self.vars.items() if num(v.get()) > 0}

    def set_prices(self, prices: Dict[str, float]) -> None:
        for k, p in prices.items():
            if k in self.vars and p:
                self.vars[k].set(str(round(p)))


class CalculatorsWindow:
    def __init__(self, app):
        self.app = app
        self.data = K.load_recipes()
        self.win = tk.Toplevel(app.root)
        self.win.title("Calculadoras")
        self.win.geometry("780x780")
        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.craft_tab = CraftTab(nb, self, "craft")
        self.refine_tab = CraftTab(nb, self, "refine")
        nb.add(self.craft_tab.frame, text="Fabricación")
        nb.add(self.refine_tab.frame, text="Refinado")
        nb.add(TradeTab(nb, self).frame, text="Venta manual")
        nb.add(UpgradeTab(nb, self).frame, text="Encantar y mejorar")
        self.rank_tab = RankTab(nb, self)
        nb.add(self.rank_tab.frame, text="Ranking")

    def exists(self) -> bool:
        return bool(self.win.winfo_exists())

    # ---- utilidades compartidas
    def name(self, item_id: str) -> str:
        return self.data["names"].get(item_id) or self.app.catalog.name(item_id)

    def premium(self) -> bool:
        return self.app.premium_var.get()

    def price(self, item_id: str, location: str, kind: str, quality: int = 1) -> float:
        e = self._entries().get((item_id, quality, location, kind))
        return float(e[0]) if e else 0.0

    def _entries(self) -> dict:
        return self.app.store.load(self.app.effective_server(), 48)

    def fetch(self, ids: List[str], locations: List[str], qualities: List[int], status: tk.StringVar,
              done: Callable[[], None]) -> None:
        """Descarga precios de la API en segundo plano y los guarda en el almacén."""
        server = self.app.effective_server()
        status.set("Buscando precios…")

        def work():
            try:
                prices, stamps = rows_to_prices(fetch_prices(server, ids, locations, qualities))
                self.app.store.upsert(server, prices, source="api", timestamps=stamps)
                msg = "Precios actualizados. Los que falten, escríbelos a mano."
            except Exception as e:
                msg = f"Error: {e}. Puedes escribir los precios a mano."
            # Tkinter no es seguro entre hilos: el resultado se entrega por la cola de la ventana principal
            self.app.events.put(("call", lambda: (status.set(msg), done()) if self.exists() else None))

        threading.Thread(target=work, daemon=True).start()


class CraftTab:
    def __init__(self, parent, owner: CalculatorsWindow, kind: str):
        self.o, self.kind, self.item = owner, kind, None
        f = self.frame = ttk.Frame(parent, padding=10)
        cats = {"resources"} if kind == "refine" else EQUIP | {"consumables"}
        ItemPicker(f, "Recurso a refinar" if kind == "refine" else "Objeto a fabricar",
                   lambda: [i for i in owner.app.catalog.items if i["c"] in cats and i["id"] in owner.data["recipes"]],
                   self.pick).pack(fill="x")
        self.title = tk.StringVar(value="Elige un objeto en el buscador.")
        ttk.Label(f, textvariable=self.title, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(6, 4))

        g = ttk.Frame(f)
        g.pack(fill="x")
        self.ench = tk.StringVar(value="0")
        self.qty = tk.StringVar(value="1")
        self.buy = tk.StringVar(value="Lymhurst")
        self.sell = tk.StringVar(value="Lymhurst")
        self.mode = tk.StringVar(value="Orden de venta")
        self.city, self.focus = tk.BooleanVar(), tk.BooleanVar()
        self.rrr, self.fee = tk.StringVar(), tk.StringVar(value="500")
        self.sell_price = tk.StringVar()

        def field(row, col, label, widget):
            ttk.Label(g, text=label).grid(row=row, column=col * 2, sticky="w", padx=(0, 4), pady=2)
            widget.grid(row=row, column=col * 2 + 1, sticky="w", padx=(0, 14), pady=2)

        def combo(var, values, width=14):
            cb = ttk.Combobox(g, textvariable=var, values=values, state="readonly", width=width)
            cb.bind("<<ComboboxSelected>>", lambda e: self.reload())
            return cb

        if kind == "craft":
            field(0, 0, "Encantamiento", combo(self.ench, ["0", "1", "2", "3", "4"], 4))
        field(0, 1, "Nº de fabricaciones", ttk.Entry(g, textvariable=self.qty, width=8))
        field(1, 0, "Comprar materiales en", combo(self.buy, CITIES))
        field(1, 1, "Vender en", combo(self.sell, CITIES + [BM_LABEL]))
        field(2, 0, "Forma de venta", combo(self.mode, ["Orden de venta", "Venta rápida"]))
        ttk.Checkbutton(g, text="Ciudad con bonus", variable=self.city, command=self.update_rrr).grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(g, text="Usar foco", variable=self.focus, command=self.update_rrr).grid(row=3, column=2, columnspan=2, sticky="w")
        field(4, 0, "Retorno (%)", ttk.Entry(g, textvariable=self.rrr, width=8))
        field(4, 1, "Tasa del taller (por 100 nutrición)", ttk.Entry(g, textvariable=self.fee, width=8))

        self.status = tk.StringVar()
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=6)
        self.fetch_btn = ttk.Button(bar, text="Buscar precios en la API", command=self.fetch, state="disabled")
        self.fetch_btn.pack(side="left")
        ttk.Label(bar, textvariable=self.status, foreground="gray").pack(side="left", padx=8)

        self.rows = PriceRows(f, self.render)
        self.rows.pack(fill="x")
        sp = ttk.Frame(f)
        sp.pack(fill="x", pady=6)
        ttk.Label(sp, text="Precio de venta por unidad").pack(side="left")
        ttk.Entry(sp, textvariable=self.sell_price, width=12, justify="right").pack(side="left", padx=6)
        self.out = tk.Text(f, height=12, state="disabled", relief="flat", bg="#f4f4f4", font=("Consolas", 10))
        self.out.pack(fill="both", expand=True)
        self.out.tag_configure("good", foreground="#1d7a3a", font=("Segoe UI", 13, "bold"))
        self.out.tag_configure("bad", foreground="#b3261e", font=("Segoe UI", 13, "bold"))
        self.out.tag_configure("warn", foreground="#b26a00")
        for v in (self.qty, self.rrr, self.fee, self.sell_price):
            v.trace_add("write", lambda *a: self.render())
        self.update_rrr()

    # ---- estado
    def item_id(self) -> Optional[str]:
        if not self.item:
            return None
        e = int(self.ench.get() or 0)
        return self.item["id"] if self.item.get("f") or not e else f"{self.item['id']}@{e}"

    def recipe(self) -> Optional[dict]:
        return self.o.data["recipes"].get(self.item_id() or "")

    def sell_loc(self) -> str:
        return BLACK_MARKET if self.sell.get() == BM_LABEL else self.sell.get()

    def instant(self) -> bool:
        return self.mode.get() == "Venta rápida" or self.sell_loc() == BLACK_MARKET

    def update_rrr(self) -> None:
        self.rrr.set(f"{K.return_rate(self.kind, self.city.get(), self.focus.get()) * 100:.1f}".replace(".", ","))

    def pick(self, it: dict) -> None:
        self.item = it
        self.ench.set("0")
        self.fetch_btn.configure(state="normal")
        self.status.set("")
        self.reload()

    def reload(self) -> None:
        """Reconstruye los materiales con los precios que ya haya guardados."""
        r = self.recipe()
        iid = self.item_id()
        if not iid:
            return
        self.title.set(f"{self.o.app.catalog.name(iid)} ({self.o.app.catalog.label(iid)})")
        self.rows.build([(m, self.o.name(m) + ("" if ret else "  (no se devuelve)"), c,
                          self.o.price(m, self.buy.get(), "offer")) for m, c, ret in (r["m"] if r else [])])
        sp = self.o.price(iid, self.sell_loc(), "request" if self.instant() else "offer")
        self.sell_price.set(str(round(sp)) if sp else "")
        self.render()

    def fetch(self) -> None:
        r = self.recipe()
        if r:
            locs = sorted({self.buy.get(), self.sell_loc()})
            self.o.fetch([self.item_id()] + [m[0] for m in r["m"]], locs, [1], self.status, self.reload)

    def render(self) -> None:
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        r = self.recipe()
        if not self.item:
            pass
        elif not r:
            self.out.insert("end", "Este objeto no tiene receta con ese encantamiento.", "warn")
        else:
            qty = max(1, int(num(self.qty.get(), 1)))
            c = K.craft(r, self.o.data["values"], self.rows.prices(), num(self.sell_price.get()) or None,
                        rrr=num(self.rrr.get()) / 100, fee100=num(self.fee.get()), premium=self.o.premium(),
                        sell_order=not self.instant(), quantity=qty)
            if c["missing"]:
                self.out.insert("end", f"⚠ Faltan precios de {len(c['missing'])} material(es): completa la tabla.\n\n", "warn")
            elif c["unit_profit"] is not None:
                sign = "+" if c["total_profit"] > 0 else ""
                self.out.insert("end", f"{sign}{fmt(c['total_profit'])}  ({c['percent']:.1f} %)\n\n",
                                "good" if c["total_profit"] > 0 else "bad")
            else:
                self.out.insert("end", "Escribe el precio de venta para ver el beneficio.\n\n")
            lines = [("Materiales", c["gross"] * qty), ("Devuelto por retorno", -c["returned"] * qty),
                     ("Tasa del taller", c["fee"] * qty), ("Coste total", c["total_cost"]),
                     (f"Coste por unidad ({fmt(c['units'])} uds.)", c["unit_cost"])]
            if c["unit_revenue"] is not None:
                lines += [("Recibes por unidad (tras impuestos)", c["unit_revenue"]), ("Beneficio por unidad", c["unit_profit"])]
            if self.focus.get() and c["focus"]:
                lines.append(("Foco necesario", c["focus"]))
            for k, v in lines:
                self.out.insert("end", f"{k:<38}{fmt(v):>14}\n")
            if self.focus.get() and c["profit_per_focus"] is not None and not c["missing"]:
                self.out.insert("end", f"{'Beneficio por punto de foco':<38}{c['profit_per_focus']:>14.1f}\n")
        self.out.configure(state="disabled")


class TradeTab:
    def __init__(self, parent, owner: CalculatorsWindow):
        self.o = owner
        f = self.frame = ttk.Frame(parent, padding=10)
        self.buy, self.sell, self.qty = tk.StringVar(), tk.StringVar(), tk.StringVar(value="1")
        self.buy_order, self.sell_order = tk.BooleanVar(), tk.BooleanVar()
        for label, var in [("Precio de compra", self.buy), ("Precio de venta", self.sell), ("Cantidad", self.qty)]:
            row = ttk.Frame(f)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=20).pack(side="left")
            ttk.Entry(row, textvariable=var, width=14, justify="right").pack(side="left")
            var.trace_add("write", lambda *a: self.render())
        ttk.Checkbutton(f, text="Compro con orden de compra (+2,5 %)", variable=self.buy_order, command=self.render).pack(anchor="w")
        ttk.Checkbutton(f, text="Vendo con orden de venta (+2,5 %)", variable=self.sell_order, command=self.render).pack(anchor="w")
        ttk.Label(f, text="El prémium se coge de la ventana principal.", foreground="gray").pack(anchor="w", pady=(4, 8))
        self.out = tk.Text(f, height=10, state="disabled", relief="flat", bg="#f4f4f4", font=("Consolas", 10))
        self.out.pack(fill="x")
        self.out.tag_configure("good", foreground="#1d7a3a", font=("Segoe UI", 13, "bold"))
        self.out.tag_configure("bad", foreground="#b3261e", font=("Segoe UI", 13, "bold"))
        self.render()

    def render(self) -> None:
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        buy, sell = num(self.buy.get()), num(self.sell.get())
        if buy <= 0 or sell <= 0:
            self.out.insert("end", "Escribe el precio de compra y el de venta.")
        else:
            t = K.trade(buy, sell, max(1, int(num(self.qty.get(), 1))), premium=self.o.premium(),
                        buy_order=self.buy_order.get(), sell_order=self.sell_order.get())
            self.out.insert("end", f"{'+' if t['total_profit'] > 0 else ''}{fmt(t['total_profit'])}  ({t['percent']:.1f} %)\n\n",
                            "good" if t["total_profit"] > 0 else "bad")
            for k, v in [("Coste por unidad", t["unit_cost"]), ("Recibes por unidad", t["unit_revenue"]),
                         ("Beneficio por unidad", t["unit_profit"]), ("Impuestos y tasas por unidad", t["fees"]),
                         ("Inversión total", t["total_cost"]),
                         ("Precio de venta mínimo para no perder", -(-t["breakeven"] // 1))]:
                self.out.insert("end", f"{k:<40}{fmt(v):>14}\n")
        self.out.configure(state="disabled")


class UpgradeTab:
    def __init__(self, parent, owner: CalculatorsWindow):
        self.o, self.item = owner, None
        f = self.frame = ttk.Frame(parent, padding=10)
        ItemPicker(f, "Objeto a mejorar",
                   lambda: [i for i in owner.app.catalog.items if i["c"] in EQUIP and i["id"] in owner.data["upgrades"]],
                   self.pick).pack(fill="x")
        self.title = tk.StringVar(value="Elige un objeto en el buscador.")
        ttk.Label(f, textvariable=self.title, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(6, 4))
        g = ttk.Frame(f)
        g.pack(fill="x")
        self.frm, self.to = tk.StringVar(value=".0"), tk.StringVar(value=".1")
        self.qual, self.city = tk.StringVar(value=QUALITY_NAMES[1]), tk.StringVar(value="Lymhurst")
        for i, (label, var, values) in enumerate([("Desde", self.frm, [".0", ".1", ".2"]), ("Hasta", self.to, [".1", ".2", ".3"]),
                                                  ("Calidad", self.qual, list(QUALITY_NAMES.values())), ("Ciudad", self.city, CITIES)]):
            ttk.Label(g, text=label).grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=(0, 4), pady=2)
            cb = ttk.Combobox(g, textvariable=var, values=values, state="readonly", width=14)
            cb.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(0, 14))
            cb.bind("<<ComboboxSelected>>", lambda e: self.reload())
        self.status = tk.StringVar()
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=6)
        self.fetch_btn = ttk.Button(bar, text="Buscar precios en la API", command=self.fetch, state="disabled")
        self.fetch_btn.pack(side="left")
        ttk.Label(bar, textvariable=self.status, foreground="gray").pack(side="left", padx=8)
        self.rows = PriceRows(f, self.render)
        self.rows.pack(fill="x")
        self.base, self.target = tk.StringVar(), tk.StringVar()
        for label, var in [("Precio del objeto sin mejorar", self.base), ("Precio comprándolo ya mejorado", self.target)]:
            row = ttk.Frame(f)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=32).pack(side="left")
            ttk.Entry(row, textvariable=var, width=14, justify="right").pack(side="left")
            var.trace_add("write", lambda *a: self.render())
        self.out = tk.Text(f, height=8, state="disabled", relief="flat", bg="#f4f4f4", font=("Consolas", 10))
        self.out.pack(fill="x", pady=(8, 0))
        self.out.tag_configure("good", foreground="#1d7a3a", font=("Segoe UI", 13, "bold"))
        self.out.tag_configure("bad", foreground="#b3261e", font=("Segoe UI", 13, "bold"))
        self.out.tag_configure("warn", foreground="#b26a00")

    def levels(self):
        return int(self.frm.get()[1]), int(self.to.get()[1])

    def quality(self) -> int:
        return next(q for q, n in QUALITY_NAMES.items() if n == self.qual.get())

    def vid(self, lvl: int) -> str:
        return f"{self.item['id']}@{lvl}" if lvl else self.item["id"]

    def steps(self) -> list:
        a, b = self.levels()
        return self.o.data["upgrades"][self.item["id"]][a:b] if self.item else []

    def pick(self, it: dict) -> None:
        self.item = it
        self.fetch_btn.configure(state="normal")
        self.status.set("")
        self.reload()

    def reload(self) -> None:
        if not self.item:
            return
        a, b = self.levels()
        self.title.set(f"{self.item['es']} (T{self.item['t']}) · de .{a} a .{b}")
        city, q = self.city.get(), self.quality()
        self.rows.build([(r, f"{self.o.name(r)}  (a .{a + i + 1})", c, self.o.price(r, city, "offer"))
                         for i, (r, c) in enumerate(self.steps())])
        for var, lvl in ((self.base, a), (self.target, b)):
            p = self.o.price(self.vid(lvl), city, "offer", q)
            var.set(str(round(p)) if p else "")
        self.render()

    def fetch(self) -> None:
        a, b = self.levels()
        if self.item and b > a:
            self.o.fetch([self.vid(a), self.vid(b)] + [s[0] for s in self.steps()], [self.city.get()],
                         sorted({1, self.quality()}), self.status, self.reload)

    def render(self) -> None:
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        if self.item:
            a, b = self.levels()
            if b <= a:
                self.out.insert("end", "«Hasta» debe ser mayor que «Desde».", "warn")
            else:
                try:
                    u = K.upgrade(self.o.data["upgrades"][self.item["id"]], a, b, num(self.base.get()) or None,
                                  self.rows.prices(), num(self.target.get()) or None)
                except ValueError as e:
                    u = None
                    self.out.insert("end", str(e), "warn")
                if u:
                    if u["missing"]:
                        self.out.insert("end", "⚠ Faltan precios: el total está incompleto.\n\n", "warn")
                    elif u["saving"] is not None and u["saving"] > 0:
                        self.out.insert("end", f"Mejorar ahorra {fmt(u['saving'])}\n\n", "good")
                    elif u["saving"] is not None:
                        self.out.insert("end", f"Sale más barato comprarlo hecho ({fmt(-u['saving'])} menos)\n\n", "bad")
                    for k, v in [("Coste de los recursos", u["upgrade_cost"]), ("Objeto sin mejorar + recursos", u["total"]),
                                 ("Comprarlo ya mejorado", u["direct"])]:
                        self.out.insert("end", f"{k:<34}{fmt(v):>14}\n")
        self.out.configure(state="disabled")


class RankTab:
    """Ranking: qué fabricar o refinar da más beneficio, repasando todas las recetas."""

    TYPES = {"Fabricar equipo": (EQUIP, "craft"), "Fabricar consumibles": ({"consumables"}, "craft"),
             "Refinar recursos": ({"resources"}, "refine")}
    SORTS = {"Mayor %": "percent", "Mayor beneficio/ud.": "unit_profit", "Mayor beneficio por foco": "profit_per_focus"}

    def __init__(self, parent, owner: CalculatorsWindow):
        self.o, self.ids = owner, None
        f = self.frame = ttk.Frame(parent, padding=10)
        g = ttk.Frame(f)
        g.pack(fill="x")
        self.type = tk.StringVar(value="Fabricar equipo")
        self.sort = tk.StringVar(value="Mayor %")
        self.buy, self.sell = tk.StringVar(value="Lymhurst"), tk.StringVar(value="Lymhurst")
        self.mode = tk.StringVar(value="Orden de venta")
        self.city, self.focus, self.fee = tk.BooleanVar(), tk.BooleanVar(), tk.StringVar(value="500")
        for i, (label, var, values, reset) in enumerate([
                ("Qué", self.type, list(self.TYPES), True), ("Ordenar por", self.sort, list(self.SORTS), False),
                ("Comprar materiales en", self.buy, CITIES, True), ("Vender en", self.sell, CITIES + [BM_LABEL], True),
                ("Forma de venta", self.mode, ["Orden de venta", "Venta rápida"], False)]):
            ttk.Label(g, text=label).grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=(0, 4), pady=2)
            cb = ttk.Combobox(g, textvariable=var, values=values, state="readonly", width=24)
            cb.grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(0, 14))
            cb.bind("<<ComboboxSelected>>", (lambda e: self.reset()) if reset else (lambda e: self.render()))
        ttk.Label(g, text="Tasa del taller (por 100 nutrición)").grid(row=2, column=2, sticky="w")
        ttk.Entry(g, textvariable=self.fee, width=8).grid(row=2, column=3, sticky="w")
        self.fee.trace_add("write", lambda *a: self.render())
        ttk.Checkbutton(g, text="Ciudad con bonus", variable=self.city, command=self.render).grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(g, text="Usar foco", variable=self.focus, command=self.render).grid(row=3, column=2, columnspan=2, sticky="w")
        ttk.Label(f, foreground="gray", wraplength=720, justify="left", text=(
            "Usa los tiers y encantamientos marcados en la ventana principal. Precios de calidad Normal. El bonus de "
            "ciudad se aplica a todo por igual: en el juego cada ciudad solo lo da a ciertos objetos.")).pack(anchor="w", pady=4)
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=4)
        self.btn = ttk.Button(bar, text="Calcular ranking", command=self.run)
        self.btn.pack(side="left")
        self.status = tk.StringVar()
        ttk.Label(bar, textvariable=self.status, foreground="gray").pack(side="left", padx=8)
        cols = [("name", "Objeto", 250, "w"), ("tier", "Tier", 50, "center"), ("cost", "Coste/ud.", 85, "e"),
                ("sell", "Venta", 85, "e"), ("profit", "Benef./ud.", 85, "e"), ("pct", "%", 65, "e"),
                ("focus", "Foco", 60, "e"), ("ppf", "Benef./foco", 80, "e")]
        box = ttk.Frame(f)
        box.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(box, columns=[c[0] for c in cols], show="headings")
        for key, title, width, anchor in cols:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor, stretch=key == "name")
        vs = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")

    def sell_loc(self) -> str:
        return BLACK_MARKET if self.sell.get() == BM_LABEL else self.sell.get()

    def reset(self) -> None:
        self.ids = None
        self.tree.delete(*self.tree.get_children())
        self.status.set("")

    def run(self) -> None:
        f = self.o.app._read_filters()
        cats, _ = self.TYPES[self.type.get()]
        recipes = self.o.data["recipes"]
        ids = [i for i in self.o.app.catalog.variant_ids(cats, f["tiers"], f["enchs"]) if i in recipes]
        if not ids:
            self.status.set("No hay recetas con los tiers y encantamientos marcados.")
            return
        mats = sorted({m[0] for i in ids for m in recipes[i]["m"]})
        self.btn.configure(state="disabled")
        self.status.set(f"Descargando precios de {fmt(len(ids))} objetos y {fmt(len(mats))} materiales…")
        server, buy, sell = self.o.app.effective_server(), self.buy.get(), self.sell_loc()

        def job():
            for group, loc in ((ids, sell), (mats, buy)):
                prices, stamps = rows_to_prices(fetch_prices(server, group, [loc], [1]))
                self.o.app.store.upsert(server, prices, source="api", timestamps=stamps)

        def done(_result, error):
            if not self.o.exists():
                return
            self.btn.configure(state="normal")
            if error:
                self.status.set(f"Error: {error}")
            else:
                self.ids = ids
                self.render()

        run_async(self.o.app, job, done)

    def render(self) -> None:
        if not self.ids:
            return
        entries = self.o._entries()  # una sola lectura del almacén para todo el ranking
        buy, sell = self.buy.get(), self.sell_loc()
        instant = self.mode.get() == "Venta rápida" or sell == BLACK_MARKET
        price = lambda i, loc, kind: float((entries.get((i, 1, loc, kind)) or (0,))[0])
        kind = self.TYPES[self.type.get()][1]
        rows = K.rank(self.o.data["recipes"], self.o.data["values"], self.ids,
                      lambda m: price(m, buy, "offer"), lambda i: price(i, sell, "request" if instant else "offer"),
                      rrr=K.return_rate(kind, self.city.get(), self.focus.get()), fee100=num(self.fee.get()),
                      premium=self.o.premium(), sell_order=not instant)
        key = self.SORTS[self.sort.get()]
        rows.sort(key=lambda r: -(r[key] if r[key] is not None else float("-inf")))
        self.tree.delete(*self.tree.get_children())
        cat = self.o.app.catalog
        for r in rows[:300]:
            self.tree.insert("", "end", values=(
                cat.name(r["id"]), cat.label(r["id"]), fmt(r["unit_cost"]), fmt(r["sell_price"]), fmt(r["unit_profit"]),
                f"{r['percent']:.1f} %", fmt(r["focus"]),
                f"{r['profit_per_focus']:.1f}" if r["profit_per_focus"] is not None else "—"))
        self.status.set(f"{fmt(len(rows))} de {fmt(len(self.ids))} recetas tienen todos los precios. "
                        "Comprueba que el objeto se vende antes de fabricar mucho.")
