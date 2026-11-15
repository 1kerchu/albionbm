"""Cliente de la API pública de Albion Online Data Project (para completar ciudades no visitadas)."""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from .game import BLACK_MARKET

HOSTS = {"europe": "europe.albion-online-data.com", "west": "west.albion-online-data.com",
         "east": "east.albion-online-data.com"}
USER_AGENT = "AlbionBM/1.0 (comparador de mercado negro)"


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


def fetch_prices(server: str, ids: List[str], locations: List[str], qualities: List[int],
                 progress: Optional[Callable[[int, int], None]] = None,
                 should_stop: Optional[Callable[[], bool]] = None) -> List[dict]:
    host = HOSTS[server]
    rows: List[dict] = []
    chunks = chunk_ids(ids)
    for n, chunk in enumerate(chunks, 1):
        if should_stop and should_stop():
            break
        url = (f"https://{host}/api/v2/stats/prices/{','.join(urllib.parse.quote(i) for i in chunk)}.json?"
               + urllib.parse.urlencode({"locations": ",".join(locations), "qualities": ",".join(map(str, qualities))}))
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    rows.extend(json.loads(resp.read().decode("utf-8")))
                break
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    time.sleep(3 * (attempt + 1))
                    continue
                raise
            except urllib.error.URLError:
                if attempt == 3:
                    raise
                time.sleep(2)
        if progress:
            progress(n, len(chunks))
        time.sleep(0.35)  # respeta el límite de peticiones de la API
    return rows
