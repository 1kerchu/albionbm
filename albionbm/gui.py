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
from .api import fetch_bm_history, fetch_prices, history_to_volumes, rows_to_prices
from .calc import QUALITY_NAMES, Opportunity, best_per_item, compute
from .export import build_report, save_report
from .capture import Capture, CaptureError
from .game import BLACK_MARKET, CITIES, GameListener
from .items import CATEGORY_NAMES, Catalog, load_items
from .store import PriceStore, default_db_path

SERVERS = {"Automático": None, "Europa": "europe", "América (West)": "west", "Asia (East)": "east"}
SERVER_LABEL = {"europe": "Europa", "west": "América", "east": "Asia"}
MAX_ROWS = 1000

DEFAULTS = {
    "server": "Automático", "premium": True, "buy_mode": "instant", "best_only": True,
    "min_pct": "10", "min_silver": "5000", "max_cost": "", "max_age": "6", "search": "", "capital": "", "auto": False, "auto_min": "15",
    "cats": ["weapons", "armors", "head", "shoes", "offhands", "bags", "capes"],
    "tiers": [4, 5, 6], "enchs": [0, 1], "quals": [1, 2, 3], "cities": list(CITIES),
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
        self.settings = self._load_settings()

        root.title(f"Albion · Mercado Negro  v{__version__}")
        root.geometry("1320x820")
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
        checks(filt, "cities", CITIES, lambda v: "Comprar en" if v is None else v, 4)

        opts = ttk.LabelFrame(filt, text="Opciones", padding=6)
        opts.grid(row=0, column=5, sticky="nsew", pady=4)
        self.premium_var = tk.BooleanVar(value=s["premium"])
        ttk.Checkbutton(opts, text="Prémium (impuesto 4 %)", variable=self.premium_var,
                        command=self._filters_changed).grid(row=0, column=0, sticky="w")
        self.best_var = tk.BooleanVar(value=s["best_only"])
        ttk.Checkbutton(opts, text="Solo mejor ciudad", variable=self.best_var,
                        command=self._filters_changed).grid(row=1, column=0, sticky="w")
        self.buy_mode_var = tk.StringVar(value=s["buy_mode"])
        ttk.Radiobutton(opts, text="Compra directa", value="instant", variable=self.buy_mode_var,
                        command=self._filters_changed).grid(row=2, column=0, sticky="w")
        ttk.Radiobutton(opts, text="Orden de compra (+2,5 %)", value="order", variable=self.buy_mode_var,
                        command=self._filters_changed).grid(row=3, column=0, sticky="w")

        # Búsqueda y límites
        row2 = ttk.Frame(self.root, padding=(10, 4, 10, 0))
        row2.pack(fill="x")
        ttk.Label(row2, text="Buscar:").pack(side="left")
        self.search_var = tk.StringVar(value=s["search"])
        self.search_var.trace_add("write", lambda *a: self._filters_changed())
        ttk.Entry(row2, textvariable=self.search_var, width=22).pack(side="left", padx=(4, 12))
        self.entries: Dict[str, tk.StringVar] = {}
        for key, label in [("min_pct", "Benef. mín. %"), ("min_silver", "Benef. mín. plata"),
                           ("max_cost", "Presupuesto máx."), ("max_age", "Datos máx. (h)"),
                           ("capital", "Capital")]:
            ttk.Label(row2, text=label).pack(side="left")
            var = tk.StringVar(value=s[key])
            ttk.Entry(row2, textvariable=var, width=10 if key == "capital" else 8).pack(side="left", padx=(4, 10))
            var.trace_add("write", lambda *a: self._filters_changed())
            self.entries[key] = var

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
        self.progress = ttk.Progressbar(bar, length=140, mode="determinate")
        self.progress.pack(side="left", padx=8)
        self.count_var = tk.StringVar()
        ttk.Label(bar, textvariable=self.count_var, foreground="gray").pack(side="left")
        ttk.Button(bar, text="Borrar datos guardados", command=self._clear).pack(side="right")
        ttk.Button(bar, text="Exportar para Claude", command=self._export).pack(side="right", padx=8)

        # Tabla
        table = ttk.Frame(self.root, padding=(10, 4))
        table.pack(fill="both", expand=True)
        cols = [("name", "Objeto", 230, "w"), ("tier", "Tier", 45, "center"), ("quality", "Calidad", 170, "w"),
                ("city", "Comprar en", 100, "w"), ("buy_price", "Precio compra", 95, "e"),
                ("bm_price", "Paga MN", 90, "e"), ("profit", "Benef./ud.", 85, "e"), ("percent", "%", 65, "e"),
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

    def _refresh_table(self) -> None:
        f = self._read_filters()
        max_age = self._num(f["max_age"], 24)
        entries = self.store.load(self.effective_server(), max_age)
        c = self.catalog
        entries = {k: v for k, v in entries.items()
                   if c.matches(k[0], f["cats"], f["tiers"], f["enchs"], f["search"])}
        opps = compute(entries, f["cities"], f["quals"], f["premium"], f["buy_mode"],
                       volumes=self.store.load_volumes(self.effective_server()))
        min_pct, min_silver = self._num(f["min_pct"], -1e18), self._num(f["min_silver"], -1e18)
        max_cost = self._num(f["max_cost"], 1e18)
        opps = [o for o in opps if o.percent >= min_pct and o.profit >= min_silver and o.buy_price <= max_cost]
        if f["best_only"]:
            opps = best_per_item(opps)
        self.opps = opps
        n_ids = len(c.variant_ids(f["cats"], f["tiers"], f["enchs"], f["search"]))
        self.count_var.set(f"{fmt(n_ids)} objetos en el filtro · {fmt(len(opps))} oportunidades")
        self._render()

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
            self.sort_key, self.sort_desc = key, key not in ("name", "city", "tier")
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
            self.tree.insert("", "end", iid=f"{o.item_id}|{o.quality}|{o.city}", tags=tags, values=(
                c.name(o.item_id), c.label(o.item_id), q, o.city, fmt(o.buy_price), fmt(o.bm_price),
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
        """Descarga de la API los precios de todas las ciudades y del MN (y el volumen diario del MN)
        para todo lo que marquen los filtros, sin tener que ir mercado a mercado."""
        if self.api_thread and self.api_thread.is_alive():
            return
        f = self._read_filters()
        ids = self.catalog.variant_ids(f["cats"], f["tiers"], f["enchs"])  # sin el buscador: todo el filtro
        self.last_api_update = time.time()
        if not ids or not f["cities"] or not f["quals"]:
            if not auto:
                messagebox.showinfo("Albion BM", "No hay objetos, ciudades o calidades seleccionadas.")
            return
        if not auto and len(ids) > 4000 and not messagebox.askyesno(
                "Albion BM", f"Vas a consultar {fmt(len(ids))} objetos; tardará unos minutos. ¿Continuar?"):
            return
        qualities = list(range(1, max(f["quals"]) + 1))
        locations = f["cities"] + [BLACK_MARKET]
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
                # Volumen diario del MN solo para lo que el MN está comprando
                bm_ids = sorted({k[0] for k in prices if k[2] == BLACK_MARKET and k[3] == "request"})
                if bm_ids and not self.api_stop:
                    hist = fetch_bm_history(server, bm_ids, qualities,
                                            progress=lambda n, t: self.events.put(("api_progress", 60 + n / t * 40)),
                                            should_stop=lambda: self.api_stop)
                    vols = history_to_volumes(hist)
                    self.store.upsert_volumes(server, vols)
                    self.events.put(("log", f"Volumen diario del Mercado Negro: {fmt(len(vols))} objetos."))
                self.events.put(("api_done", "Actualización terminada." if not self.api_stop else "Actualización detenida."))
            except Exception as e:
                self.events.put(("api_done", f"Error consultando la API: {e}"))

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
                        f"presupuesto máx. por objeto {f['max_cost'] or 'sin límite'}"
                        + ("; solo la mejor ciudad por objeto" if f["best_only"] else ""))
        text = build_report(self.opps, self.catalog, server=srv, premium=f["premium"], buy_mode=f["buy_mode"],
                            max_age_h=self._num(f["max_age"], 24), capital=capital, location=self.location,
                            live_count=self.store.count_live(srv), filters_text=filters_text)
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
            "1. Deja esta app abierta y juega normalmente.\n"
            "2. En el juego, abre el Mercado Negro de Caerleon (pestaña Vender) y navega por las categorías: "
            "la app guarda lo que paga.\n"
            "3. Ve a otras ciudades, abre el mercado (pestaña Comprar) y navega: la app guarda los precios.\n"
            "4. Las filas en verde usan datos leídos de tu juego. Para lo que no hayas visto, pulsa "
            "«Actualizar precios».\n\n"
            "Doble clic en una fila copia el nombre del objeto para pegarlo en el buscador del mercado.\n\n"
            "«Exportar para Claude» genera un informe (copiado al portapapeles y guardado en Documentos\\AlbionBM) "
            "para pegárselo a Claude y preguntarle en qué invertir. Rellena «Capital» para incluir un reparto.\n\n"
            "Requisito: Npcap (https://npcap.com). La app solo escucha el tráfico; no modifica el juego."))

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
