"""Ventana principal (Tkinter)."""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, List, Optional

from . import __version__
from .api import fetch_history, fetch_prices, history_to_stats, rows_to_prices
from .calc import PROFILES, QUALITY_NAMES, STRATEGIES, Opportunity, best_per_item, compute, plan, plan_routes
from .export import build_report, save_report
from .capture import Capture, CaptureError
from .game import BLACK_MARKET, CITIES, GameListener
from .items import CATEGORY_NAMES, NOT_BLACK_MARKET, Catalog, load_items
from .store import PriceStore, default_db_path

SERVERS = {"Automático": None, "Europa": "europe", "América (West)": "west", "Asia (East)": "east"}
SERVER_LABEL = {"europe": "Europa", "west": "América", "east": "Asia"}
STRATEGY_BY_LABEL = {v: k for k, v in STRATEGIES.items()}
PROFILE_BY_LABEL = {p.name: k for k, p in PROFILES.items()}
MAX_HISTORY_ITEMS = 1500
MAX_ROWS = 1000

DEFAULTS = {
    "server": "Automático", "premium": True, "buy_mode": "instant", "best_only": True,
    "min_pct": "10", "min_silver": "5000", "max_cost": "", "max_age": "6", "search": "", "capital": "", "auto": False, "auto_min": "15",
    "strategy": "bm", "hide_susp": True, "weight": "", "profile": "balanced", "alert": False,
    "cats": ["weapons", "armors", "head", "shoes", "offhands", "bags", "capes"],
    "tiers": [4, 5, 6], "enchs": [0, 1], "quals": [1, 2, 3], "cities": [c for c in CITIES if c != "Brecilien"],
}


def settings_path() -> str:
    return os.path.join(os.path.dirname(default_db_path()), "ajustes.json")


