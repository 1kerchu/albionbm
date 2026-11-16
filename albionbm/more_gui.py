"""Ventana «Más» de la app de escritorio: favoritos con avisos de precio, historial de precios
y registro de ganancias. Mismas funciones que la pestaña «Más» de la versión web."""
from __future__ import annotations

import json
import os
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional

from . import calculators as K
from .api import fetch_history, fetch_prices, history_series, rows_to_prices, week_summary
from .calc import QUALITY_NAMES
from .calc_gui import ItemPicker, fmt, num, run_async
from .export import export_dir
from .game import BLACK_MARKET, CITIES
from .items import NOT_BLACK_MARKET
from .store import default_db_path

QUALITIES = list(QUALITY_NAMES.values())
# Colores categóricos validados para daltonismo, uno fijo por ciudad (mismo orden que la web)
CITY_COLORS = dict(zip(CITIES + [BLACK_MARKET],
                       ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]))
CHECK_EVERY_MS = 10 * 60 * 1000


def city_label(c: str) -> str:
    return "Mercado Negro" if c == BLACK_MARKET else c


def data_file(name: str) -> str:
    return os.path.join(os.path.dirname(default_db_path()), name)


def load_json(name: str, default):
    try:
        with open(data_file(name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(name: str, value) -> None:
    try:
        with open(data_file(name), "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def quality_of(name: str) -> int:
    return next(q for q, n in QUALITY_NAMES.items() if n == name)


class MoreWindow:
    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title("Favoritos, historial y ganancias")
        self.win.geometry("860x800")
        self.nb = ttk.Notebook(self.win)
        self.nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.hist = HistoryTab(self.nb, self)
        self.favs = FavoritesTab(self.nb, self)
        self.ledger = LedgerTab(self.nb, self)
        self.nb.add(self.favs.frame, text="Favoritos y avisos")
        self.nb.add(self.hist.frame, text="Historial de precios")
        self.nb.add(self.ledger.frame, text="Registro de ganancias")

    def exists(self) -> bool:
        return bool(self.win.winfo_exists())

    def cities(self) -> List[str]:
        return self.app._read_filters()["cities"]


# ---------------------------------------------------------------------------- favoritos

class FavoritesTab:
    def __init__(self, parent, owner: MoreWindow):
        self.o = owner
        self.favs = load_json("favoritos.json", [])  # [{id, quality, kind: "below"|"above", target}]
        self.hits: set = set()
        self.auto_job = None
        f = self.frame = ttk.Frame(parent, padding=10)

        add = ttk.Frame(f)
        add.pack(fill="x")
        ItemPicker(add, "Añadir objeto (elige encantamiento y calidad, y luego el objeto)",
                   lambda: owner.app.catalog.items, self.add).pack(side="left", fill="x", expand=True)
        side = ttk.Frame(add)
        side.pack(side="left", padx=(10, 0), anchor="n")
        self.ench, self.qual = tk.StringVar(value="0"), tk.StringVar(value=QUALITIES[0])
        ttk.Label(side, text="Encantamiento").pack(anchor="w")
        ttk.Combobox(side, textvariable=self.ench, values=["0", "1", "2", "3", "4"], state="readonly", width=12).pack()
        ttk.Label(side, text="Calidad").pack(anchor="w", pady=(4, 0))
        ttk.Combobox(side, textvariable=self.qual, values=QUALITIES, state="readonly", width=12).pack()

        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=8)
        self.btn = ttk.Button(bar, text="Comprobar precios ahora", command=self.check)
        self.btn.pack(side="left")
        self.auto = tk.BooleanVar()
        ttk.Checkbutton(bar, text="Comprobar sola cada 10 min", variable=self.auto, command=self.set_auto).pack(side="left", padx=10)
        self.status = tk.StringVar()
        ttk.Label(bar, textvariable=self.status, foreground="gray").pack(side="left")

        cols = [("name", "Objeto", 220, "w"), ("tier", "Tier", 45, "center"), ("qual", "Calidad", 85, "w"),
                ("min", "Más barato", 85, "e"), ("minc", "En", 90, "w"), ("max", "Más caro", 85, "e"),
                ("maxc", "En", 90, "w"), ("alert", "Aviso", 120, "w")]
        self.tree = ttk.Treeview(f, columns=[c[0] for c in cols], show="headings", selectmode="browse", height=12)
        for key, title, width, anchor in cols:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor, stretch=key == "name")
        self.tree.pack(fill="both", expand=True)
        self.tree.tag_configure("hit", background="#e7f6ea")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.show_selected())

        edit = ttk.LabelFrame(f, text="Aviso del favorito seleccionado", padding=6)
        edit.pack(fill="x", pady=(8, 0))
        self.kind, self.target = tk.StringVar(value="Avísame si baja de"), tk.StringVar()
        ttk.Combobox(edit, textvariable=self.kind, values=["Avísame si baja de", "Avísame si sube de"],
                     state="readonly", width=20).pack(side="left")
        ttk.Entry(edit, textvariable=self.target, width=12, justify="right").pack(side="left", padx=6)
        ttk.Button(edit, text="Guardar aviso", command=self.save_alert).pack(side="left")
        ttk.Button(edit, text="Ver historial", command=self.open_history).pack(side="left", padx=6)
        ttk.Button(edit, text="Quitar", command=self.remove).pack(side="right")
        self.render()

    # ---- datos
    def add(self, it: dict) -> None:
        ench = int(self.ench.get())
        item_id = it["id"] if it.get("f") or not ench else f"{it['id']}@{ench}"
        if ench and not it.get("f") and ench not in it["e"]:
            self.status.set("Ese objeto no existe con ese encantamiento.")
            return
        q = quality_of(self.qual.get())
        if any(x["id"] == item_id and x["quality"] == q for x in self.favs):
            self.status.set("Ya está en favoritos.")
            return
        self.favs.insert(0, {"id": item_id, "quality": q, "kind": "below", "target": 0})
        save_json("favoritos.json", self.favs)
        self.status.set(f"Añadido: {self.o.app.catalog.name(item_id)}")
        self.render()

    def prices(self, fav: dict, entries: dict):
        lo = hi = None
        for city in self.o.cities():
            e = entries.get((fav["id"], fav["quality"], city, "offer"))
            if not e:
                continue
            if lo is None or e[0] < lo[0]:
                lo = (e[0], city)
            if hi is None or e[0] > hi[0]:
                hi = (e[0], city)
        return lo, hi

    @staticmethod
    def is_hit(fav: dict, lo, hi) -> bool:
        if not fav.get("target"):
            return False
        return bool(lo and lo[0] <= fav["target"]) if fav["kind"] == "below" else bool(hi and hi[0] >= fav["target"])

    def selected(self) -> Optional[int]:
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    # ---- interfaz
    def render(self) -> List[str]:
        entries = self.o.app.store.load(self.o.app.effective_server(), 48)
        keep = self.selected()
        self.tree.delete(*self.tree.get_children())
        cat, hits = self.o.app.catalog, []
        for i, fav in enumerate(self.favs):
            lo, hi = self.prices(fav, entries)
            hit = self.is_hit(fav, lo, hi)
            if hit:
                hits.append(f"{fav['id']}|{fav['quality']}")
            alert = "—" if not fav.get("target") else f"{'baja de' if fav['kind'] == 'below' else 'sube de'} {fmt(fav['target'])}"
            self.tree.insert("", "end", iid=str(i), tags=("hit",) if hit else (), values=(
                cat.name(fav["id"]), cat.label(fav["id"]), QUALITY_NAMES[fav["quality"]],
                fmt(lo[0]) if lo else "—", lo[1] if lo else "—", fmt(hi[0]) if hi else "—", hi[1] if hi else "—",
                ("✔ " if hit else "") + alert))
        if keep is not None and keep < len(self.favs):
            self.tree.selection_set(str(keep))
        return hits

    def show_selected(self) -> None:
        i = self.selected()
        if i is not None:
            fav = self.favs[i]
            self.kind.set("Avísame si baja de" if fav["kind"] == "below" else "Avísame si sube de")
            self.target.set(str(fav["target"]) if fav.get("target") else "")

    def save_alert(self) -> None:
        i = self.selected()
        if i is None:
            self.status.set("Selecciona un favorito de la lista.")
            return
        self.favs[i]["kind"] = "below" if self.kind.get().endswith("baja de") else "above"
        self.favs[i]["target"] = int(num(self.target.get()))
        save_json("favoritos.json", self.favs)
        self.render()

    def remove(self) -> None:
        i = self.selected()
        if i is not None:
            del self.favs[i]
            save_json("favoritos.json", self.favs)
            self.render()

    def open_history(self) -> None:
        i = self.selected()
        if i is not None:
            self.o.nb.select(self.o.hist.frame)
            self.o.hist.show(self.favs[i]["id"], self.favs[i]["quality"])

    def check(self, auto: bool = False) -> None:
        cities = self.o.cities()
        if not self.favs or not cities:
            self.status.set("Añade algún favorito y marca alguna ciudad en la ventana principal.")
            return
        app, server = self.o.app, self.o.app.effective_server()
        ids = sorted({x["id"] for x in self.favs})
        quals = sorted({x["quality"] for x in self.favs})
        self.btn.configure(state="disabled")
        self.status.set("Buscando precios…")

        def job():
            prices, stamps = rows_to_prices(fetch_prices(server, ids, cities, quals))
            app.store.upsert(server, prices, source="api", timestamps=stamps)

        def done(_r, error):
            if not self.o.exists():
                return
            self.btn.configure(state="normal")
            if error:
                self.status.set(f"Error: {error}")
                return
            hits = set(self.render())
            fresh = hits - self.hits
            self.hits = hits
            self.status.set("Comprobado a las " + time.strftime("%H:%M") + ".")
            if fresh:
                names = ", ".join(app.catalog.name(h.split("|")[0]) for h in sorted(fresh)[:3])
                app.root.bell()
                app._log(f"🔔 {len(fresh)} aviso(s) de precio: {names}")

        run_async(app, job, done)

    def set_auto(self) -> None:
        if self.auto_job:
            self.o.win.after_cancel(self.auto_job)
            self.auto_job = None
        if self.auto.get():
            def tick():
                if self.o.exists() and self.auto.get():
                    self.check(auto=True)
                    self.auto_job = self.o.win.after(CHECK_EVERY_MS, tick)
            self.auto_job = self.o.win.after(CHECK_EVERY_MS, tick)


