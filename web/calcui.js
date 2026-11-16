// Interfaz de las calculadoras (pestaña «Calcular»).
(function () {
  "use strict";
  const A = window.AlbionApp, C = window.AlbionCalc, K = window.AlbionCalculators;
  const $ = (id) => document.getElementById(id);
  const { fmt, esc, norm, num } = A;
  const EQUIP = new Set(["weapons", "armors", "head", "shoes", "offhands", "bags", "capes", "gathering"]);

  let data = null;            // recipes.json
  let kind = "boc";           // boc | craft | refine | trade | upgrade | rank
  let craftItem = null, upItem = null;   // objeto elegido del catálogo
  let matPrices = {}, upPrices = {};     // precios editables

  const matName = (id) => (data && data.names[id]) || A.itemName(id);
  const pct = (x) => (x == null ? "—" : x.toFixed(1).replace(".", ",") + " %");
  const cls = (x) => (x > 0 ? "good" : "bad");
  const price = (id, loc, k, q) => { const e = A.entries.get([id, q || 1, loc, k].join("|")); return e ? e.p : 0; };

  async function loadData() {
    if (data) return;
    let res = await fetch("recipes.json");
    if (!res.ok) res = await fetch("../data/recipes.json");
    data = await res.json();
  }

  // ------------------------------------------------------------ buscador de objetos
  function setupSearch(inputId, resultsId, filter, onPick) {
    $(inputId).addEventListener("input", () => {
      const q = norm($(inputId).value.trim());
      if (q.length < 2) { $(resultsId).innerHTML = ""; return; }
      const found = A.getItems().filter((it) => filter(it) && (norm(it.es).includes(q) || norm(it.en).includes(q) || norm(it.id).includes(q))).slice(0, 8);
      $(resultsId).innerHTML = found.length
        ? found.map((it) => `<button data-id="${esc(it.id)}">${esc(it.es)} <small>${A.itemLabel(it.id)}</small></button>`).join("")
        : '<p class="muted small">Sin resultados.</p>';
    });
    $(resultsId).addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      const it = A.getItems().find((i) => i.id === b.dataset.id);
      $(resultsId).innerHTML = ""; $(inputId).value = "";
      onPick(it);
    });
  }

  async function fetchPrices(ids, locs, quals, statusId) {
    const f = A.readForm();
    $(statusId).textContent = "Buscando precios…";
    try {
      const chunks = C.chunkIds(ids);
      for (let i = 0; i < chunks.length; i++) {
        const chunk = chunks[i];
        if (chunks.length > 1) {
          $(statusId).textContent = `Buscando precios… ${i + 1}/${chunks.length}`;
          if (i) await new Promise((r) => setTimeout(r, 500));  // respeta el límite de la API
        }
        const url = `https://${f.server}.albion-online-data.com/api/v2/stats/prices/${chunk.map(encodeURIComponent).join(",")}.json` +
          `?locations=${encodeURIComponent(locs.join(","))}&qualities=${quals.join(",")}`;
        C.mergePrices(A.entries, await A.getJson(url) || []);
      }
      $(statusId).textContent = "Precios actualizados. Los que falten, escríbelos a mano.";
      return true;
    } catch (e) {
      $(statusId).textContent = "Error: " + e.message + " Puedes escribir los precios a mano.";
      return false;
    }
  }

  // ------------------------------------------------------------ fabricación y refinado
  function craftId() {
    if (!craftItem) return null;
    const e = Number($("cEnch").value);
    return craftItem.f || !e ? craftItem.id : `${craftItem.id}@${e}`;
  }
  const craftRecipe = () => (craftId() && data ? data.recipes[craftId()] : null);

  function updateRrr() {
    $("cRrr").value = (K.returnRate(kind === "refine" ? "refine" : "craft", $("cCity").checked, $("cFocus").checked) * 100).toFixed(1).replace(".", ",");
  }

  function pickCraft(it) {
    craftItem = it; matPrices = {};
    $("cItem").hidden = false;
    $("cEnchWrap").hidden = !!it.f;
    $("cEnch").value = "0";
    $("cFetch").disabled = false;
    $("cSellPrice").value = ""; $("cStatus").textContent = "";
    fillFromStore(); renderCraft();
  }

  function fillFromStore() {
    const r = craftRecipe();
    if (!r) return;
    for (const [id] of r.m) { const p = price(id, $("cBuy").value, "offer"); if (p) matPrices[id] = p; }
    const sell = $("cSell").value, instant = $("cSellMode").value === "instant" || sell === C.BLACK_MARKET;
    const sp = price(craftId(), sell, instant ? "request" : "offer");
    if (sp) $("cSellPrice").value = sp;
  }

  function renderCraft() {
    const r = craftRecipe();
    if (!craftItem) { $("cMats").innerHTML = ""; $("cOut").innerHTML = ""; return; }
    $("cItem").textContent = `${A.itemName(craftId())} (${A.itemLabel(craftId())})`;
    if (!r) {
      $("cMats").innerHTML = ""; $("cOut").innerHTML = '<span class="warn">Este objeto no tiene receta con ese encantamiento.</span>';
      return;
    }
    const f = A.readForm();
    const qty = Math.max(1, Math.floor(num($("cQty").value, 1)));
    const sell = $("cSell").value, instant = $("cSellMode").value === "instant" || sell === C.BLACK_MARKET;
    const out = K.craft(r, data.values, matPrices, num($("cSellPrice").value, 0), {
      rrr: num($("cRrr").value, 0) / 100, fee100: num($("cFee").value, 0), premium: f.premium, sellOrder: !instant, quantity: qty });
    // La tabla de materiales solo se reconstruye si cambia la receta, para no perder el foco al escribir
    const sig = r.m.map((m) => m[0]).join(",");
    if ($("cMats").dataset.sig !== sig) {
      $("cMats").dataset.sig = sig;
      $("cMats").innerHTML = `<table class="mats"><thead><tr><th>Material</th><th>Cant.</th><th>Precio/ud.</th></tr></thead><tbody>` +
        out.materials.map((m) => `<tr><td>${esc(matName(m.id))}${m.returnable ? "" : ' <span class="muted">(no se devuelve)</span>'}</td>
          <td>${fmt(m.count * qty)}</td><td><input data-mat="${esc(m.id)}" type="text" inputmode="numeric"></td></tr>`).join("") + "</tbody></table>";
    }
    $("cMats").querySelectorAll("input").forEach((i) => {
      const v = matPrices[i.dataset.mat];
      if (document.activeElement !== i) i.value = v ? v : "";
      i.classList.toggle("missing", !v);
    });
    const rows = [
      ["Materiales", fmt(out.gross * qty)], ["Devuelto por retorno", "−" + fmt(out.returned * qty)],
      ["Tasa del taller", fmt(out.fee * qty)], ["Coste total", fmt(out.totalCost)],
      [`Coste por unidad (${fmt(out.units)} uds.)`, fmt(out.unitCost)],
    ];
    if (out.unitRevenue != null) rows.push(["Recibes por unidad (tras impuestos)", fmt(out.unitRevenue)], ["Beneficio por unidad", fmt(out.unitProfit)]);
    if (out.focus && $("cFocus").checked) {
      rows.push(["Foco necesario", fmt(out.focus)]);
      if (out.profitPerFocus != null) rows.push(["Beneficio por punto de foco", out.profitPerFocus.toFixed(1).replace(".", ",")]);
    }
    $("cOut").innerHTML =
      (out.missing.length ? '<div class="muted">Completa los precios de los materiales para ver el beneficio.</div>'
        : out.unitProfit != null
        ? `<div class="big ${cls(out.totalProfit)}">${out.totalProfit > 0 ? "+" : ""}${fmt(out.totalProfit)} <small>(${pct(out.percent)})</small></div>`
        : '<div class="muted">Escribe el precio de venta para ver el beneficio.</div>') +
      (out.missing.length ? `<div class="warn">⚠ Faltan precios de ${out.missing.length} material(es): cuentan como 0.</div>` : "") +
      "<dl>" + rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("") + "</dl>";
  }

  // ------------------------------------------------------------ venta manual
  function renderTrade() {
    const buy = num($("tBuy").value, 0), sell = num($("tSell").value, 0);
    if (!buy || !sell) { $("tOut").innerHTML = '<div class="muted">Escribe el precio de compra y el de venta.</div>'; return; }
    const t = K.trade(buy, sell, Math.max(1, Math.floor(num($("tQty").value, 1))), {
      premium: A.readForm().premium, buyOrder: $("tBuyOrder").checked, sellOrder: $("tSellOrder").checked });
    $("tOut").innerHTML = `<div class="big ${cls(t.totalProfit)}">${t.totalProfit > 0 ? "+" : ""}${fmt(t.totalProfit)} <small>(${pct(t.percent)})</small></div><dl>
      <dt>Coste por unidad</dt><dd>${fmt(t.unitCost)}</dd><dt>Recibes por unidad</dt><dd>${fmt(t.unitRevenue)}</dd>
      <dt>Beneficio por unidad</dt><dd>${fmt(t.unitProfit)}</dd><dt>Impuestos y tasas por unidad</dt><dd>${fmt(t.fees)}</dd>
      <dt>Inversión total</dt><dd>${fmt(t.totalCost)}</dd>
      <dt>Precio de venta mínimo para no perder</dt><dd>${fmt(Math.ceil(t.breakeven))}</dd></dl>`;
  }

  // ------------------------------------------------------------ encantar y mejorar
  const upSteps = () => (upItem && data ? data.upgrades[upItem.id] : null);
  const upId = (lvl) => (lvl ? `${upItem.id}@${lvl}` : upItem.id);

  function pickUp(it) {
    upItem = it; upPrices = {};
    $("uItem").hidden = false; $("uFetch").disabled = false;
    $("uBase").value = ""; $("uTarget").value = ""; $("uStatus").textContent = "";
    fillUpFromStore(); renderUp();
  }
  function fillUpFromStore() {
    const steps = upSteps();
    if (!steps) return;
    const city = $("uCity").value, q = Number($("uQual").value);
    for (const [id] of steps) { const p = price(id, city, "offer"); if (p) upPrices[id] = p; }
    const b = price(upId(Number($("uFrom").value)), city, "offer", q), t = price(upId(Number($("uTo").value)), city, "offer", q);
    if (b) $("uBase").value = b;
    if (t) $("uTarget").value = t;
  }
  function renderUp() {
    if (!upItem) { $("uMats").innerHTML = ""; $("uOut").innerHTML = ""; return; }
    const from = Number($("uFrom").value), to = Number($("uTo").value), steps = upSteps();
    $("uItem").textContent = `${upItem.es} (T${upItem.t}) · de .${from} a .${to}`;
    if (!steps || to <= from) {
      $("uMats").innerHTML = ""; $("uMats").dataset.sig = "";
      $("uOut").innerHTML = `<span class="warn">${steps ? "«Hasta» debe ser mayor que «Desde»." : "Este objeto no se puede mejorar."}</span>`;
      return;
    }
    const u = K.upgrade(steps, from, to, num($("uBase").value, 0), upPrices, num($("uTarget").value, 0));
    if (!u) { $("uMats").innerHTML = ""; $("uOut").innerHTML = '<span class="warn">Este objeto no se puede mejorar a ese nivel.</span>'; return; }
    const sig = u.steps.map((s) => s.id).join(",");
    if ($("uMats").dataset.sig !== sig) {
      $("uMats").dataset.sig = sig;
      $("uMats").innerHTML = `<table class="mats"><thead><tr><th>Recurso</th><th>Cant.</th><th>Precio/ud.</th></tr></thead><tbody>` +
        u.steps.map((s) => `<tr><td>${esc(matName(s.id))} <span class="muted">(a .${s.level})</span></td><td>${fmt(s.count)}</td>
          <td><input data-mat="${esc(s.id)}" type="text" inputmode="numeric"></td></tr>`).join("") + "</tbody></table>";
    }
    $("uMats").querySelectorAll("input").forEach((i) => {
      const v = upPrices[i.dataset.mat];
      if (document.activeElement !== i) i.value = v ? v : "";
      i.classList.toggle("missing", !v);
    });
    let head = '<div class="muted">Escribe los precios para comparar.</div>';
    if (u.saving != null && !u.missing.length) {
      head = u.saving > 0
        ? `<div class="big good">Mejorar ahorra ${fmt(u.saving)}</div>`
        : `<div class="big bad">Sale más barato comprarlo hecho (${fmt(-u.saving)} menos)</div>`;
    }
    $("uOut").innerHTML = head +
      (u.missing.length ? '<div class="warn">⚠ Faltan precios: el total está incompleto.</div>' : "") +
      `<dl><dt>Coste de los recursos</dt><dd>${fmt(u.upgradeCost)}</dd><dt>Objeto sin mejorar + recursos</dt><dd>${fmt(u.total)}</dd>
       <dt>Comprarlo ya mejorado</dt><dd>${u.direct ? fmt(u.direct) : "—"}</dd></dl>`;
  }

  // ------------------------------------------------------------ comprar o fabricar
  let bocItem = null, bocReady = false;
  const bocStats = new Map();   // "item|calidad|ciudad" -> { daily, avg } (ventas diarias, del historial)
  const bocId = () => (bocItem ? (bocItem.f || !Number($("bEnch").value) ? bocItem.id : `${bocItem.id}@${$("bEnch").value}`) : null);

  function pickBoc(it) {
    bocItem = it; bocReady = false;
    $("bItem").hidden = false; $("bEnchWrap").hidden = !!it.f; $("bEnch").value = "0";
    $("bFetch").disabled = false; $("bStatus").textContent = "";
    renderBoc();
  }

  async function runBoc() {
    const id = bocId(), r = data.recipes[id];
    if (!r) { renderBoc(); return; }
    const f = A.readForm(), city = $("bCity").value, q = Number($("bQual").value);
    const ids = [id, ...r.m.map((m) => m[0])], quals = [...new Set([1, q])];
    $("bFetch").disabled = true;
    const ok = await fetchPrices(ids, [city], quals, "bStatus");
    if (ok) {
      $("bStatus").textContent = "Buscando cuánto se vende al día…";
      try {
        C.mergeHistory(bocStats, await A.getJson(`https://${f.server}.albion-online-data.com/api/v2/stats/history/` +
          `${ids.map(encodeURIComponent).join(",")}.json?locations=${encodeURIComponent(city)}&qualities=${quals.join(",")}&time-scale=24`) || []);
        $("bStatus").textContent = "";
      } catch (e) { $("bStatus").textContent = "No se pudo descargar el historial de ventas: la subida de precio no se estima."; }
      bocReady = true;
    }
    $("bFetch").disabled = false;
    renderBoc();
  }

  function renderBoc() {
    $("bMats").innerHTML = "";
    if (!bocItem) { $("bOut").innerHTML = ""; return; }
    const id = bocId(), r = data.recipes[id];
    $("bItem").textContent = `${A.itemName(id)} (${A.itemLabel(id)})`;
    if (!r) { $("bOut").innerHTML = '<span class="warn">Este objeto no se puede fabricar con ese encantamiento.</span>'; return; }
    if (!bocReady) { $("bOut").innerHTML = '<div class="muted">Pulsa «Buscar precios y comparar».</div>'; return; }
    const city = $("bCity").value, q = Number($("bQual").value), n = Math.max(1, Math.floor(num($("bQty").value, 1)));
    const slip = Math.max(0, num($("bSlip").value, 30)) / 100;
    const daily = (item, ql) => { const s = bocStats.get([item, ql, city].join("|")); return s ? s.daily : null; };
    const quoteItem = (k) => K.buyCost(k, price(id, city, "offer", q), null, daily(id, q), slip);
    const quoteMat = (m, k) => K.buyCost(k, price(m, city, "offer"), null, daily(m, 1), slip);
    const rrr = K.returnRate(bocItem.c === "resources" ? "refine" : "craft", $("bCityBonus").checked, false);
    const res = K.buyOrCraft(r, data.values, n, quoteItem, quoteMat, { rrr, fee100: num($("bFee").value, 0) });
    const c = res.craft, b = res.buy, best = price(id, city, "offer", q);
    let head;
    if (c.missing.length) head = `<div class="warn">⚠ La API no tiene precio en ${esc(city)} de: ${c.missing.map((m) => esc(matName(m))).join(", ")}. No se puede comparar.</div>`;
    else if (!b) head = `<div class="warn">⚠ La API no tiene precio de venta de este objeto en ${esc(city)}. Fabricarlo costaría ${fmt(c.unitCost)} por unidad.</div>`;
    else head = `<div class="big good">${res.verdict === "craft" ? "Mejor fabricarlo" : "Mejor comprarlo"}</div>
      <div>Ahorras ${fmt(res.saving)} en ${fmt(n)} ud${n > 1 ? "s." : "."} (${fmt(Math.abs(b.avg - c.unitCost))} por unidad).</div>`;
    const rows = [];
    if (b) rows.push(["Comprar: orden más barata ahora", fmt(best)], [`Comprar: precio medio de ${fmt(n)} uds.`, fmt(b.avg)], ["Comprar: total", fmt(b.total)]);
    if (!c.missing.length) rows.push(["Fabricar: materiales", fmt(c.materialsTotal)], ["Fabricar: tasa del taller", fmt(c.fee)],
      [`Fabricar: total (${fmt(c.units)} uds.)`, fmt(c.total)], ["Fabricar: por unidad", fmt(c.unitCost)]);
    const notes = [];
    if (res.switchAt) notes.push(`A partir de unas ${fmt(res.switchAt)} unidades sale mejor ${res.verdict === "buy" ? "fabricar" : "comprar"}.`);
    else if (res.verdict) notes.push(`${res.verdict === "buy" ? "Comprar" : "Fabricar"} sigue saliendo mejor aunque quieras muchas más.`);
    if (res.verdict && ((b && b.noVolume) || c.noVolume)) notes.push("⚠ De algún objeto no hay datos de ventas diarias: ahí no se ha podido estimar la subida de precio.");
    notes.push(`Retorno de recursos usado: ${pct(rrr * 100)} (sin foco). La subida de precio es una estimación: confírmala en el juego si vas a comprar muchas.`);
    if (!bocItem.f) notes.push("Al fabricar, la calidad sale al azar; se compara con comprarlo en la calidad elegida.");
    $("bOut").innerHTML = head + "<dl>" + rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("") + "</dl>" +
      notes.map((t) => `<p class="muted small">${esc(t)}</p>`).join("");
    if (!c.missing.length) {
      $("bMats").innerHTML = `<table class="mats"><thead><tr><th>Material</th><th>A comprar</th><th>Precio medio</th></tr></thead><tbody>` +
        c.materials.map((m) => `<tr><td>${esc(matName(m.id))}</td><td>${fmt(m.buy)}</td><td>${fmt(m.avg)}</td></tr>`).join("") + "</tbody></table>";
    }
  }

  // ------------------------------------------------------------ ranking de fabricación
  let rankIds = null;
  const RANK_CATS = { equip: [...EQUIP], consumables: ["consumables"], refine: ["resources"] };

  async function runRank() {
    const f = A.readForm();
    const ids = A.variantIds(f, RANK_CATS[$("rType").value]).filter((id) => data.recipes[id]);
    if (!ids.length) { $("rStatus").textContent = "No hay recetas con los tiers y encantamientos marcados en Ajustes."; return; }
    const mats = new Set();
    for (const id of ids) for (const m of data.recipes[id].m) mats.add(m[0]);
    $("rRun").disabled = true;
    const ok = await fetchPrices(ids, [$("rSell").value], [1], "rStatus") &&
               await fetchPrices([...mats], [$("rBuy").value], [1], "rStatus");
    $("rRun").disabled = false;
    if (ok) { rankIds = ids; renderRank(); }
  }

  function renderRank() {
    if (!rankIds) return;
    const f = A.readForm(), buy = $("rBuy").value, sell = $("rSell").value;
    const instant = $("rSellMode").value === "instant" || sell === C.BLACK_MARKET;
    const refine = $("rType").value === "refine", focus = $("rFocus").checked;
    const opts = { rrr: K.returnRate(refine ? "refine" : "craft", $("rCity").checked, focus), fee100: num($("rFee").value, 0),
      premium: f.premium, sellOrder: !instant };
    const rows = [];
    for (const id of rankIds) {
      const r = data.recipes[id], prices = {};
      for (const [m] of r.m) prices[m] = price(m, buy, "offer");
      const sp = price(id, sell, instant ? "request" : "offer");
      if (!sp) continue;
      const c = K.craft(r, data.values, prices, sp, opts);
      if (!c.missing.length) rows.push({ id, c, sp });
    }
    const key = $("rSort").value;
    rows.sort((a, b) => (b.c[key] ?? -Infinity) - (a.c[key] ?? -Infinity));
    $("rStatus").textContent = `${fmt(rows.length)} de ${fmt(rankIds.length)} recetas tienen todos los precios. ` +
      "Comprueba en el juego que el objeto se vende antes de fabricar mucho.";
    $("rList").innerHTML = rows.length ? rows.slice(0, 60).map(({ id, c, sp }) => `<article class="card">
      <div class="top"><div><div class="name">${esc(A.itemName(id))}</div><div class="sub">${A.itemLabel(id)}${c.unitsPerCraft > 1 ? ` · ${c.unitsPerCraft} uds. por fabricación` : ""}</div></div>
        <div class="pct ${cls(c.unitProfit)}">${pct(c.percent)}<div class="sub">${c.unitProfit > 0 ? "+" : ""}${fmt(c.unitProfit)}/ud.</div></div></div>
      <dl><div><dt>Coste/ud.</dt><dd>${fmt(c.unitCost)}</dd></div><div><dt>Venta</dt><dd>${fmt(sp)}</dd></div>
        <div><dt>${focus ? "Benef./foco" : "Foco"}</dt><dd>${focus && c.profitPerFocus != null ? c.profitPerFocus.toFixed(1).replace(".", ",") : fmt(c.focus)}</dd></div></dl>
      </article>`).join("") : '<div class="empty">Ninguna receta tiene todos los precios en esas ciudades.</div>';
  }

  // ------------------------------------------------------------ arranque
  function showKind() {
    kind = $("calcKind").value;
    $("calc-boc").hidden = kind !== "boc";
    $("calc-craft").hidden = !(kind === "craft" || kind === "refine");
    $("calc-trade").hidden = kind !== "trade";
    $("calc-upgrade").hidden = kind !== "upgrade";
    $("calc-rank").hidden = kind !== "rank";
    if (kind === "craft" || kind === "refine") {
      $("cSearchLabel").textContent = kind === "refine" ? "Recurso a refinar" : "Objeto a fabricar";
      craftItem = null; matPrices = {};
      $("cItem").hidden = true; $("cFetch").disabled = true; $("cStatus").textContent = ""; $("cSellPrice").value = ""; $("cMats").dataset.sig = ""; $("cEnchWrap").hidden = kind === "refine";
      updateRrr(); renderCraft();
    }
    if (kind === "boc") renderBoc();
    if (kind === "trade") renderTrade();
    if (kind === "upgrade") renderUp();
  }

  let ready = false;
  async function init() {
    if (ready) return;
    ready = true;
    const opt = (v, l) => `<option value="${esc(v)}">${esc(l)}</option>`;
    const cities = C.CITIES.map((c) => opt(c, c)).join("");
    $("cBuy").innerHTML = cities; $("uCity").innerHTML = cities; $("rBuy").innerHTML = cities; $("bCity").innerHTML = cities;
    $("bCity").value = "Lymhurst";
    $("cSell").innerHTML = cities + opt(C.BLACK_MARKET, "Mercado Negro"); $("rSell").innerHTML = $("cSell").innerHTML;
    $("rBuy").value = "Lymhurst"; $("rSell").value = "Lymhurst";
    $("uQual").innerHTML = Object.entries(C.QUALITY_NAMES).map(([q, n]) => opt(q, n)).join("");
    $("cBuy").value = "Lymhurst"; $("cSell").value = "Lymhurst"; $("uCity").value = "Lymhurst"; $("uTo").value = "1";
    try { await loadData(); } catch (e) { $("cStatus").textContent = "No se pudieron cargar las recetas. Recarga la página."; return; }

    setupSearch("cSearch", "cResults",
      (it) => (kind === "refine" ? it.c === "resources" : EQUIP.has(it.c) || it.c === "consumables") &&
        (data.recipes[it.id] !== undefined), pickCraft);
    setupSearch("uSearch", "uResults", (it) => EQUIP.has(it.c) && data.upgrades[it.id] !== undefined, pickUp);

    $("calcKind").addEventListener("change", showKind);
    $("calc-craft").addEventListener("input", (e) => {
      if (e.target.dataset.mat) matPrices[e.target.dataset.mat] = num(e.target.value, 0);
      if (e.target.id !== "cSearch") renderCraft();
    });
    $("calc-craft").addEventListener("change", (e) => {
      if (["cCity", "cFocus"].includes(e.target.id)) updateRrr();
      if (["cEnch", "cBuy", "cSell", "cSellMode"].includes(e.target.id)) {
        if (e.target.id !== "cSell" && e.target.id !== "cSellMode") matPrices = {};
        $("cSellPrice").value = ""; fillFromStore();
      }
      renderCraft();
    });
    $("cFetch").addEventListener("click", async () => {
      const r = craftRecipe();
      if (!r) return;
      const locs = [...new Set([$("cBuy").value, $("cSell").value])];
      await fetchPrices([craftId(), ...r.m.map((m) => m[0])], locs, [1], "cStatus");
      fillFromStore(); renderCraft();
    });
    $("calc-trade").addEventListener("input", renderTrade);
    $("calc-upgrade").addEventListener("input", (e) => {
      if (e.target.dataset.mat) upPrices[e.target.dataset.mat] = num(e.target.value, 0);
      if (e.target.id !== "uSearch") renderUp();
    });
    $("calc-upgrade").addEventListener("change", (e) => {
      if (["uFrom", "uTo", "uQual", "uCity"].includes(e.target.id)) {
        if (e.target.id === "uCity") upPrices = {};
        $("uBase").value = ""; $("uTarget").value = ""; fillUpFromStore();
      }
      renderUp();
    });
    $("uFetch").addEventListener("click", async () => {
      const steps = upSteps();
      if (!steps) return;
      const from = Number($("uFrom").value), to = Number($("uTo").value);
      await fetchPrices([upId(from), upId(to), ...steps.slice(from, to).map((s) => s[0])], [$("uCity").value],
        [...new Set([1, Number($("uQual").value)])], "uStatus");
      fillUpFromStore(); renderUp();
    });
    $("bQual").innerHTML = $("uQual").innerHTML;
    setupSearch("bSearch", "bResults", (it) => data.recipes[it.id] !== undefined, pickBoc);
    $("bFetch").addEventListener("click", runBoc);
    $("calc-boc").addEventListener("input", (e) => { if (["bQty", "bFee", "bSlip"].includes(e.target.id)) renderBoc(); });
    $("calc-boc").addEventListener("change", (e) => {
      if (["bEnch", "bQual", "bCity"].includes(e.target.id)) bocReady = false;  // hacen falta otros precios
      renderBoc();
    });
    $("rRun").addEventListener("click", runRank);
    $("calc-rank").addEventListener("change", (e) => {
      if (["rType", "rBuy", "rSell"].includes(e.target.id)) { rankIds = null; $("rList").innerHTML = ""; $("rStatus").textContent = ""; }
      else renderRank();
    });
    $("calc-rank").addEventListener("input", (e) => { if (e.target.id === "rFee") renderRank(); });
    showKind();
  }

  window.AlbionCalcUI = { setupSearch, fetchPrices };  // lo reutiliza la pestaña «Más»
  document.addEventListener("albion-tab", (e) => { if (e.detail === "calc") init(); });
})();
