"""Cliente de la API pública de Albion Online Data Project (para completar ciudades no visitadas)."""
from __future__ import annotations

import gzip
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from .game import BLACK_MARKET

HOSTS = {"europe": "europe.albion-online-data.com", "west": "west.albion-online-data.com",
         "east": "east.albion-online-data.com"}
USER_AGENT = "AlbionBM/1.2 (comparador de mercado negro)"
PAUSE = 0.6


def parse_api_date(s: Optional[str]) -> Optional[float]:
    if not s or s.startswith("0001"):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", ""))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc).timestamp()


def chunk_ids(ids: List[str], max_chars: int = 1800) -> List[List[str]]:
    chunks, cur, length = [], [], 0
    for i in ids:
        if cur and length + len(i) + 1 > max_chars:
            chunks.append(cur)
            cur, length = [], 0
        cur.append(i)
        length += len(i) + 1
    if cur:
        chunks.append(cur)
    return chunks


def rows_to_prices(rows: List[dict]) -> Tuple[Dict[tuple, int], Dict[tuple, float]]:
    """Convierte filas de la API en precios con su fecha de observación."""
    prices, stamps = {}, {}
    for r in rows:
        loc = r.get("city")
        if loc not in (BLACK_MARKET, "Caerleon", "Bridgewatch", "Martlock", "Lymhurst", "Fort Sterling",
                       "Thetford", "Brecilien"):
            continue
        item, q = r["item_id"], int(r.get("quality") or 1)
        for kind, pf, df in (("offer", "sell_price_min", "sell_price_min_date"),
                             ("request", "buy_price_max", "buy_price_max_date")):
            price, ts = r.get(pf) or 0, parse_api_date(r.get(df))
            if price > 0 and ts:
                prices[(item, q, loc, kind)] = int(price)
                stamps[(item, q, loc, kind)] = ts
    return prices, stamps


def _get_json(url: str):
    """GET con reintentos (límite de peticiones y errores de red). Pide gzip para ir más rápido."""
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return json.loads(data.decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == 4:
                raise
            time.sleep(3)
    raise RuntimeError("La API no responde (límite de peticiones). Inténtalo en unos minutos.")


def _fetch_chunks(build_url: Callable[[List[str]], str], ids: List[str],
                  progress: Optional[Callable[[int, int], None]], should_stop: Optional[Callable[[], bool]],
                  max_chars: int = 1800) -> List[dict]:
    rows: List[dict] = []
    chunks = chunk_ids(ids, max_chars)
    for n, chunk in enumerate(chunks, 1):
        if should_stop and should_stop():
            break
        rows.extend(_get_json(build_url(chunk)) or [])
        if progress:
            progress(n, len(chunks))
        time.sleep(PAUSE)  # respeta el límite de peticiones de la API (180/min, 300/5 min)
    return rows


def _ids_path(chunk: List[str]) -> str:
    return ",".join(urllib.parse.quote(i) for i in chunk)


def fetch_prices(server: str, ids: List[str], locations: List[str], qualities: List[int],
                 progress: Optional[Callable[[int, int], None]] = None,
                 should_stop: Optional[Callable[[], bool]] = None) -> List[dict]:
    """Precios actuales (mejor venta y mejor compra) por objeto, calidad y ciudad."""
    host = HOSTS[server]
    query = urllib.parse.urlencode({"locations": ",".join(locations), "qualities": ",".join(map(str, qualities))})
    return _fetch_chunks(lambda c: f"https://{host}/api/v2/stats/prices/{_ids_path(c)}.json?{query}",
                         ids, progress, should_stop)


def fetch_bm_history(server: str, ids: List[str], qualities: List[int],
                     progress: Optional[Callable[[int, int], None]] = None,
                     should_stop: Optional[Callable[[], bool]] = None) -> List[dict]:
    """Historial diario de ventas en el Mercado Negro (cuántas unidades se venden al día)."""
    host = HOSTS[server]
    query = urllib.parse.urlencode({"locations": BLACK_MARKET, "qualities": ",".join(map(str, qualities)),
                                    "time-scale": 24})
    return _fetch_chunks(lambda c: f"https://{host}/api/v2/stats/history/{_ids_path(c)}.json?{query}",
                         ids, progress, should_stop)


def history_to_volumes(rows: List[dict], days: int = 7, now: Optional[float] = None) -> Dict[tuple, float]:
    """Media de unidades vendidas al día en el MN en los últimos `days` días: {(item, calidad): unidades/día}."""
    now = now or time.time()
    since = now - days * 86400
    out: Dict[tuple, float] = {}
    for r in rows:
        if r.get("location") not in (BLACK_MARKET, None):
            continue
        total = 0
        for d in r.get("data") or []:
            ts = parse_api_date(d.get("timestamp"))
            if ts and ts >= since:
                total += int(d.get("item_count") or 0)
        key = (r.get("item_id"), int(r.get("quality") or 1))
        out[key] = out.get(key, 0.0) + total / days
    return out
