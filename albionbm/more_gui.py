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
from .calc import QUALITY_NAMES, selling_places
from .calc_gui import ItemPicker, fmt, num, run_async
from .export import export_dir
from .game import BLACK_MARKET, CITIES
from .items import NOT_BLACK_MARKET
from .movements import BUYS, KIND_LABELS, profit_since, realize
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
        self.nb.add(self.ledger.frame, text="Registro manual")
        self.auto = AutoLedgerTab(self.nb, self)
        self.nb.add(self.auto.frame, text="Historial automático")
        self.sell = SellTab(self.nb, self)
        self.nb.add(self.sell.frame, text="Dónde vender")
        self.nb.add(DiscordTab(self.nb, self).frame, text="Avisos a Discord")

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
                from . import notify
                if notify.load_config().get("favs"):
                    app.discord(f"🔔 **Aviso de precio** en Albion: {names}" + (" y más" if len(fresh) > 3 else "")
                                + ". Míralo en la app.")

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


# ---------------------------------------------------------------------------- historial automático

class AutoLedgerTab:
    """Compras y ventas leídas del juego (correos del mercado, compras directas y ventas rápidas)."""

    def __init__(self, parent, owner: MoreWindow):
        self.o, self.seen_version, self.rows = owner, -1, []
        f = self.frame = ttk.Frame(parent, padding=10)
        self.totals = tk.StringVar()
        ttk.Label(f, textvariable=self.totals, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.detail = tk.StringVar()
        ttk.Label(f, textvariable=self.detail, foreground="gray", wraplength=820, justify="left").pack(anchor="w", pady=(2, 6))
        ttk.Label(f, foreground="gray", wraplength=820, justify="left", text=(
            "Se apunta solo con la app abierta y la captura activa: las compras directas y ventas rápidas al "
            "hacerlas, y las órdenes cuando ABRES su correo en el juego. El beneficio de cada venta usa el coste "
            "medio de lo que la app te vio comprar de ese objeto; si no vio la compra, sale «—».")).pack(anchor="w")
        cols = [("date", "Fecha", 110, "w"), ("kind", "Tipo", 120, "w"), ("name", "Objeto", 230, "w"), ("qty", "Uds.", 55, "e"),
                ("net", "Plata neta", 100, "e"), ("profit", "Beneficio", 100, "e"), ("loc", "Dónde", 100, "w")]
        box = ttk.Frame(f)
        box.pack(fill="both", expand=True, pady=8)
        self.tree = ttk.Treeview(box, columns=[c[0] for c in cols], show="headings", selectmode="browse")
        for key, title, width, anchor in cols:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor, stretch=key == "name")
        vs = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.tag_configure("buy", foreground="#6b665c")
        self.tree.tag_configure("neg", foreground="#b3261e")
        self.tree.tag_configure("pos", foreground="#1d7a3a")
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        ttk.Button(bar, text="Borrar el seleccionado", command=self.remove).pack(side="left")
        ttk.Button(bar, text="Exportar a CSV", command=self.export_csv).pack(side="right")
        self.tick()

    def tick(self) -> None:
        """Se refresca sola cuando la app apunta un movimiento nuevo."""
        if not self.o.exists():
            return
        if self.o.app.store.movements_version != self.seen_version:
            self.render()
        self.o.win.after(1500, self.tick)

    def render(self) -> None:
        app = self.o.app
        self.seen_version = app.store.movements_version
        self.rows, s = realize(app.store.load_movements(app.effective_server()), app.premium_var.get())
        now = time.time()
        midnight = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
        sign = lambda v: ("+" if v > 0 else "") + fmt(v)
        self.totals.set(f"Beneficio  ·  Hoy: {sign(profit_since(self.rows, midnight))}     "
                        f"7 días: {sign(profit_since(self.rows, now - 7 * 86400))}     Total: {sign(s['profit'])}")
        detail = f"Gastado: {fmt(s['spent'])}  ·  Ingresado: {fmt(s['earned'])}  ·  Sin vender: {fmt(s['stock_units'])} uds. que costaron {fmt(s['stock_cost'])}"
        if s["unknown_revenue"]:
            detail += f"  ·  Ventas sin coste conocido: {fmt(s['unknown_revenue'])} (no cuentan en el beneficio)"
        self.detail.set(detail if self.rows else "Todavía no hay movimientos. Compra o vende en el mercado con la app abierta, o abre un correo del mercado.")
        self.tree.delete(*self.tree.get_children())
        cat = app.catalog
        for r in reversed(self.rows):
            buy = r["kind"] in BUYS
            tag = "buy" if buy else "neg" if (r["profit"] or 0) < 0 else "pos" if r["profit"] else ""
            self.tree.insert("", "end", iid=r["key"], tags=(tag,), values=(
                time.strftime("%d/%m %H:%M", time.localtime(r["ts"])), KIND_LABELS[r["kind"]],
                f"{cat.name(r['item'])} ({cat.label(r['item'])})", fmt(r["qty"]),
                ("−" if buy else "+") + fmt(r["net"]),
                "" if buy else "—" if r["profit"] is None else sign(r["profit"]),
                city_label(r["location"]) if r["location"] else ""))

    def remove(self) -> None:
        sel = self.tree.selection()
        if sel and messagebox.askyesno("Albion BM", "¿Borrar este movimiento del historial?", parent=self.o.win):
            self.o.app.store.delete_movement(sel[0])
            self.render()

    def export_csv(self) -> None:
        if not self.rows:
            messagebox.showinfo("Albion BM", "El historial está vacío.", parent=self.o.win)
            return
        cat = self.o.app.catalog
        lines = ["fecha;tipo;objeto;id;cantidad;plata_bruta;plata_neta;beneficio;lugar"]
        for r in self.rows:
            name = '"' + cat.name(r["item"]).replace('"', '""') + '"'
            lines.append(";".join(str(x) for x in [
                time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ts"])), KIND_LABELS[r["kind"]], name, r["item"], r["qty"],
                round(r["silver"]), round(r["net"]), "" if r["profit"] is None else round(r["profit"]), r["location"]]))
        try:
            path = os.path.join(export_dir(), time.strftime("historial_albionbm_%Y%m%d.csv"))
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write("\n".join(lines))
            messagebox.showinfo("Albion BM", f"Historial guardado en:\n{path}", parent=self.o.win)
        except OSError as e:
            messagebox.showerror("Albion BM", f"No se pudo guardar: {e}", parent=self.o.win)


