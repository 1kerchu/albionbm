"""Almacén local de precios (SQLite). Guarda el precio más reciente de cada objeto/calidad/mercado."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Dict, Optional, Tuple

# clave: (item_id, calidad, ubicación, tipo) -> (precio, timestamp, origen, profundidad)
# profundidad: [[precio, cantidad], ...] del mejor al peor, o None si no se conoce (datos de la API)
Key = Tuple[str, int, str, str]
Entry = Tuple[int, float, str, Optional[list]]


def default_db_path() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    folder = os.path.join(base, "AlbionBM")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "precios.sqlite3")


class PriceStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or default_db_path()
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS prices (
                server TEXT, item TEXT, quality INTEGER, location TEXT, kind TEXT,
                price INTEGER, ts REAL, source TEXT,
                PRIMARY KEY (server, item, quality, location, kind))"""
        )
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS stats (
                server TEXT, item TEXT, quality INTEGER, location TEXT, daily REAL, avg_price REAL, ts REAL,
                PRIMARY KEY (server, item, quality, location))"""
        )
        self._db.execute("DROP TABLE IF EXISTS volumes")  # tabla de la v1.2, sustituida por stats
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS movements (
                key TEXT PRIMARY KEY, server TEXT, ts REAL, kind TEXT, item TEXT, quality INTEGER,
                qty INTEGER, silver REAL, location TEXT)"""
        )
        cols = [r[1] for r in self._db.execute("PRAGMA table_info(prices)")]
        if "book" not in cols:  # migración desde la v1.0
            self._db.execute("ALTER TABLE prices ADD COLUMN book TEXT")
        self._db.commit()
        self.version = 0  # aumenta cada vez que cambian los datos
        self.movements_version = 0

    def upsert(self, server: str, prices: Dict[Key, int], ts: Optional[float] = None,
               source: str = "juego", timestamps: Optional[Dict[Key, float]] = None,
               books: Optional[Dict[Key, list]] = None) -> int:
        """Guarda precios; solo sustituye si el dato nuevo es igual o más reciente. Devuelve cuántos se guardaron."""
        now = ts if ts is not None else time.time()
        rows = []
        for (item, q, loc, kind), price in prices.items():
            t = timestamps.get((item, q, loc, kind), now) if timestamps else now
            book = books.get((item, q, loc, kind)) if books else None
            rows.append((server, item, int(q), loc, kind, int(price), float(t), source,
                         json.dumps(book) if book else None))
        if not rows:
            return 0
        with self._lock:
            before = self._db.total_changes
            self._db.executemany(
                """INSERT INTO prices (server, item, quality, location, kind, price, ts, source, book)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(server, item, quality, location, kind) DO UPDATE SET
                     price=excluded.price, ts=excluded.ts, source=excluded.source, book=excluded.book
                   WHERE excluded.ts >= prices.ts""",
                rows,
            )
            self._db.commit()
            changed = self._db.total_changes - before
            if changed:
                self.version += 1
            return changed

    def load(self, server: str, max_age_hours: float) -> Dict[Key, Entry]:
        min_ts = time.time() - max_age_hours * 3600
        with self._lock:
            cur = self._db.execute(
                "SELECT item, quality, location, kind, price, ts, source, book FROM prices WHERE server=? AND ts>=?",
                (server, min_ts),
            )
            return {(r[0], r[1], r[2], r[3]): (r[4], r[5], r[6], json.loads(r[7]) if r[7] else None)
                    for r in cur}

    def upsert_stats(self, server: str, stats: Dict[Tuple[str, int, str], Tuple[float, Optional[float]]]) -> None:
        """Historial por (objeto, calidad, ubicación): (unidades vendidas al día, precio medio 7 días)."""
        now = time.time()
        with self._lock:
            self._db.executemany(
                "INSERT OR REPLACE INTO stats VALUES (?,?,?,?,?,?,?)",
                [(server, item, int(q), loc, float(v[0]), v[1], now) for (item, q, loc), v in stats.items()],
            )
            self._db.commit()
            self.version += 1

    def load_stats(self, server: str, max_age_days: float = 3) -> Dict[Tuple[str, int, str], Tuple[float, Optional[float]]]:
        with self._lock:
            cur = self._db.execute(
                "SELECT item, quality, location, daily, avg_price FROM stats WHERE server=? AND ts>=?",
                (server, time.time() - max_age_days * 86400))
            return {(r[0], r[1], r[2]): (r[3], r[4]) for r in cur}

    # ---- tus compras y ventas leídas del juego
    def add_movement(self, m: dict) -> bool:
        """Guarda un movimiento; devuelve False si ya estaba (p. ej. un correo abierto dos veces)."""
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO movements VALUES (?,?,?,?,?,?,?,?,?)",
                (m["key"], m.get("server", ""), float(m["ts"]), m["kind"], m["item"], int(m.get("quality") or 0),
                 int(m["qty"]), float(m["silver"]), m.get("location") or ""))
            self._db.commit()
            if cur.rowcount:
                self.movements_version += 1
            return bool(cur.rowcount)

    def load_movements(self, server: str) -> list:
        with self._lock:
            cur = self._db.execute(
                "SELECT key, ts, kind, item, quality, qty, silver, location FROM movements WHERE server=? ORDER BY ts",
                (server,))
            return [dict(zip(("key", "ts", "kind", "item", "quality", "qty", "silver", "location"), r)) for r in cur]

    def delete_movement(self, key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM movements WHERE key=?", (key,))
            self._db.commit()
            self.movements_version += 1

    def count_live(self, server: str, since_hours: float = 24) -> int:
        with self._lock:
            return self._db.execute(
                "SELECT COUNT(*) FROM prices WHERE server=? AND source='juego' AND ts>=?",
                (server, time.time() - since_hours * 3600),
            ).fetchone()[0]

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM prices")
            self._db.execute("DELETE FROM stats")
            self._db.commit()
            self.version += 1

    def close(self) -> None:
        with self._lock:
            self._db.close()

