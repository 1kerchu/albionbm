"""Ventana «Confirmar en el juego»: lista corta de objetos que abrir en el mercado, que se tacha sola."""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk
from typing import Optional

from . import checklist as CL
from .calc import PROFILES, QUALITY_NAMES, plan
from .game import BLACK_MARKET


def fmt(n) -> str:
    return "—" if n is None else f"{round(n):,}".replace(",", ".")


def place(loc: str) -> str:
    return "Mercado Negro (Caerleon)" if loc == BLACK_MARKET else loc


class ChecklistWindow:
    def __init__(self, app):
        self.app = app
        self.cl: Optional[CL.Checklist] = None
        self.seen = (-1, None)
        self.win = tk.Toplevel(app.root)
        self.win.title("Confirmar en el juego")
        self.win.geometry("900x760")
        f = ttk.Frame(self.win, padding=10)
        f.pack(fill="both", expand=True)

        ttk.Label(f, wraplength=860, justify="left", text=(
            "Abre en el mercado del juego cada objeto de la lista (búscalo por nombre: doble clic lo copia). "
            "La app lee las órdenes y lo tacha sola. Pestaña «Comprar» para ver a cuánto se vende; pestaña "
            "«Vender» para ver cuánto pagan las órdenes de compra.")).pack(anchor="w")
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=8)
        ttk.Label(bar, text="Oportunidades a comprobar").pack(side="left")
        self.count = tk.StringVar(value="10")
        ttk.Combobox(bar, textvariable=self.count, values=["5", "10", "15", "25"], state="readonly", width=4).pack(side="left", padx=6)
        ttk.Button(bar, text="Generar lista", command=self.generate).pack(side="left")
        self.source = tk.StringVar()
        ttk.Label(bar, textvariable=self.source, foreground="gray").pack(side="left", padx=10)
        self.progress = tk.StringVar()
        ttk.Label(f, textvariable=self.progress, font=("Segoe UI", 11, "bold")).pack(anchor="w")

        cols = [("name", "Objeto", 300, "w"), ("tier", "Tier", 50, "center"), ("qual", "Calidad", 100, "w"),
                ("api", "Precio API", 100, "e"), ("live", "Precio en el juego", 120, "e"), ("state", "Estado", 110, "w")]
        box = ttk.Frame(f)
        box.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(box, columns=[c[0] for c in cols], show="tree headings", height=14)
        self.tree.column("#0", width=24, stretch=False)
        for key, title, width, anchor in cols:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor=anchor, stretch=key == "name")
        vs = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.tag_configure("group", font=("Segoe UI", 10, "bold"))
        self.tree.tag_configure("here", font=("Segoe UI", 10, "bold"), foreground="#1d7a3a")
        self.tree.tag_configure("done", foreground="#6b665c")
        self.tree.bind("<Double-1>", self.copy_name)

        ttk.Label(f, text="Resultado de cada oportunidad", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(10, 2))
        vcols = [("name", "Objeto", 250, "w"), ("route", "Ruta", 230, "w"), ("before", "Benef./ud. API", 110, "e"),
                 ("now", "Benef./ud. ahora", 120, "e"), ("verdict", "Veredicto", 170, "w")]
        self.vtree = ttk.Treeview(f, columns=[c[0] for c in vcols], show="headings", height=8)
        for key, title, width, anchor in vcols:
            self.vtree.heading(key, text=title)
            self.vtree.column(key, width=width, anchor=anchor, stretch=key == "name")
        self.vtree.pack(fill="x")
        self.vtree.tag_configure("good", foreground="#1d7a3a")
        self.vtree.tag_configure("bad", foreground="#b3261e")
        self.status = tk.StringVar(value="Doble clic en un objeto copia su nombre para pegarlo en el buscador del mercado.")
        ttk.Label(f, textvariable=self.status, foreground="gray").pack(anchor="w", pady=(6, 0))
        self.generate()
        self.tick()

    def exists(self) -> bool:
        return bool(self.win.winfo_exists())

    # ---- lista
    def generate(self) -> None:
        app, f = self.app, self.app._read_filters()
        capital = app._num(f["capital"], 0)
        n = int(self.count.get())
        good = [o for o in app.opps if not o.suspicious and o.profit > 0]
        if capital > 0:
            lines, _ = plan(good, capital, profile=f["profile"], max_weight=app._num(f["weight"], 0) or None,
                            weight_of=app.catalog.weight, **app.risk_args(f))
            opps = [l.opp for l in lines][:n]
            self.source.set(f"Del plan de inversión (perfil {PROFILES[f['profile']].name}).")
        else:
            opps = sorted(good, key=lambda o: -(o.total_profit if o.total_profit is not None else o.profit))[:n]
            self.source.set("Las de más beneficio de la tabla. Escribe «Mi capital» para usar tu plan.")
        if not opps:
            self.source.set("No hay oportunidades: pulsa «Actualizar precios» en la ventana principal.")
        self.cl = CL.build(opps, f["buy_mode"], f["strategy"])
        self.seen = (-1, None)
        self.render()

    def tick(self) -> None:
        """Se tacha sola: vuelve a pintar cuando llegan precios del juego o cambias de ciudad."""
        if not self.exists():
            return
        state = (self.app.store.version, self.app.location)
        if state != self.seen:
            self.render()
        self.win.after(1000, self.tick)

    def render(self) -> None:
        app = self.app
        self.seen = (app.store.version, app.location)
        self.tree.delete(*self.tree.get_children())
        self.vtree.delete(*self.vtree.get_children())
        if not self.cl or not self.cl.checks:
            self.progress.set("")
            return
        entries = app.store.load(app.effective_server(), 48)
        cat, done_total = app.catalog, 0
        for (loc, tab), rows in CL.groups(self.cl, entries, app.location):
            pending = sum(1 for _, live in rows if live is None)
            done_total += len(rows) - pending
            here = loc == app.location
            title = f"{place(loc)} — pestaña {tab}" + ("   ← estás aquí" if here else "")
            gid = self.tree.insert("", "end", text="", open=pending > 0,
                                   values=(title, "", "", "", "", f"{pending} pendientes" if pending else "✔ hecho"),
                                   tags=("here" if here else "group",))
            for c, live in sorted(rows, key=lambda r: r[1] is not None):
                diff = ""
                if live is not None and c.api_price:
                    d = (live - c.api_price) / c.api_price * 100
                    diff = f" ({'+' if d >= 0 else ''}{d:.0f} %)"
                self.tree.insert(gid, "end", iid=f"{c.item}|{c.quality}|{c.location}|{c.kind}",
                                 tags=("done",) if live is not None else (), values=(
                                     cat.name(c.item), cat.label(c.item), QUALITY_NAMES.get(c.quality, ""),
                                     fmt(c.api_price), fmt(live) + diff if live is not None else "—",
                                     "✔ comprobado" if live is not None else "pendiente"))
        total = len(self.cl.checks)
        self.progress.set(f"Comprobados {done_total} de {total}" + ("  ·  ¡Lista completa!" if done_total == total else ""))
        for i, o in enumerate(self.cl.opps):
            v = CL.verdict(self.cl, i, entries, app.premium_var.get())
            if v["confirmed"]:
                text = "✔ Sigue compensando" if v["still_good"] else "✗ Ya no compensa"
            elif v["partial"]:
                text = "A medias: falta un precio"
            else:
                text = "Sin comprobar"
            self.vtree.insert("", "end", tags=(("good" if v["still_good"] else "bad"),) if v["confirmed"] else (), values=(
                f"{cat.name(o.item_id)} ({cat.label(o.item_id)})", f"{o.city} → {place(o.sell_city)}",
                fmt(o.profit), fmt(v["profit"]) + f" ({v['percent']:.0f} %)", text))

    def copy_name(self, _e=None) -> None:
        sel = self.tree.selection()
        if not sel or "|" not in sel[0]:
            return
        name = self.app.catalog.name(sel[0].split("|")[0])
        self.win.clipboard_clear()
        self.win.clipboard_append(name)
        self.status.set(f"Copiado: {name}. Pégalo en el buscador del mercado.")