# ---------------------------------------------------------------------------- dónde vender lo que tengo

class SellTab:
    """Para los objetos que ya tienes: en qué mercado y de qué forma sacas más por cada uno."""

    def __init__(self, parent, owner: MoreWindow):
        self.o = owner
        self.items = load_json("inventario.json", [])  # [{id, quality, qty}]
        f = self.frame = ttk.Frame(parent, padding=10)
        add = ttk.Frame(f)
        add.pack(fill="x")
        ItemPicker(add, "Añadir objeto (elige encantamiento, calidad y cantidad, y luego el objeto)",
                   lambda: owner.app.catalog.items, self.add).pack(side="left", fill="x", expand=True)
        side = ttk.Frame(add)
        side.pack(side="left", padx=(10, 0), anchor="n")
        self.ench, self.qual, self.qty = tk.StringVar(value="0"), tk.StringVar(value=QUALITIES[0]), tk.StringVar(value="1")
        for label, widget in (("Encantamiento", ttk.Combobox(side, textvariable=self.ench, values=["0", "1", "2", "3", "4"], state="readonly", width=12)),
                              ("Calidad", ttk.Combobox(side, textvariable=self.qual, values=QUALITIES, state="readonly", width=12)),
                              ("Cantidad", ttk.Entry(side, textvariable=self.qty, width=14))):
            ttk.Label(side, text=label).pack(anchor="w")
            widget.pack()
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=8)
        self.btn = ttk.Button(bar, text="Buscar precios y comparar", command=self.check)
        self.btn.pack(side="left")
        ttk.Button(bar, text="Cargar lo que tengo sin vender", command=self.load_stock).pack(side="left", padx=6)
        ttk.Button(bar, text="Quitar el seleccionado", command=self.remove).pack(side="left")
        ttk.Button(bar, text="Vaciar", command=self.clear).pack(side="left", padx=6)
        self.status = tk.StringVar()
        ttk.Label(bar, textvariable=self.status, foreground="gray").pack(side="left")
        self.total = tk.StringVar()
        ttk.Label(f, textvariable=self.total, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        cols = [("name", "Objeto", 220, "w"), ("tier", "Tier", 45, "center"), ("qual", "Calidad", 85, "w"), ("qty", "Uds.", 50, "e"),
                ("best", "Mejor sitio", 190, "w"), ("unit", "Neto/ud.", 85, "e"), ("tot", "Neto total", 95, "e"),
                ("second", "Segunda opción", 190, "w")]
        self.tree = ttk.Treeview(f, columns=[c[0] for c in cols], show="headings", selectmode="browse")
        for key, title, width, anchor in cols:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor, stretch=key == "name")
        self.tree.pack(fill="both", expand=True)
        ttk.Label(f, foreground="gray", wraplength=820, justify="left", text=(
            "«Venta rápida» = vender ya a la mejor orden de compra que acepte tu calidad. «Orden de venta» = poner tu "
            "orden igualando la más barata (tarda y paga un 2,5 % más). Neto = tras impuestos. Usa las ciudades "
            "marcadas en la ventana principal y el Mercado Negro si es equipo.")).pack(anchor="w", pady=(6, 0))
        self.render()

    def item_id(self, it: dict, ench: int) -> Optional[str]:
        if ench and not it.get("f") and ench not in it["e"]:
            return None
        return it["id"] if it.get("f") or not ench else f"{it['id']}@{ench}"

    def add(self, it: dict) -> None:
        iid = self.item_id(it, int(self.ench.get()))
        if not iid:
            self.status.set("Ese objeto no existe con ese encantamiento.")
            return
        q, n = quality_of(self.qual.get()), max(1, int(num(self.qty.get(), 1)))
        for x in self.items:
            if x["id"] == iid and x["quality"] == q:
                x["qty"] += n
                break
        else:
            self.items.append({"id": iid, "quality": q, "qty": n})
        save_json("inventario.json", self.items)
        self.render()

    def load_stock(self) -> None:
        """Lo que el historial automático te vio comprar y aún no te ha visto vender."""
        app = self.o.app
        stock: dict = {}
        for m in app.store.load_movements(app.effective_server()):
            sign = 1 if m["kind"] in BUYS else -1
            stock[m["item"]] = stock.get(m["item"], 0) + sign * m["qty"]
        added = 0
        for item, n in stock.items():
            if n > 0 and not any(x["id"] == item for x in self.items):
                self.items.append({"id": item, "quality": 1, "qty": n})
                added += 1
        save_json("inventario.json", self.items)
        self.status.set(f"Añadidos {added} objetos del historial (con calidad Normal: cámbiala si no lo es)." if added
                        else "El historial automático no tiene objetos comprados sin vender.")
        self.render()

    def remove(self) -> None:
        sel = self.tree.selection()
        if sel:
            del self.items[int(sel[0])]
            save_json("inventario.json", self.items)
            self.render()

    def clear(self) -> None:
        if self.items and messagebox.askyesno("Albion BM", "¿Vaciar la lista?", parent=self.o.win):
            self.items = []
            save_json("inventario.json", self.items)
            self.render()

    def locations(self, item: str) -> List[str]:
        equip = self.o.app.catalog.base(item).get("c") not in NOT_BLACK_MARKET
        return self.o.cities() + ([BLACK_MARKET] if equip else [])

    def check(self) -> None:
        if not self.items:
            self.status.set("Añade algún objeto primero.")
            return
        app, server = self.o.app, self.o.app.effective_server()
        ids = sorted({x["id"] for x in self.items})
        locs = sorted({loc for x in self.items for loc in self.locations(x["id"])})
        quals = list(range(1, max(x["quality"] for x in self.items) + 1))
        self.btn.configure(state="disabled")
        self.status.set("Buscando precios…")

        def job():
            prices, stamps = rows_to_prices(fetch_prices(server, ids, locs, quals))
            app.store.upsert(server, prices, source="api", timestamps=stamps)

        def done(_r, error):
            if not self.o.exists():
                return
            self.btn.configure(state="normal")
            self.status.set(f"Error: {error}" if error else "Precios actualizados.")
            self.render()

        run_async(app, job, done)

    def render(self) -> None:
        app = self.o.app
        entries = app.store.load(app.effective_server(), 24)
        cat, total = app.catalog, 0.0
        self.tree.delete(*self.tree.get_children())
        mode = {"quick": "venta rápida", "order": "orden de venta"}
        for i, x in enumerate(self.items):
            places = selling_places(x["id"], x["quality"], entries, self.locations(x["id"]), app.premium_var.get())
            best = places[0] if places else None
            second = places[1] if len(places) > 1 else None
            if best:
                total += best["net"] * x["qty"]
            self.tree.insert("", "end", iid=str(i), values=(
                cat.name(x["id"]), cat.label(x["id"]), QUALITY_NAMES[x["quality"]], fmt(x["qty"]),
                f"{city_label(best['location'])} · {mode[best['mode']]}" if best else "sin precios",
                fmt(best["net"]) if best else "—", fmt(best["net"] * x["qty"]) if best else "—",
                f"{city_label(second['location'])} · {mode[second['mode']]}: {fmt(second['net'])}" if second else ""))
        self.total.set(f"Vendiéndolo todo en el mejor sitio: {fmt(total)} de plata neta" if self.items else
                       "Añade los objetos que tienes para ver dónde venderlos.")