# ---------------------------------------------------------------------------- historial

class HistoryTab:
    W, H, L, R, T, B = 800, 260, 60, 16, 12, 28

    def __init__(self, parent, owner: MoreWindow):
        self.o, self.item_id, self.series = owner, None, []
        f = self.frame = ttk.Frame(parent, padding=10)
        top = ttk.Frame(f)
        top.pack(fill="x")
        ItemPicker(top, "Objeto", lambda: owner.app.catalog.items, self.pick).pack(side="left", fill="x", expand=True)
        side = ttk.Frame(top)
        side.pack(side="left", padx=(10, 0), anchor="n")
        self.ench, self.qual = tk.StringVar(value="0"), tk.StringVar(value=QUALITIES[0])
        ttk.Label(side, text="Encantamiento").pack(anchor="w")
        ttk.Combobox(side, textvariable=self.ench, values=["0", "1", "2", "3", "4"], state="readonly", width=12).pack()
        ttk.Label(side, text="Calidad").pack(anchor="w", pady=(4, 0))
        ttk.Combobox(side, textvariable=self.qual, values=QUALITIES, state="readonly", width=12).pack()
        self.title = tk.StringVar(value="Elige un objeto en el buscador.")
        ttk.Label(f, textvariable=self.title, font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(6, 0))
        self.status = tk.StringVar()
        ttk.Label(f, textvariable=self.status, foreground="gray").pack(anchor="w")
        self.legend = ttk.Frame(f)
        self.legend.pack(fill="x", pady=(4, 0))
        self.canvas = tk.Canvas(f, width=self.W, height=self.H, bg="#ffffff", highlightthickness=1, highlightbackground="#e2ddd2")
        self.canvas.pack(pady=4)
        self.canvas.bind("<Motion>", self.hover)
        self.canvas.bind("<Leave>", lambda e: (self.canvas.delete("hover"), self.tip.set("Pasa el ratón por la gráfica para ver los precios de un día.")))
        self.tip = tk.StringVar()
        ttk.Label(f, textvariable=self.tip, wraplength=800, justify="left").pack(anchor="w")
        cols = [("city", "Ciudad", 160, "w"), ("last", "Último día", 110, "e"), ("avg", "Media 7 d", 110, "e"), ("vol", "Ventas/día", 100, "e")]
        self.tree = ttk.Treeview(f, columns=[c[0] for c in cols], show="headings", height=8)
        for key, title, width, anchor in cols:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor)
        self.tree.pack(fill="x", pady=(6, 0))

    def pick(self, it: dict) -> None:
        ench = int(self.ench.get())
        if ench and not it.get("f") and ench not in it["e"]:
            self.status.set("Ese objeto no existe con ese encantamiento.")
            return
        self.show(it["id"] if it.get("f") or not ench else f"{it['id']}@{ench}", quality_of(self.qual.get()))

    def show(self, item_id: str, quality: int) -> None:
        app, cat = self.o.app, self.o.app.catalog
        self.item_id = item_id
        self.title.set(f"{cat.name(item_id)} ({cat.label(item_id)}) · {QUALITY_NAMES[quality]}")
        equip = cat.base(item_id).get("c") not in NOT_BLACK_MARKET
        locs = self.o.cities() + ([BLACK_MARKET] if equip else [])
        if not locs:
            self.status.set("Marca alguna ciudad en la ventana principal.")
            return
        self.status.set("Descargando historial…")
        server = app.effective_server()

        def done(rows, error):
            if not self.o.exists() or self.item_id != item_id:
                return
            if error:
                self.status.set(f"Error: {error}")
                return
            self.series = history_series(rows or [])
            self.status.set("" if self.series else "La API no tiene ventas registradas de este objeto en los últimos 28 días.")
            self.draw()

        run_async(app, lambda: fetch_history(server, [item_id], locs, [quality]), done)

    # ---- gráfica
    def scales(self):
        pts = [p for s in self.series for p in s["points"]]
        days = sorted({p[0] for p in pts})
        d0, d1 = days[0], max(days[-1], days[0] + 1)
        prices = sorted(p[1] for p in pts)
        # Un pico aislado aplastaría el resto: el eje se corta en 1,3 × el percentil 95
        hi = min(prices[-1], prices[min(len(prices) - 1, int(len(prices) * 0.95))] * 1.3)
        lo = min(prices[0], hi) * 0.95
        x = lambda d: self.L + (d - d0) / (d1 - d0) * (self.W - self.L - self.R)
        y = lambda v: self.T + (1 - (min(v, hi) - lo) / ((hi - lo) or 1)) * (self.H - self.T - self.B)
        return days, d0, d1, lo, hi, x, y

    @staticmethod
    def day_label(day: int) -> str:
        return time.strftime("%d/%m", time.gmtime(day * 86400))

    def draw(self) -> None:
        c = self.canvas
        c.delete("all")
        for w in self.legend.winfo_children():
            w.destroy()
        self.tree.delete(*self.tree.get_children())
        self.tip.set("")
        if not self.series:
            return
        days, d0, d1, lo, hi, x, y = self.scales()
        for i in range(5):
            v = lo + (hi - lo) * i / 4
            c.create_line(self.L, y(v), self.W - self.R, y(v), fill="#e2ddd2")
            c.create_text(self.L - 6, y(v), text=fmt(v), anchor="e", fill="#6b665c", font=("Segoe UI", 8))
        for d, anchor in ((d0, "w"), ((d0 + d1) // 2, "center"), (d1, "e")):
            c.create_text(x(d), self.H - 12, text=self.day_label(d), anchor=anchor, fill="#6b665c", font=("Segoe UI", 8))
        for s in self.series:
            color = CITY_COLORS[s["city"]]
            coords = [v for p in s["points"] for v in (x(p[0]), y(p[1]))]
            if len(s["points"]) > 1:
                c.create_line(*coords, fill=color, width=2, joinstyle="round", capstyle="round")
            else:
                c.create_oval(coords[0] - 4, coords[1] - 4, coords[0] + 4, coords[1] + 4, fill=color, outline="")
            item = ttk.Frame(self.legend)
            item.pack(side="left", padx=(0, 12))
            tk.Label(item, bg=color, width=2).pack(side="left", padx=(0, 4))
            ttk.Label(item, text=city_label(s["city"])).pack(side="left")
        for city, last, avg, vol in week_summary(self.series):
            self.tree.insert("", "end", values=(city_label(city), fmt(last), fmt(avg), f"{vol:.1f}".replace(".", ",")))
        self.tip.set("Pasa el ratón por la gráfica para ver los precios de un día.")

    def hover(self, event) -> None:
        if not self.series:
            return
        days, d0, d1, lo, hi, x, y = self.scales()
        frac = min(1.0, max(0.0, (event.x - self.L) / (self.W - self.L - self.R)))
        target = d0 + frac * (d1 - d0)
        day = min(days, key=lambda d: abs(d - target))
        self.canvas.delete("hover")
        self.canvas.create_line(x(day), self.T, x(day), self.H - self.B, fill="#6b665c", dash=(3, 3), tags="hover")
        parts = []
        for s in self.series:
            p = next((p for p in s["points"] if p[0] == day), None)
            if p:
                parts.append(f"{city_label(s['city'])}: {fmt(p[1])}")
        self.tip.set(f"{self.day_label(day)}  ·  " + "   ".join(parts))


# ---------------------------------------------------------------------------- registro de ganancias

class LedgerTab:
    def __init__(self, parent, owner: MoreWindow):
        self.o = owner
        self.entries = load_json("ganancias.json", [])  # [{ts, name, qty, buy, sell, buyOrder, sellOrder, premium, profit, cost}]
        f = self.frame = ttk.Frame(parent, padding=10)
        self.totals = tk.StringVar()
        ttk.Label(f, textvariable=self.totals, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))

        form = ttk.LabelFrame(f, text="Apuntar una operación", padding=8)
        form.pack(fill="x")
        self.name, self.qty, self.buy, self.sell = tk.StringVar(), tk.StringVar(value="1"), tk.StringVar(), tk.StringVar()
        self.buy_order, self.sell_order = tk.BooleanVar(), tk.BooleanVar()
        for i, (label, var, width) in enumerate([("Objeto", self.name, 30), ("Cantidad", self.qty, 8),
                                                 ("Precio de compra/ud.", self.buy, 12), ("Precio de venta/ud.", self.sell, 12)]):
            ttk.Label(form, text=label).grid(row=i // 2, column=(i % 2) * 2, sticky="w", padx=(0, 4), pady=2)
            ttk.Entry(form, textvariable=var, width=width).grid(row=i // 2, column=(i % 2) * 2 + 1, sticky="w", padx=(0, 14))
            var.trace_add("write", lambda *a: self.preview_update())
        ttk.Checkbutton(form, text="Compré con orden de compra (+2,5 %)", variable=self.buy_order,
                        command=self.preview_update).grid(row=2, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(form, text="Vendí con orden de venta (+2,5 %)", variable=self.sell_order,
                        command=self.preview_update).grid(row=2, column=2, columnspan=2, sticky="w")
        self.preview = tk.StringVar()
        ttk.Label(form, textvariable=self.preview, foreground="gray").grid(row=3, column=0, columnspan=3, sticky="w", pady=(4, 0))
        ttk.Button(form, text="Añadir al registro", command=self.add).grid(row=3, column=3, sticky="e")

        cols = [("date", "Fecha", 90, "w"), ("name", "Objeto", 240, "w"), ("qty", "Uds.", 60, "e"), ("buy", "Compra", 90, "e"),
                ("sell", "Venta", 90, "e"), ("profit", "Beneficio", 100, "e"), ("pct", "%", 70, "e")]
        self.tree = ttk.Treeview(f, columns=[c[0] for c in cols], show="headings", selectmode="browse")
        for key, title, width, anchor in cols:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor, stretch=key == "name")
        self.tree.pack(fill="both", expand=True, pady=8)
        self.tree.tag_configure("neg", foreground="#b3261e")
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        ttk.Button(bar, text="Borrar la seleccionada", command=self.remove).pack(side="left")
        ttk.Button(bar, text="Exportar a CSV", command=self.export_csv).pack(side="right")
        self.render()

    def draft(self) -> Optional[dict]:
        buy, sell = num(self.buy.get()), num(self.sell.get())
        if buy <= 0 or sell <= 0:
            return None
        qty = max(1, int(num(self.qty.get(), 1)))
        premium = self.o.app.premium_var.get()
        t = K.trade(buy, sell, qty, premium=premium, buy_order=self.buy_order.get(), sell_order=self.sell_order.get())
        return {"ts": time.time(), "name": self.name.get().strip() or "Sin nombre", "qty": qty, "buy": buy, "sell": sell,
                "buyOrder": self.buy_order.get(), "sellOrder": self.sell_order.get(), "premium": premium,
                "profit": round(t["total_profit"]), "cost": round(t["total_cost"])}

    def preview_update(self) -> None:
        d = self.draft()
        self.preview.set(f"Beneficio tras impuestos: {'+' if d['profit'] > 0 else ''}{fmt(d['profit'])}" if d else "")

    def add(self) -> None:
        d = self.draft()
        if not d:
            self.preview.set("Escribe el precio de compra y el de venta.")
            return
        self.entries.insert(0, d)
        save_json("ganancias.json", self.entries)
        for v, val in ((self.name, ""), (self.buy, ""), (self.sell, ""), (self.qty, "1")):
            v.set(val)
        self.render()

    def remove(self) -> None:
        sel = self.tree.selection()
        if sel:
            del self.entries[int(sel[0])]
            save_json("ganancias.json", self.entries)
            self.render()

    def render(self) -> None:
        now, today = time.time(), time.strftime("%Y-%m-%d")
        day = lambda e: time.strftime("%Y-%m-%d", time.localtime(e["ts"]))
        groups = [("Hoy", [e for e in self.entries if day(e) == today]),
                  ("Últimos 7 días", [e for e in self.entries if now - e["ts"] < 7 * 86400]), ("Total", self.entries)]
        sign = lambda v: ("+" if v > 0 else "") + fmt(v)
        self.totals.set("     ".join(f"{k}: {sign(sum(e['profit'] for e in lst))} ({len(lst)} op.)" for k, lst in groups))
        self.tree.delete(*self.tree.get_children())
        for i, e in enumerate(self.entries):
            pct = f"{e['profit'] / e['cost'] * 100:.1f} %" if e.get("cost") else ""
            self.tree.insert("", "end", iid=str(i), tags=("neg",) if e["profit"] < 0 else (), values=(
                time.strftime("%d/%m/%Y", time.localtime(e["ts"])), e["name"], fmt(e["qty"]), fmt(e["buy"]),
                fmt(e["sell"]), sign(e["profit"]), pct))

    def csv_text(self) -> str:
        yn = lambda b: "si" if b else "no"
        lines = ["fecha;objeto;cantidad;precio_compra;precio_venta;orden_compra;orden_venta;premium;inversion;beneficio"]
        for e in self.entries:
            name = '"' + e["name"].replace('"', '""') + '"'
            lines.append(";".join(str(x) for x in [
                time.strftime("%Y-%m-%d", time.localtime(e["ts"])), name, e["qty"], round(e["buy"]), round(e["sell"]),
                yn(e.get("buyOrder")), yn(e.get("sellOrder")), yn(e.get("premium")), e.get("cost", ""), e["profit"]]))
        return "\n".join(lines)

    def export_csv(self) -> None:
        if not self.entries:
            messagebox.showinfo("Albion BM", "El registro está vacío.", parent=self.o.win)
            return
        try:
            path = os.path.join(export_dir(), time.strftime("ganancias_albionbm_%Y%m%d.csv"))
            with open(path, "w", encoding="utf-8-sig") as f:  # con BOM para que Excel lea bien los acentos
                f.write(self.csv_text())
            messagebox.showinfo("Albion BM", f"Registro guardado en:\n{path}", parent=self.o.win)
        except OSError as e:
            messagebox.showerror("Albion BM", f"No se pudo guardar: {e}", parent=self.o.win)