def fmt(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def fmtn(n) -> str:
    return "—" if n is None else fmt(n)


def ago(h: float) -> str:
    if h < 1:
        return f"{max(1, round(h * 60))} min"
    if h < 48:
        return f"{round(h)} h"
    return f"{round(h / 24)} d"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.catalog = Catalog(load_items())
        self.store = PriceStore()
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.detected_server: Optional[str] = None
        self.location: Optional[str] = None
        self.api_thread: Optional[threading.Thread] = None
        self.api_stop = False
        self.last_api_update = 0.0
        self.rendered_version = -1
        self.opps: List[Opportunity] = []
        self.sort_key, self.sort_desc = "percent", True
        self.alert_seen: Optional[set] = None
        self.plan_win: Optional[tk.Toplevel] = None
        self.calc_win = None
        self.more_win = None
        self.settings = self._load_settings()

        root.title(f"Albion · Comercio y Mercado Negro  v{__version__}")
        root.geometry("1440x860")
        root.minsize(980, 600)
        self._build_ui()

        self.listener = GameListener(self._on_live_prices, self._on_game_status)
        self.capture = Capture(self.listener.feed, lambda m: self.events.put(("capture_error", m)))
        self._start_capture()

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(300, self._tick)

    # ------------------------------------------------------------------ ajustes
    def _load_settings(self) -> dict:
        s = dict(DEFAULTS)
        try:
            with open(settings_path(), encoding="utf-8") as f:
                s.update(json.load(f))
        except (OSError, ValueError):
            pass
        return s

    def _save_settings(self) -> None:
        try:
            with open(settings_path(), "w", encoding="utf-8") as f:
                json.dump(self._read_filters(), f, ensure_ascii=False, indent=1)
        except OSError:
            pass

    # ------------------------------------------------------------------ interfaz
    def _build_ui(self) -> None:
        s = self.settings
        style = ttk.Style()
        try:
            style.theme_use("vista" if os.name == "nt" else "clam")
        except tk.TclError:
            pass
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))

        # Barra de estado superior
        top = ttk.Frame(self.root, padding=(10, 8))
        top.pack(fill="x")
        self.capture_var = tk.StringVar(value="Captura: iniciando…")
        self.capture_lbl = ttk.Label(top, textvariable=self.capture_var, style="Status.TLabel")
        self.capture_lbl.pack(side="left")
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)
        self.location_var = tk.StringVar(value="Ubicación: —")
        ttk.Label(top, textvariable=self.location_var).pack(side="left")
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=10)
        self.live_var = tk.StringVar(value="Precios leídos del juego: 0")
        ttk.Label(top, textvariable=self.live_var).pack(side="left")
        ttk.Label(top, text="Servidor:").pack(side="left", padx=(16, 4))
        self.server_var = tk.StringVar(value=s["server"])
        cb = ttk.Combobox(top, textvariable=self.server_var, values=list(SERVERS), state="readonly", width=16)
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self._filters_changed())
        self.server_info = tk.StringVar()
        ttk.Label(top, textvariable=self.server_info, foreground="gray").pack(side="left", padx=6)
        ttk.Button(top, text="Ayuda", command=self._help).pack(side="right")

        self.warn_var = tk.StringVar()
        self.warn_lbl = tk.Label(self.root, textvariable=self.warn_var, fg="#b3261e", anchor="w", padx=10)
        self.warn_lbl.pack(fill="x")

        # Filtros
        filt = ttk.Frame(self.root, padding=(10, 0))
        filt.pack(fill="x")
        self.vars: Dict[str, Dict] = {}

        def checks(parent, key, values, label_fn, col):
            box = ttk.LabelFrame(parent, text=label_fn(None), padding=6)
            box.grid(row=0, column=col, sticky="nsew", padx=(0, 8), pady=4)
            self.vars[key] = {}
            for i, v in enumerate(values):
                var = tk.BooleanVar(value=v in s[key])
                ttk.Checkbutton(box, text=label_fn(v), variable=var, command=self._filters_changed).grid(
                    row=i % 4, column=i // 4, sticky="w", padx=(0, 6))
                self.vars[key][v] = var

        checks(filt, "cats", list(CATEGORY_NAMES), lambda v: "Categorías" if v is None else CATEGORY_NAMES[v], 0)
        checks(filt, "tiers", [4, 5, 6, 7, 8], lambda v: "Tier" if v is None else f"T{v}", 1)
        checks(filt, "enchs", [0, 1, 2, 3, 4], lambda v: "Encantamiento" if v is None else f".{v}", 2)
        checks(filt, "quals", [1, 2, 3, 4, 5], lambda v: "Calidad" if v is None else QUALITY_NAMES[v], 3)
        checks(filt, "cities", CITIES, lambda v: "Ciudades" if v is None else v, 4)

        opts = ttk.LabelFrame(filt, text="Opciones", padding=6)
        opts.grid(row=0, column=5, sticky="nsew", pady=4)
        self.strategy_var = tk.StringVar(value=STRATEGIES.get(s["strategy"], STRATEGIES["bm"]))
        scb = ttk.Combobox(opts, textvariable=self.strategy_var, values=list(STRATEGIES.values()),
                           state="readonly", width=30)
        scb.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 3))
        scb.bind("<<ComboboxSelected>>", lambda e: self._filters_changed())
        self.premium_var = tk.BooleanVar(value=s["premium"])
        ttk.Checkbutton(opts, text="Prémium (impuesto 4 %)", variable=self.premium_var,
                        command=self._filters_changed).grid(row=1, column=0, sticky="w")
        self.best_var = tk.BooleanVar(value=s["best_only"])
        ttk.Checkbutton(opts, text="Solo mejor ruta", variable=self.best_var,
                        command=self._filters_changed).grid(row=1, column=1, sticky="w")
        self.buy_mode_var = tk.StringVar(value=s["buy_mode"])
        ttk.Radiobutton(opts, text="Compra directa", value="instant", variable=self.buy_mode_var,
                        command=self._filters_changed).grid(row=2, column=0, sticky="w")
        ttk.Radiobutton(opts, text="Orden de compra", value="order", variable=self.buy_mode_var,
                        command=self._filters_changed).grid(row=2, column=1, sticky="w")
        self.susp_var = tk.BooleanVar(value=s["hide_susp"])
        ttk.Checkbutton(opts, text="Ocultar precios sospechosos (⚠)", variable=self.susp_var,
                        command=self._filters_changed).grid(row=3, column=0, columnspan=2, sticky="w")

        # Búsqueda y límites
        row2 = ttk.Frame(self.root, padding=(10, 4, 10, 0))
        row2.pack(fill="x")
        ttk.Label(row2, text="Buscar:").pack(side="left")
        self.search_var = tk.StringVar(value=s["search"])
        self.search_var.trace_add("write", lambda *a: self._filters_changed())
        ttk.Entry(row2, textvariable=self.search_var, width=22).pack(side="left", padx=(4, 12))
        self.entries: Dict[str, tk.StringVar] = {}
        for key, label in [("min_pct", "Benef. mín. %"), ("min_silver", "Benef. mín. plata"),
                           ("max_cost", "Precio máx./ud."), ("max_age", "Datos máx. (h)")]:
            ttk.Label(row2, text=label).pack(side="left")
            var = tk.StringVar(value=s[key])
            ttk.Entry(row2, textvariable=var, width=8).pack(side="left", padx=(4, 10))
            var.trace_add("write", lambda *a: self._filters_changed())
            self.entries[key] = var
        # Inversión: capital, carga, perfil y acciones
        row3 = ttk.Frame(self.root, padding=(10, 4, 10, 0))
        row3.pack(fill="x")
        for key, label, width in [("capital", "Mi capital", 12), ("weight", "Carga máx. por viaje (kg)", 7)]:
            ttk.Label(row3, text=label).pack(side="left")
            var = tk.StringVar(value=s[key])
            ttk.Entry(row3, textvariable=var, width=width).pack(side="left", padx=(4, 12))
            var.trace_add("write", lambda *a: self._filters_changed())
            self.entries[key] = var
        ttk.Label(row3, text="Perfil de riesgo").pack(side="left")
        self.profile_var = tk.StringVar(value=PROFILES.get(s["profile"], PROFILES["balanced"]).name)
        pcb = ttk.Combobox(row3, textvariable=self.profile_var, values=[p.name for p in PROFILES.values()],
                           state="readonly", width=17)
        pcb.pack(side="left", padx=(4, 0))
        pcb.bind("<<ComboboxSelected>>", lambda e: self._filters_changed())
        ttk.Button(row3, text="★ Plan de inversión", command=self._show_plan).pack(side="left", padx=(12, 4))
        ttk.Button(row3, text="Exportar para Claude", command=self._export).pack(side="left")
        ttk.Button(row3, text="🖩 Calculadoras", command=self._show_calculators).pack(side="left", padx=4)
        ttk.Button(row3, text="☆ Favoritos · Historial · Ganancias", command=self._show_more).pack(side="left")

        # Barra de acciones
        bar = ttk.Frame(self.root, padding=(10, 4))
        bar.pack(fill="x")
        self.api_btn = ttk.Button(bar, text="⟳ Actualizar precios", command=self._api_refresh)
        self.api_btn.pack(side="left")
        self.api_stop_btn = ttk.Button(bar, text="Detener", command=self._api_cancel, state="disabled")
        self.api_stop_btn.pack(side="left", padx=4)
        self.auto_var = tk.BooleanVar(value=s["auto"])
        ttk.Checkbutton(bar, text="Auto cada", variable=self.auto_var, command=self._filters_changed).pack(
            side="left", padx=(8, 2))
        self.auto_min_var = tk.StringVar(value=s["auto_min"])
        ttk.Entry(bar, textvariable=self.auto_min_var, width=4).pack(side="left")
        ttk.Label(bar, text="min").pack(side="left", padx=(2, 0))
        self.alert_var = tk.BooleanVar(value=s["alert"])
        ttk.Checkbutton(bar, text="Avisar de nuevas", variable=self.alert_var, command=self._filters_changed).pack(
            side="left", padx=(8, 0))
        self.progress = ttk.Progressbar(bar, length=140, mode="determinate")
        self.progress.pack(side="left", padx=8)
        self.count_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.count_var, foreground="gray").pack(side="left")
        ttk.Button(bar, text="Borrar datos guardados", command=self._clear).pack(side="right")

        # Tabla
        table = ttk.Frame(self.root, padding=(10, 4))
        table.pack(fill="both", expand=True)
        cols = [("name", "Objeto", 230, "w"), ("tier", "Tier", 45, "center"), ("quality", "Calidad", 170, "w"),
                ("city", "Comprar en", 100, "w"), ("sell_city", "Vender en", 100, "w"),
                ("buy_price", "Precio compra", 95, "e"), ("bm_price", "Precio venta", 90, "e"), ("profit", "Benef./ud.", 85, "e"), ("percent", "%", 65, "e"),
                ("units", "Uds.", 55, "e"), ("invest", "Inversión máx.", 105, "e"),
                ("total_profit", "Benef. total", 95, "e"), ("age", "Datos", 60, "e"), ("source", "Origen", 85, "center")]
        self.tree = ttk.Treeview(table, columns=[c[0] for c in cols], show="headings", selectmode="browse")
        for key, title, width, anchor in cols:
            self.tree.heading(key, text=title, command=lambda k=key: self._sort(k))
            self.tree.column(key, width=width, anchor=anchor, stretch=key == "name")
        vs = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.tag_configure("live", background="#e7f6ea")
        self.tree.tag_configure("neg", foreground="#b3261e")
        self.tree.tag_configure("susp", foreground="#b26a00")
        self.tree.bind("<Double-1>", self._copy_name)

        # Registro de actividad
        bottom = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        bottom.pack(fill="x")
        self.status_var = tk.StringVar(value="Doble clic en una fila copia el nombre del objeto para buscarlo en el mercado.")
        ttk.Label(bottom, textvariable=self.status_var, foreground="gray").pack(side="left")
        self.log = tk.Text(self.root, height=5, state="disabled", font=("Consolas", 9), relief="flat", bg="#f4f4f4")
        self.log.pack(fill="x", padx=10, pady=(0, 10))

    # ------------------------------------------------------------------ captura
    def _start_capture(self) -> None:
        try:
            self.capture.start()
            self._set_capture(True, "Captura: activa — abre un mercado en el juego")
            self._log("Escuchando el tráfico del juego (puerto 5056).")
        except CaptureError as e:
            self._set_capture(False, "Captura: no disponible")
            self.warn_var.set(str(e) + "  Mientras tanto puedes usar «Actualizar precios».")
            self._log(str(e))

    def _set_capture(self, ok: bool, text: str) -> None:
        self.capture_var.set(("● " if ok else "○ ") + text)
        self.capture_lbl.configure(foreground="#1d7a3a" if ok else "#b3261e")

    # Llamados desde el hilo de captura -> se pasan a la cola de la interfaz
    def _on_live_prices(self, server: str, location: Optional[str], prices: dict, books: dict) -> None:
        srv = server or self.effective_server()
        n = self.store.upsert(srv, prices, source="juego", books=books)
        locs = sorted({k[2] for k in prices})
        self.events.put(("prices", f"{len(prices)} precios leídos en {', '.join(locs)} ({n} actualizados)"))

    def _on_game_status(self, kind: str, value: str) -> None:
        self.events.put((kind, value))

    def _tick(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "prices":
                    self._log(value)
                elif kind == "location":
                    self.location = value or None
                    self.location_var.set(f"Ubicación: {value or 'fuera de un mercado'}")
                    if value:
                        self._log(f"Has entrado en {value}.")
                elif kind == "server":
                    self.detected_server = value
                    self._log(f"Servidor detectado: {SERVER_LABEL.get(value, value)}.")
                    self._filters_changed()
                elif kind == "encrypted":
                    self.warn_var.set(value)
                    if value:
                        self._log(value)
                elif kind == "capture_error":
                    if not self.capture.running:
                        self._set_capture(False, "Captura: detenida")
                        self.warn_var.set(value)
                    self._log(value)
                elif kind == "log":
                    self._log(value)
                elif kind == "call":
                    value()
                elif kind == "api_progress":
                    self.progress["value"] = value
                elif kind == "api_done":
                    self._api_finished(value)
        except queue.Empty:
            pass

        srv = self.effective_server()
        self.server_info.set(f"({SERVER_LABEL[srv]})")
        if self.store.version != self.rendered_version:
            self.rendered_version = self.store.version
            self.live_var.set(f"Precios leídos del juego (24 h): {fmt(self.store.count_live(srv))}")
            self._refresh_table()
        # Actualización automática
        if self.auto_var.get() and not (self.api_thread and self.api_thread.is_alive()):
            every = max(5.0, self._num(self.auto_min_var.get(), 15)) * 60
            if time.time() - self.last_api_update >= every:
                self._api_refresh(auto=True)
        self.root.after(700, self._tick)

    def effective_server(self) -> str:
        return SERVERS.get(self.server_var.get()) or self.detected_server or "europe"

    # ------------------------------------------------------------------ filtros y tabla
    def _read_filters(self) -> dict:
        sel = lambda k: [v for v, var in self.vars[k].items() if var.get()]
        return {
            "server": self.server_var.get(), "premium": self.premium_var.get(), "best_only": self.best_var.get(),
            "buy_mode": self.buy_mode_var.get(), "search": self.search_var.get().strip(),
            **{k: v.get().strip() for k, v in self.entries.items()},
            "cats": sel("cats"), "tiers": sel("tiers"), "enchs": sel("enchs"), "quals": sel("quals"),
            "cities": sel("cities"), "auto": self.auto_var.get(), "auto_min": self.auto_min_var.get().strip(),
            "weight": self.entries["weight"].get().strip(),
            "strategy": STRATEGY_BY_LABEL.get(self.strategy_var.get(), "bm"), "hide_susp": self.susp_var.get(),
            "profile": PROFILE_BY_LABEL.get(self.profile_var.get(), "balanced"), "alert": self.alert_var.get(),
        }

    def _filters_changed(self) -> None:
        if hasattr(self, "_pending"):
            self.root.after_cancel(self._pending)
        self._pending = self.root.after(250, self._apply_filters)

    def _apply_filters(self) -> None:
        self._save_settings()
        self._refresh_table()

    @staticmethod
    def _num(s: str, default: float) -> float:
        try:
            return float(s.replace(".", "").replace(",", ".")) if s else default
        except ValueError:
            return default

    def _compute(self, f: dict, thresholds: bool = True) -> List[Opportunity]:
        """Oportunidades para los filtros dados (se puede llamar desde el hilo de la API)."""
        srv = self.effective_server()
        entries = self.store.load(srv, self._num(f["max_age"], 24))
        c = self.catalog
        search = f["search"] if thresholds else ""
        entries = {k: v for k, v in entries.items() if c.matches(k[0], f["cats"], f["tiers"], f["enchs"], search)}
        opps = compute(entries, f["cities"], f["quals"], f["premium"], f["buy_mode"],
                       strategy=f["strategy"], sell_cities=f["cities"], stats=self.store.load_stats(srv))
        if not thresholds:
            return opps
        min_pct, min_silver = self._num(f["min_pct"], -1e18), self._num(f["min_silver"], -1e18)
        max_cost = self._num(f["max_cost"], 1e18)
        opps = [o for o in opps if o.percent >= min_pct and o.profit >= min_silver and o.buy_price <= max_cost
                and not (f["hide_susp"] and o.suspicious)]
        if f["best_only"]:
            opps = best_per_item(opps)
        return opps

    def _refresh_table(self) -> None:
        f = self._read_filters()
        self.opps = self._compute(f)
        n_ids = len(self.catalog.variant_ids(f["cats"], f["tiers"], f["enchs"], f["search"]))
        self.count_var.set(f"{fmt(n_ids)} objetos en el filtro · {fmt(len(self.opps))} oportunidades")
        self._render()
        if self.plan_win is not None and self.plan_win.winfo_exists():
            self._fill_plan()

    def _sort_value(self, o: Opportunity):
        k = self.sort_key
        if k == "name":
            return self.catalog.name(o.item_id)
        if k == "tier":
            return self.catalog.label(o.item_id)
        if k == "age":
            return max(o.buy_age_h, o.bm_age_h)
        if k == "source":
            return (o.buy_source, o.bm_source)
        v = getattr(o, k)
        return -1 if v is None else v

    def _sort(self, key: str) -> None:
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, key not in ("name", "city", "sell_city", "tier")
        self._render()

    def _render(self) -> None:
        rows = sorted(self.opps, key=self._sort_value, reverse=self.sort_desc)
        self.tree.delete(*self.tree.get_children())
        c = self.catalog
        for o in rows[:MAX_ROWS]:
            q = QUALITY_NAMES[o.quality]
            if o.bm_quality != o.quality:
                q += f" (orden {QUALITY_NAMES[o.bm_quality]})"
            src = "Juego" if o.buy_source == o.bm_source == "juego" else (
                "API" if o.buy_source == o.bm_source == "api" else
                f"{o.buy_source.capitalize()}/{o.bm_source.capitalize()}".replace("Api", "API"))
            tags = []
            if "juego" in (o.buy_source, o.bm_source):
                tags.append("live")
            if o.profit <= 0:
                tags.append("neg")
            if o.suspicious:
                tags.append("susp")
            self.tree.insert("", "end", iid=f"{o.item_id}|{o.quality}|{o.city}|{o.sell_city}", tags=tags, values=(
                ("⚠ " if o.suspicious else "") + c.name(o.item_id), c.label(o.item_id), q, o.city, o.sell_city,
                fmt(o.buy_price), fmt(o.bm_price),
                fmt(o.profit), f"{o.percent:.1f} %", ("~" if o.estimated else "") + fmtn(o.units), fmtn(o.invest), fmtn(o.total_profit), ago(max(o.buy_age_h, o.bm_age_h)), src))
        arrow = " ▼" if self.sort_desc else " ▲"
        for col in self.tree["columns"]:
            title = self.tree.heading(col, "text").rstrip(" ▲▼")
            self.tree.heading(col, text=title + (arrow if col == self.sort_key else ""))

    def _copy_name(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        item_id = sel[0].split("|")[0]
        name = self.catalog.name(item_id)
        self.root.clipboard_clear()
        self.root.clipboard_append(name)
        self.status_var.set(f"Copiado al portapapeles: {name}  ({item_id})")

    # ------------------------------------------------------------------ API
    def _api_refresh(self, auto: bool = False) -> None:
        """Descarga de la API los precios de todos los mercados de la estrategia para todo lo que marquen
        los filtros, y después el historial (ventas diarias y precio medio) de lo que da beneficio."""
        if self.api_thread and self.api_thread.is_alive():
            return
        f = self._read_filters()
        bm = f["strategy"] == "bm"
        cats = [c for c in f["cats"] if not (bm and c in NOT_BLACK_MARKET)]  # el MN no compra recursos, etc.
        ids = self.catalog.variant_ids(cats, f["tiers"], f["enchs"])  # sin el buscador: todo el filtro
        self.last_api_update = time.time()
        if not ids or not f["cities"] or not f["quals"]:
            if not auto:
                messagebox.showinfo("Albion BM", "No hay objetos, ciudades o calidades seleccionadas."
                                    + (" El Mercado Negro solo compra equipo: para recursos, consumibles, "
                                       "monturas o artefactos elige una estrategia «Entre ciudades»." if bm else ""))
            return
        if not auto and len(ids) > 4000 and not messagebox.askyesno(
                "Albion BM", f"Vas a consultar {fmt(len(ids))} objetos; tardará unos minutos. ¿Continuar?"):
            return
        qualities = list(range(1, max(f["quals"]) + 1))
        sell_locs = [BLACK_MARKET] if bm else list(f["cities"])
        locations = f["cities"] + ([BLACK_MARKET] if bm else [])
        server = self.effective_server()
        self.api_stop = False
        self.api_btn.configure(state="disabled")
        self.api_stop_btn.configure(state="normal")
        self.progress["value"] = 0
        self._log(("Actualización automática: " if auto else "") +
                  f"descargando precios de {fmt(len(ids))} objetos en {len(locations)} mercados "
                  f"({SERVER_LABEL[server]})…")

        def work():
            try:
                rows = fetch_prices(server, ids, locations, qualities,
                                    progress=lambda n, t: self.events.put(("api_progress", n / t * 60)),
                                    should_stop=lambda: self.api_stop)
                prices, stamps = rows_to_prices(rows)
                n = self.store.upsert(server, prices, source="api", timestamps=stamps)
                self.events.put(("log", f"Precios: {fmt(len(prices))} recibidos, {fmt(n)} actualizados "
                                        "(los leídos en el juego más recientes se conservan)."))
                # Historial solo de lo que da beneficio: cuánto se vende al día y a qué precio medio
                best: Dict[str, float] = {}
                for o in self._compute(f, thresholds=False):
                    if o.profit > 0 and o.item_id in id_set:
                        best[o.item_id] = max(best.get(o.item_id, 0), o.profit)
                # ...y solo si no tenemos ya su historial reciente (cambia despacio; ahorra peticiones)
                fresh = {k[0] for k in self.store.load_stats(server, max_age_days=0.25) if k[2] in sell_locs}
                hist_ids = [i for i in sorted(best, key=lambda i: -best[i]) if i not in fresh][:MAX_HISTORY_ITEMS]
                if hist_ids and not self.api_stop:
                    self.events.put(("log", f"Descargando historial de ventas de {fmt(len(hist_ids))} objetos…"))
                    hist = fetch_history(server, hist_ids, sell_locs, qualities,
                                         progress=lambda n, t: self.events.put(("api_progress", 60 + n / t * 40)),
                                         should_stop=lambda: self.api_stop)
                    stats = history_to_stats(hist)
                    self.store.upsert_stats(server, stats)
                    self.events.put(("log", f"Historial: {fmt(len(stats))} series (ventas/día y precio medio)."))
                self.events.put(("api_done", "Actualización terminada." if not self.api_stop else "Actualización detenida."))
            except Exception as e:
                self.events.put(("api_done", f"Error consultando la API: {e}"))

        id_set = set(ids)
        self.api_thread = threading.Thread(target=work, daemon=True)
        self.api_thread.start()

    def _api_cancel(self) -> None:
        self.api_stop = True

    def _api_finished(self, msg: str) -> None:
        self.last_api_update = time.time()
        self.api_btn.configure(state="normal")
        self.api_stop_btn.configure(state="disabled")
        self.progress["value"] = 0
        self._log(msg)
        self.rendered_version = self.store.version
        self._refresh_table()
        self._check_alerts()

    def _check_alerts(self) -> None:
        """Avisa (sonido y registro) de oportunidades que no estaban en la actualización anterior."""
        keys = {(o.item_id, o.quality, o.city, o.sell_city): o for o in self.opps if not o.suspicious}
        if self.alert_seen is not None and self.alert_var.get():
            new = [o for k, o in keys.items() if k not in self.alert_seen]
            if new:
                top = max(new, key=lambda o: o.profit)
                self.root.bell()
                self._log(f"🔔 {len(new)} oportunidades nuevas. La mejor: {self.catalog.name(top.item_id)} "
                          f"({self.catalog.label(top.item_id)}) {top.city} → {top.sell_city}, "
                          f"+{fmt(top.profit)} por unidad ({top.percent:.0f} %).")
                self.status_var.set(f"🔔 {len(new)} oportunidades nuevas con tus filtros.")
        self.alert_seen = set(keys)

    def _show_calculators(self) -> None:
        from .calc_gui import CalculatorsWindow
        if self.calc_win is not None and self.calc_win.exists():
            self.calc_win.win.lift()
            return
        try:
            self.calc_win = CalculatorsWindow(self)
        except (OSError, ValueError) as e:
            messagebox.showerror("Albion BM", f"No se pudieron cargar las recetas: {e}")

    def _show_more(self):
        from .more_gui import MoreWindow
        if self.more_win is not None and self.more_win.exists():
            self.more_win.win.lift()
        else:
            self.more_win = MoreWindow(self)
        return self.more_win

    # ------------------------------------------------------------------ plan de inversión
    def _show_plan(self) -> None:
        if self.plan_win is not None and self.plan_win.winfo_exists():
            self.plan_win.lift()
            self._fill_plan()
            return
        win = self.plan_win = tk.Toplevel(self.root)
        win.title("Plan de inversión")
        win.geometry("1040x640")
        self.plan_info = tk.StringVar()
        ttk.Label(win, textvariable=self.plan_info, padding=(10, 8), wraplength=1000, justify="left").pack(fill="x")
        ttk.Label(win, text="Rutas (elige una para ver qué comprar):", padding=(10, 0)).pack(anchor="w")
        rcols = [("route", "Ruta", 300, "w"), ("n", "Objetos", 70, "e"), ("invest", "Inversión", 120, "e"),
                 ("profit", "Benef. estimado", 130, "e"), ("pct", "%", 70, "e"), ("weight", "Peso (kg)", 90, "e")]
        self.route_tree = ttk.Treeview(win, columns=[c[0] for c in rcols], show="headings", height=7,
                                       selectmode="browse")
        for key, title, width, anchor in rcols:
            self.route_tree.heading(key, text=title)
            self.route_tree.column(key, width=width, anchor=anchor)
        self.route_tree.pack(fill="x", padx=10, pady=4)
        self.route_tree.bind("<<TreeviewSelect>>", lambda e: self._fill_plan_lines())
        lcols = [("name", "Objeto", 250, "w"), ("tier", "Tier", 50, "center"), ("quality", "Calidad", 90, "w"),
                 ("buy", "Comprar en", 100, "w"), ("sell", "Vender en", 100, "w"), ("units", "Uds.", 60, "e"),
                 ("price", "Precio compra", 100, "e"), ("invest", "Inversión", 110, "e"),
                 ("profit", "Beneficio", 110, "e")]
        frame = ttk.Frame(win, padding=(10, 0, 10, 10))
        frame.pack(fill="both", expand=True)
        self.line_tree = ttk.Treeview(frame, columns=[c[0] for c in lcols], show="headings", selectmode="browse")
        for key, title, width, anchor in lcols:
            self.line_tree.heading(key, text=title)
            self.line_tree.column(key, width=width, anchor=anchor, stretch=key == "name")
        vs = ttk.Scrollbar(frame, orient="vertical", command=self.line_tree.yview)
        self.line_tree.configure(yscrollcommand=vs.set)
        self.line_tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self._fill_plan()

    def _fill_plan(self) -> None:
        f = self._read_filters()
        capital = self._num(f["capital"], 0)
        weight = self._num(f["weight"], 0) or None
        prof = PROFILES[f["profile"]]
        self.route_tree.delete(*self.route_tree.get_children())
        self.plans: Dict[str, list] = {}
        if capital <= 0:
            self.plan_info.set("Escribe tu dinero en «Capital» (y, si quieres, la «Carga máx.» de tu montura) "
                               "en la ventana principal.")
            self._fill_plan_lines()
            return
        w_of = self.catalog.weight
        lines, left = plan(self.opps, capital, profile=f["profile"], max_weight=weight, weight_of=w_of)
        rows = []
        if lines:
            rows.append(("__all__", "Todas las rutas mezcladas" + (" (un cargamento)" if weight else ""), lines))
        for r in plan_routes(self.opps, capital, f["profile"], weight, w_of):
            rows.append((f"{r.buy_city}|{r.sell_city}", f"{r.buy_city} → {r.sell_city}", r.lines))
        for iid, label, ls in rows:
            inv, prof_total = sum(l.invest for l in ls), sum(l.profit for l in ls)
            self.plans[iid] = ls
            self.route_tree.insert("", "end", iid=iid, values=(
                label, len(ls), fmt(inv), fmt(prof_total), f"{prof_total / inv * 100:.1f} %",
                f"{sum(l.weight for l in ls):.0f}"))
        self.plan_info.set(
            f"Capital: {fmt(capital)}" + (f" · Carga máx.: {weight:g} kg" if weight else "") +
            f" · Estrategia: {STRATEGIES[f['strategy']]} · Perfil «{prof.name}»: {prof.description}\n"
            + ("Las unidades con «~» son estimadas por las ventas diarias. Nunca se incluyen precios sospechosos. "
               "Comprueba el precio en el juego antes de comprar." if rows else
               "No hay oportunidades válidas para este perfil: pulsa «Actualizar precios», afloja los filtros "
               "o elige un perfil menos estricto."))
        if rows:
            self.route_tree.selection_set(rows[0][0])
        self._fill_plan_lines()

    def _fill_plan_lines(self) -> None:
        self.line_tree.delete(*self.line_tree.get_children())
        sel = self.route_tree.selection()
        c = self.catalog
        for l in self.plans.get(sel[0], []) if sel else []:
            o = l.opp
            self.line_tree.insert("", "end", values=(
                c.name(o.item_id), c.label(o.item_id), QUALITY_NAMES[o.quality], o.city, o.sell_city,
                ("~" if o.estimated else "") + fmt(l.units), fmt(o.buy_price), fmt(l.invest), fmt(l.profit)))

    # ------------------------------------------------------------------ varios
    def _export(self) -> None:
        """Genera el informe para pegárselo a Claude: lo copia al portapapeles y lo guarda en Documentos."""
        self._refresh_table()
        f = self._read_filters()
        srv = self.effective_server()
        capital = self._num(f["capital"], 0) or None
        filters_text = (f"categorías {', '.join(f['cats']) or 'ninguna'}; tiers {', '.join(map(str, f['tiers']))}; "
                        f"encantamientos {', '.join(map(str, f['enchs']))}; calidades "
                        f"{', '.join(QUALITY_NAMES[q] for q in f['quals'])}; ciudades {', '.join(f['cities'])}; "
                        f"beneficio mín. {f['min_pct'] or '—'} % y {f['min_silver'] or '—'} de plata; "
                        f"precio máx. por unidad {f['max_cost'] or 'sin límite'}"
                        + ("; solo la mejor ruta por objeto" if f["best_only"] else "")
                        + ("; precios sospechosos ocultos" if f["hide_susp"] else ""))
        text = build_report(self.opps, self.catalog, server=srv, premium=f["premium"], buy_mode=f["buy_mode"],
                            max_age_h=self._num(f["max_age"], 24), capital=capital, location=self.location,
                            live_count=self.store.count_live(srv), filters_text=filters_text,
                            strategy=f["strategy"], profile=f["profile"],
                            max_weight=self._num(f["weight"], 0) or None)
        try:
            path = save_report(text)
        except OSError as e:
            path = None
            self._log(f"No se pudo guardar el informe: {e}")
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._log(f"Informe exportado ({len(self.opps)} oportunidades)" + (f": {path}" if path else "."))
        messagebox.showinfo("Exportar para Claude", (
            "El informe está copiado en el portapapeles"
            + (f" y guardado en:\n{path}" if path else "") +
            "\n\nPégalo (Ctrl+V) o adjunta el archivo en tu conversación con Claude y pregunta, por ejemplo:\n"
            "«Tengo 25 millones, ¿en qué me vale más la pena invertir?»"))

    def _clear(self) -> None:
        if messagebox.askyesno("Albion BM", "¿Borrar todos los precios guardados?"):
            self.store.clear()
            self._log("Datos borrados.")

    def _log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("[%H:%M:%S] ") + msg + "\n")
        self.log.see("end")
        lines = int(self.log.index("end-1c").split(".")[0])
        if lines > 300:
            self.log.delete("1.0", f"{lines - 300}.0")
        self.log.configure(state="disabled")

    def _help(self) -> None:
        messagebox.showinfo("Cómo se usa", (
            "LO RÁPIDO\n"
            "1. Elige la estrategia (arriba a la derecha) y marca categorías, tiers y ciudades.\n"
            "2. Pulsa «Actualizar precios»: descarga todos los mercados de golpe.\n"
            "3. Escribe tu Capital (y la Carga de tu montura), elige un Perfil y pulsa «Plan de inversión».\n\n"
            "ESTRATEGIAS\n"
            "• Ciudad → Mercado Negro: solo equipo. Venta inmediata, pero hay que cruzar zona roja.\n"
            "• Entre ciudades · venta rápida: vendes al momento a las órdenes de compra de otra ciudad.\n"
            "• Entre ciudades · orden de venta: pones tu orden; más margen, pero tarda en venderse.\n"
            "Las categorías Recursos, Consumibles, Monturas y Artefactos solo sirven entre ciudades.\n\n"
            "SEÑALES\n"
            "• ⚠ = el precio de venta supera 1,6 veces la media de la semana: suele ser un dato viejo o una trampa.\n"
            "• «~» en Uds. = cantidad estimada por las ventas diarias. Sin «~» = leída de tu juego.\n"
            "• Filas verdes = precios leídos de tu juego (abre el mercado con la app en marcha; requiere Npcap).\n\n"
            "Doble clic en una fila copia el nombre del objeto. «Exportar para Claude» genera un informe para "
            "pegárselo a Claude y preguntarle en qué invertir.\n\n"
            "La app solo escucha el tráfico y consulta una API pública; no modifica ni automatiza el juego."))

    def _on_close(self) -> None:
        self.api_stop = True
        self._save_settings()
        self.capture.stop()
        self.store.close()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        App(root)
    except Exception as e:
        messagebox.showerror("Albion BM", f"No se pudo iniciar: {e}")
        raise
    root.mainloop()