# ---------------------------------------------------------------------------- avisos a Discord

class DiscordTab:
    def __init__(self, parent, owner: MoreWindow):
        from . import notify
        self.o, self.notify = owner, notify
        cfg = notify.load_config()
        f = self.frame = ttk.Frame(parent, padding=12)
        ttk.Label(f, wraplength=820, justify="left", text=(
            "Con la app abierta en el PC, te llega un mensaje a Discord (y al móvil, con la app de Discord) "
            "cuando aparecen oportunidades nuevas que superen tus mínimos o se cumple el aviso de un favorito.\n\n"
            "Cómo conseguir el webhook: en un servidor de Discord tuyo, ajustes del canal → Integraciones → Webhooks → "
            "Nuevo webhook → Copiar URL del webhook, y pégala aquí.")).pack(anchor="w")
        g = ttk.Frame(f)
        g.pack(fill="x", pady=10)
        self.webhook = tk.StringVar(value=cfg["webhook"])
        self.enabled = tk.BooleanVar(value=cfg["enabled"])
        self.min_pct, self.min_total = tk.StringVar(value=cfg["min_pct"]), tk.StringVar(value=cfg["min_total"])
        self.favs = tk.BooleanVar(value=cfg["favs"])
        ttk.Label(g, text="URL del webhook").grid(row=0, column=0, sticky="w")
        ttk.Entry(g, textvariable=self.webhook, width=80, show="•").grid(row=0, column=1, columnspan=3, sticky="w", padx=6)
        ttk.Checkbutton(g, text="Activar avisos a Discord", variable=self.enabled).grid(row=1, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Label(g, text="Avisar si el beneficio es al menos (%)").grid(row=2, column=0, sticky="w")
        ttk.Entry(g, textvariable=self.min_pct, width=8).grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(g, text="y el beneficio total al menos (plata)").grid(row=3, column=0, sticky="w")
        ttk.Entry(g, textvariable=self.min_total, width=12).grid(row=3, column=1, sticky="w", padx=6)
        ttk.Checkbutton(g, text="Avisar también de los favoritos que cumplen su precio", variable=self.favs).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=4)
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        ttk.Button(bar, text="Guardar", command=self.save).pack(side="left")
        ttk.Button(bar, text="Enviar mensaje de prueba", command=self.test).pack(side="left", padx=6)
        self.status = tk.StringVar()
        ttk.Label(bar, textvariable=self.status, foreground="gray").pack(side="left", padx=6)
        ttk.Label(f, foreground="gray", wraplength=820, justify="left", text=(
            "Las oportunidades se revisan tras cada «Actualizar precios»: activa «Auto cada N min» en la ventana "
            "principal para que se revisen solas. Solo se avisa de las que no estaban en la revisión anterior. "
            "Los favoritos se revisan con «Comprobar sola cada 10 min» de su pestaña, con esta ventana abierta.\n"
            "El webhook se guarda solo en este PC. Quien tenga esa URL puede escribir en tu canal: no la compartas.")
                  ).pack(anchor="w", pady=(12, 0))

    def config(self) -> dict:
        return {"webhook": self.webhook.get().strip(), "enabled": self.enabled.get(), "min_pct": self.min_pct.get().strip(),
                "min_total": self.min_total.get().strip(), "favs": self.favs.get()}

    def save(self) -> None:
        cfg = self.config()
        if cfg["enabled"] and not self.notify.valid_webhook(cfg["webhook"]):
            self.status.set("Esa URL no parece un webhook de Discord.")
            return
        self.notify.save_config(cfg)
        self.status.set("Guardado.")

    def test(self) -> None:
        url = self.webhook.get().strip()
        self.status.set("Enviando…")
        app = self.o.app
        self.notify.send_async(url, "✅ Prueba de **Albion BM**: los avisos te llegarán a este canal.",
                               # se llama desde otro hilo: todo lo que toca la ventana va por la cola
                               lambda err: app.events.put(("call", lambda: self.status.set(err or "Enviado. Míralo en Discord.")
                                                           if self.o.exists() else None)))
