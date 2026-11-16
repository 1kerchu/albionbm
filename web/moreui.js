// Pestaña «Más»: favoritos con avisos de precio, historial de precios y registro de ganancias.
(function () {
  "use strict";
  const A = window.AlbionApp, C = window.AlbionCalc, K = window.AlbionCalculators, U = window.AlbionCalcUI;
  const $ = (id) => document.getElementById(id);
  const { fmt, esc, num } = A;
  const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) || d; } catch { return d; } };
  const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* sin almacenamiento */ } };
  const FAV_KEY = "albionbm.favs.v1", LEDGER_KEY = "albionbm.ledger.v1";
  const opt = (v, l) => `<option value="${esc(v)}">${esc(l)}</option>`;
  const cityColor = (c) => `var(--s${c === C.BLACK_MARKET ? 8 : C.CITIES.indexOf(c) + 1})`;

  // ================================================================ favoritos
  let favs = load(FAV_KEY, []);   // [{id, quality, kind: "below"|"above", target}]
  let favHits = new Set(), autoTimer = null;

  function addFav(id, quality) {
    if (favs.some((f) => f.id === id && f.quality === quality)) { A.toast("Ya está en favoritos."); return; }
    favs.unshift({ id, quality: quality || 1, kind: "below", target: 0 });
    save(FAV_KEY, favs); renderFavs();
    A.toast("Añadido a favoritos: " + A.itemName(id));
  }

  /** Precio de venta más barato y más caro entre las ciudades marcadas en Ajustes. */
  function favPrices(f) {
    let min = null, max = null;
    for (const city of A.readForm().cities) {
      const e = A.entries.get([f.id, f.quality, city, "offer"].join("|"));
      if (!e) continue;
      if (!min || e.p < min.p) min = { p: e.p, city, ts: e.ts };
      if (!max || e.p > max.p) max = { p: e.p, city, ts: e.ts };
    }
    return { min, max };
  }
  const favHit = (f, pr) => f.target > 0 && (f.kind === "below" ? pr.min && pr.min.p <= f.target : pr.max && pr.max.p >= f.target);

  function renderFavs() {
    if (!favs.length) {
      $("fList").innerHTML = '<div class="empty">Sin favoritos. Búscalos arriba o pulsa ☆ en una oportunidad.</div>';
      return;
    }
    const now = Date.now() / 1000;
    $("fList").innerHTML = favs.map((f, i) => {
      const pr = favPrices(f), hit = favHit(f, pr);
      return `<article class="card" data-i="${i}">
        <div class="top"><div><div class="name">${esc(A.itemName(f.id))}</div>
          <div class="sub">${A.itemLabel(f.id)} · ${C.QUALITY_NAMES[f.quality]}</div></div>
          <button class="star on" data-act="del" aria-label="Quitar de favoritos">✕</button></div>
        <dl><div><dt>Más barato</dt><dd>${pr.min ? fmt(pr.min.p) : "—"}</dd></div>
          <div><dt>En</dt><dd>${pr.min ? esc(pr.min.city) : "—"}</dd></div>
          <div><dt>Datos</dt><dd>${pr.min ? A.ago((now - pr.min.ts) / 3600) : "—"}</dd></div>
          <div><dt>Más caro</dt><dd>${pr.max ? fmt(pr.max.p) : "—"}</dd></div>
          <div><dt>En</dt><dd>${pr.max ? esc(pr.max.city) : "—"}</dd></div></dl>
        <div class="fav-row"><select data-act="kind" aria-label="Tipo de aviso">
            <option value="below"${f.kind === "below" ? " selected" : ""}>Avísame si baja de</option>
            <option value="above"${f.kind === "above" ? " selected" : ""}>Avísame si sube de</option></select>
          <input data-act="target" type="text" inputmode="numeric" placeholder="precio" value="${f.target || ""}">
          <button data-act="hist">Historial</button></div>
        ${hit ? `<div class="hit">✔ Se cumple: ${f.kind === "below" ? `${fmt(pr.min.p)} en ${esc(pr.min.city)}` : `${fmt(pr.max.p)} en ${esc(pr.max.city)}`}</div>` : ""}
      </article>`;
    }).join("");
  }

  async function checkFavs(silent) {
    if (!favs.length) { $("fStatus").textContent = "Añade algún favorito primero."; return; }
    const cities = A.readForm().cities;
    if (!cities.length) { $("fStatus").textContent = "Marca alguna ciudad en Ajustes."; return; }
    const ok = await U.fetchPrices([...new Set(favs.map((f) => f.id))], cities, [...new Set(favs.map((f) => f.quality))], "fStatus");
    if (!ok) return;
    $("fStatus").textContent = "Comprobado a las " + new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }) + ".";
    const hits = new Set(favs.filter((f) => favHit(f, favPrices(f))).map((f) => f.id + "|" + f.quality));
    const fresh = [...hits].filter((h) => !favHits.has(h));
    favHits = hits;
    renderFavs();
    if (fresh.length) {
      const msg = `${fresh.length} aviso(s) de precio: ${fresh.map((h) => A.itemName(h.split("|")[0])).slice(0, 3).join(", ")}`;
      A.toast("🔔 " + msg);
      if (silent && "Notification" in window && Notification.permission === "granted") {
        try { new Notification("Albion · Comercio", { body: msg }); } catch { /* no disponible en este navegador */ }
      }
    }
  }

  function setAuto(on) {
    clearInterval(autoTimer);
    if (on) {
      autoTimer = setInterval(() => checkFavs(true), 10 * 60 * 1000);
      if ("Notification" in window && Notification.permission === "default") Notification.requestPermission().catch(() => {});
    }
  }

  // ================================================================ historial de precios
  let histItem = null;
  const histId = () => (histItem ? (histItem.f || !Number($("hEnch").value) ? histItem.id : `${histItem.id}@${$("hEnch").value}`) : null);

  function pickHist(it, ench, quality) {
    histItem = it;
    $("hEnchWrap").hidden = !!it.f;
    $("hEnch").value = String(ench || 0);
    if (quality) $("hQual").value = String(quality);
    $("hItem").hidden = false; $("hRun").disabled = false;
    $("hItem").textContent = `${A.itemName(histId())} (${A.itemLabel(histId())})`;
    $("hChart").innerHTML = ""; $("hTable").innerHTML = ""; $("hStatus").textContent = "";
  }

  async function runHist() {
    const id = histId(), f = A.readForm();
    const equip = !["resources", "consumables", "mounts", "artefacts"].includes(histItem.c);
    const locs = f.cities.concat(equip ? [C.BLACK_MARKET] : []);
    if (!locs.length) { $("hStatus").textContent = "Marca alguna ciudad en Ajustes."; return; }
    $("hItem").textContent = `${A.itemName(id)} (${A.itemLabel(id)})`;
    $("hStatus").textContent = "Descargando historial…";
    let rows;
    try {
      rows = await A.getJson(`https://${f.server}.albion-online-data.com/api/v2/stats/history/${encodeURIComponent(id)}.json` +
        `?locations=${encodeURIComponent(locs.join(","))}&qualities=${$("hQual").value}&time-scale=24`);
    } catch (e) { $("hStatus").textContent = "Error: " + e.message; return; }
    const series = buildSeries(rows || [], Date.now() / 1000);
    if (!series.length) {
      $("hStatus").textContent = "La API no tiene ventas registradas de este objeto en los últimos 28 días.";
      $("hChart").innerHTML = ""; $("hTable").innerHTML = "";
      return;
    }
    $("hStatus").textContent = "";
    drawChart(series);
    drawTable(series);
  }

  /** Filas de la API -> [{city, points: [{day, price, count}]}], últimos 28 días, en el orden fijo de ciudades. */
  function buildSeries(rows, now) {
    const since = now - 28 * 86400, out = [];
    for (const r of rows) {
      const pts = [];
      for (const d of r.data || []) {
        const ts = C.parseApiDate(d.timestamp);
        if (ts && ts >= since && d.item_count > 0 && d.avg_price > 0) pts.push({ day: Math.floor(ts / 86400), price: d.avg_price, count: d.item_count });
      }
      if (pts.length) out.push({ city: r.location, points: pts.sort((a, b) => a.day - b.day) });
    }
    const order = (c) => (c === C.BLACK_MARKET ? 99 : C.CITIES.indexOf(c));
    return out.sort((a, b) => order(a.city) - order(b.city));
  }

  function niceTicks(lo, hi, n) {
    const step0 = (hi - lo) / n || 1, mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
    const ticks = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(v);
    return ticks;
  }
  const short = (v) => (v >= 1e6 ? (v / 1e6).toFixed(v >= 1e7 ? 0 : 1).replace(".", ",") + " M" : v >= 1e3 ? (v / 1e3).toFixed(v >= 1e4 ? 0 : 1).replace(".", ",") + " k" : String(Math.round(v)));
  const dayLabel = (day) => new Date(day * 86400000).toLocaleDateString("es-ES", { day: "numeric", month: "short", timeZone: "UTC" });

  function drawChart(series) {
    const W = 340, H = 200, L = 40, R = 8, T = 8, B = 22;
    const all = series.flatMap((s) => s.points);
    const days = [...new Set(all.map((p) => p.day))].sort((a, b) => a - b);
    const d0 = days[0], d1 = Math.max(days[days.length - 1], d0 + 1);
    // Un pico aislado (una venta absurda) aplastaría el resto: el eje se corta en 1,3 × el percentil 95
    const sorted = all.map((p) => p.price).sort((a, b) => a - b);
    const p95 = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))];
    const hi = Math.min(sorted[sorted.length - 1], p95 * 1.3), lo = Math.min(sorted[0], hi) * 0.95;
    const clipped = sorted[sorted.length - 1] > hi;
    const x = (d) => L + ((d - d0) / (d1 - d0)) * (W - L - R);
    const y = (v) => T + (1 - (Math.min(v, hi) - lo) / (hi - lo || 1)) * (H - T - B);
    const ticks = niceTicks(lo, hi, 4);
    const xt = [d0, Math.round((d0 + d1) / 2), d1];
    const svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Precio medio diario por ciudad">
      ${ticks.map((t) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(t)}" y2="${y(t)}"/><text class="axis" x="${L - 5}" y="${y(t) + 4}" text-anchor="end">${short(t)}</text>`).join("")}
      ${xt.map((d, i) => `<text class="axis" x="${x(d)}" y="${H - 6}" text-anchor="${i === 0 ? "start" : i === 2 ? "end" : "middle"}">${dayLabel(d)}</text>`).join("")}
      ${series.map((s) => `<path class="line" style="stroke:${cityColor(s.city)}" d="${s.points.map((p, i) => `${i ? "L" : "M"}${x(p.day).toFixed(1)},${y(p.price).toFixed(1)}`).join("")}"/>` +
        (s.points.length === 1 ? `<circle cx="${x(s.points[0].day)}" cy="${y(s.points[0].price)}" r="4" style="fill:${cityColor(s.city)}"/>` : "")).join("")}
      <line class="cross" id="hCross" y1="${T}" y2="${H - B}" x1="0" x2="0" visibility="hidden"/>
      <rect id="hHit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/></svg>`;
    $("hChart").innerHTML = `<div class="viz"><h3>Precio medio de venta por día</h3>
      <div class="legend">${series.map((s) => `<span style="--c:${cityColor(s.city)}">${esc(A.CITY_LABEL(s.city))}</span>`).join("")}</div>
      ${svg}<div class="tip" id="hTip" hidden></div>
      <p class="muted small" id="hHint">Toca la gráfica para ver los precios de un día.</p>
      ${clipped ? '<p class="muted small">Algún pico aislado queda fuera de la escala.</p>' : ""}</div>`;
    const hit = $("hHit"), cross = $("hCross"), tip = $("hTip");
    const move = (ev) => {
      const box = hit.getBoundingClientRect();
      const frac = Math.min(1, Math.max(0, (ev.clientX - box.left) / box.width));
      const target = d0 + frac * (d1 - d0);
      const day = days.reduce((a, b) => (Math.abs(b - target) < Math.abs(a - target) ? b : a));
      cross.setAttribute("x1", x(day)); cross.setAttribute("x2", x(day)); cross.setAttribute("visibility", "visible");
      const rows = series.map((s) => ({ s, p: s.points.find((q) => q.day === day) })).filter((r) => r.p);
      tip.innerHTML = `<b>${dayLabel(day)}</b>` + rows.map(({ s, p }) =>
        `<div><span><i style="--c:${cityColor(s.city)}"></i>${esc(A.CITY_LABEL(s.city))}</span><span>${fmt(p.price)}</span></div>`).join("");
      tip.hidden = false; $("hHint").hidden = true;
    };
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", (ev) => {
      if (ev.pointerType === "mouse") { cross.setAttribute("visibility", "hidden"); tip.hidden = true; $("hHint").hidden = false; }
    });
  }

  function drawTable(series) {
    const lastDay = Math.max(...series.flatMap((s) => s.points.map((p) => p.day)));
    $("hTable").innerHTML = `<table class="mats"><thead><tr><th>Ciudad</th><th>Último día</th><th>Media 7 d</th><th>Ventas/día</th></tr></thead><tbody>` +
      series.map((s) => {
        const week = s.points.filter((p) => p.day > lastDay - 7);
        const n = week.reduce((a, p) => a + p.count, 0);
        const avg = n ? week.reduce((a, p) => a + p.price * p.count, 0) / n : null;
        return `<tr><td>${esc(A.CITY_LABEL(s.city))}</td><td>${fmt(s.points[s.points.length - 1].price)}</td>
          <td>${fmt(avg)}</td><td>${(n / 7).toFixed(1).replace(".", ",")}</td></tr>`;
      }).join("") + "</tbody></table>";
  }

  // ================================================================ registro de ganancias
  let ledger = load(LEDGER_KEY, []);   // [{ts, name, qty, buy, sell, buyOrder, sellOrder, premium, profit, cost}]

  function ledgerDraft() {
    const buy = num($("lBuy").value, 0), sell = num($("lSell").value, 0), qty = Math.max(1, Math.floor(num($("lQty").value, 1)));
    if (buy <= 0 || sell <= 0) return null;
    const premium = A.readForm().premium, buyOrder = $("lBuyOrder").checked, sellOrder = $("lSellOrder").checked;
    const t = K.trade(buy, sell, qty, { premium, buyOrder, sellOrder });
    return { ts: Date.now(), name: $("lName").value.trim() || "Sin nombre", qty, buy, sell, buyOrder, sellOrder, premium,
      profit: Math.round(t.totalProfit), cost: Math.round(t.totalCost) };
  }

  function renderLedger() {
    const d = ledgerDraft();
    $("lPreview").textContent = d ? `Beneficio tras impuestos: ${d.profit > 0 ? "+" : ""}${fmt(d.profit)}` : "";
    const now = Date.now(), today = new Date().toDateString();
    const sum = (list) => list.reduce((a, e) => a + e.profit, 0);
    const tiles = [["Hoy", ledger.filter((e) => new Date(e.ts).toDateString() === today)],
      ["Últimos 7 días", ledger.filter((e) => now - e.ts < 7 * 864e5)], ["Total", ledger]];
    $("lTotals").innerHTML = tiles.map(([k, list]) => { const v = sum(list);
      return `<div class="tile"><div class="k">${k}</div><div class="v ${v > 0 ? "good" : v < 0 ? "bad" : ""}">${v > 0 ? "+" : ""}${fmt(v)}</div><div class="k">${list.length} op.</div></div>`; }).join("");
    $("lList").innerHTML = ledger.length ? ledger.map((e, i) => `<article class="card" data-i="${i}">
      <div class="top"><div><div class="name">${esc(e.name)}</div>
        <div class="sub">${new Date(e.ts).toLocaleDateString("es-ES")} · ${fmt(e.qty)} uds. · ${fmt(e.buy)} → ${fmt(e.sell)}</div></div>
        <div class="pct ${e.profit > 0 ? "good" : "bad"}">${e.profit > 0 ? "+" : ""}${fmt(e.profit)}<div class="sub">${e.cost ? (e.profit / e.cost * 100).toFixed(1).replace(".", ",") + " %" : ""}</div></div>
        <button class="star" data-act="del" aria-label="Borrar">✕</button></div></article>`).join("")
      : '<div class="empty">Todavía no has apuntado ninguna operación.</div>';
  }

  function ledgerCsv() {
    const q = (s) => `"${String(s).replace(/"/g, '""')}"`;
    return ["fecha;objeto;cantidad;precio_compra;precio_venta;orden_compra;orden_venta;premium;inversion;beneficio"].concat(
      ledger.map((e) => [new Date(e.ts).toISOString().slice(0, 10), q(e.name), e.qty, e.buy, e.sell, e.buyOrder ? "si" : "no",
        e.sellOrder ? "si" : "no", e.premium ? "si" : "no", e.cost, e.profit].join(";"))).join("\n");
  }

  // ================================================================ arranque
  function showKind() {
    const k = $("moreKind").value;
    $("more-favs").hidden = k !== "favs"; $("more-hist").hidden = k !== "hist"; $("more-ledger").hidden = k !== "ledger";
    if (k === "favs") renderFavs();
    if (k === "ledger") renderLedger();
  }

  let ready = false;
  function init() {
    if (ready) { showKind(); return; }
    ready = true;
    $("hQual").innerHTML = Object.entries(C.QUALITY_NAMES).map(([q, n]) => opt(q, n)).join("");
    $("moreKind").addEventListener("change", showKind);

    U.setupSearch("fSearch", "fResults", () => true, (it) => addFav(it.id, 1));
    $("fCheck").addEventListener("click", () => checkFavs(false));
    $("fAuto").addEventListener("change", (e) => setAuto(e.target.checked));
    $("fList").addEventListener("click", (e) => {
      const card = e.target.closest(".card"), act = e.target.dataset.act;
      if (!card || !act) return;
      const f = favs[Number(card.dataset.i)];
      if (act === "del") { favs.splice(Number(card.dataset.i), 1); save(FAV_KEY, favs); renderFavs(); }
      if (act === "hist") {
        const [baseId, ench] = f.id.split("@");
        const it = A.getItems().find((i) => i.id === f.id) || A.getItems().find((i) => i.id === baseId);
        if (it) { pickHist(it, it.f ? 0 : Number(ench || 0), f.quality); $("moreKind").value = "hist"; showKind(); runHist(); }
      }
    });
    $("fList").addEventListener("change", (e) => {
      const card = e.target.closest(".card"), act = e.target.dataset.act;
      if (!card || !act) return;
      const f = favs[Number(card.dataset.i)];
      if (act === "kind") f.kind = e.target.value;
      if (act === "target") f.target = num(e.target.value, 0);
      save(FAV_KEY, favs);
      setTimeout(renderFavs, 0);  // tras el evento: redibujar dentro de él choca con la pérdida de foco del campo
    });

    U.setupSearch("hSearch", "hResults", () => true, (it) => pickHist(it, 0));
    $("hRun").addEventListener("click", runHist);
    $("hEnch").addEventListener("change", () => { $("hItem").textContent = `${A.itemName(histId())} (${A.itemLabel(histId())})`; });

    $("more-ledger").addEventListener("input", () => { const d = ledgerDraft();
      $("lPreview").textContent = d ? `Beneficio tras impuestos: ${d.profit > 0 ? "+" : ""}${fmt(d.profit)}` : ""; });
    $("lAdd").addEventListener("click", () => {
      const d = ledgerDraft();
      if (!d) { A.toast("Escribe el precio de compra y el de venta."); return; }
      ledger.unshift(d); save(LEDGER_KEY, ledger);
      $("lName").value = ""; $("lBuy").value = ""; $("lSell").value = ""; $("lQty").value = "1";
      renderLedger(); A.toast("Apuntado.");
    });
    $("lList").addEventListener("click", (e) => {
      if (e.target.dataset.act !== "del") return;
      ledger.splice(Number(e.target.closest(".card").dataset.i), 1); save(LEDGER_KEY, ledger); renderLedger();
    });
    $("lCsv").addEventListener("click", () => (ledger.length ? A.copy(ledgerCsv(), "Registro copiado como CSV.") : A.toast("El registro está vacío.")));
    showKind();
  }

  document.addEventListener("albion-tab", (e) => { if (e.detail === "more") init(); });
  // La estrella de una oportunidad añade el favorito aunque esta pestaña no se haya abierto aún
  document.addEventListener("albion-fav", (e) => addFav(e.detail.id, e.detail.quality));
})();
