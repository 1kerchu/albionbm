(function () {
  "use strict";
  const C = window.AlbionCalc;
  const $ = (id) => document.getElementById(id);
  const fmt = (n) => (n == null ? "—" : Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, "."));
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const norm = (s) => (s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
  const num = (s, d) => { const v = parseFloat(String(s || "").replace(/\./g, "").replace(",", ".")); return Number.isFinite(v) ? v : d; };
  const ago = (h) => (h < 1 ? `${Math.max(1, Math.round(h * 60))} min` : h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} d`);

  const CATEGORY_NAMES = {
    weapons: "Armas", armors: "Armaduras", head: "Cascos", shoes: "Botas", offhands: "Secundarias", bags: "Bolsas",
    capes: "Capas", gathering: "Recolección", resources: "Recursos", consumables: "Consumibles", mounts: "Monturas",
    artefacts: "Artefactos",
  };
  const NOT_BM = new Set(["resources", "consumables", "mounts", "artefacts"]);
  const CITY_LABEL = (c) => (c === C.BLACK_MARKET ? "Mercado Negro" : c);
  const DEFAULTS = {
    server: "europe", strategy: "bm", premium: true, buyOrder: false, bestOnly: true, hideSusp: true,
    minPct: "10", minSilver: "5000", maxCost: "", maxAge: "6", capital: "", weight: "", profile: "balanced",
    cats: ["weapons", "armors", "head", "shoes", "offhands", "bags", "capes"],
    tiers: [4, 5, 6], enchs: [0, 1], quals: [1, 2, 3], cities: C.CITIES.filter((c) => c !== "Brecilien"), sort: "percent",
  };
  const STORE_KEY = "albionbm.web.v1";
  const PAUSE_MS = 600, MAX_CARDS = 150, MAX_HISTORY_ITEMS = 1000;

  let items = [], byId = new Map();
  const entries = new Map(), stats = new Map();
  let opps = [], running = false, stopFlag = false, lastUpdate = null;

  // ---------------------------------------------------------------- catálogo
  const base = (id) => byId.get(id) || byId.get(id.split("@")[0]) || null;
  const itemName = (id) => (base(id) || {}).es || id;
  const itemLabel = (id) => `T${(base(id) || {}).t || "?"}.${id.includes("@") ? id.split("@")[1] : 0}`;
  const itemWeight = (id) => (base(id) || {}).w || 0;
  function matches(id, f, q) {
    const b = base(id);
    if (!b) return false;
    const ench = id.includes("@") ? Number(id.split("@")[1]) : 0;
    if (!f.cats.includes(b.c) || !f.tiers.includes(b.t) || !f.enchs.includes(ench)) return false;
    return !q || norm(b.es).includes(q) || norm(b.en).includes(q) || norm(b.id).includes(q);
  }
  function variantIds(f, cats) {
    const out = [];
    for (const it of items) {
      if (!cats.includes(it.c) || !f.tiers.includes(it.t)) continue;
      for (const e of it.e) if (f.enchs.includes(e)) out.push(it.f || !e ? it.id : `${it.id}@${e}`);
    }
    return out;
  }

  // ---------------------------------------------------------------- ajustes
  function chips(id, values, label, checked) {
    $(id).innerHTML = values.map((v) =>
      `<label><input type="checkbox" value="${v}" ${checked.includes(v) ? "checked" : ""}>${esc(label(v))}</label>`).join("");
  }
  const checkedVals = (id, numeric) => [...$(id).querySelectorAll("input:checked")].map((i) => (numeric ? Number(i.value) : i.value));
  const TEXT = ["minPct", "minSilver", "maxCost", "maxAge", "capital", "weight"];
  const BOOL = ["premium", "buyOrder", "bestOnly", "hideSusp"];
  const SELECT = ["server", "strategy", "profile", "sort"];

  function loadSettings() {
    try { return Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem(STORE_KEY)) || {}); } catch { return Object.assign({}, DEFAULTS); }
  }
  function readForm() {
    const f = { cats: checkedVals("cats"), tiers: checkedVals("tiers", true), enchs: checkedVals("enchs", true),
      quals: checkedVals("quals", true), cities: checkedVals("cities") };
    for (const k of TEXT) f[k] = $(k).value.trim();
    for (const k of BOOL) f[k] = $(k).checked;
    for (const k of SELECT) f[k] = $(k).value;
    return f;
  }
  function saveSettings() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(readForm())); } catch { /* sin almacenamiento */ }
  }
  function initForm() {
    const s = loadSettings();
    $("strategy").innerHTML = Object.entries(C.STRATEGIES).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("");
    $("profile").innerHTML = Object.entries(C.PROFILES).map(([k, p]) => `<option value="${k}">${esc(p.name)}</option>`).join("");
    chips("cats", Object.keys(CATEGORY_NAMES), (c) => CATEGORY_NAMES[c], s.cats);
    chips("tiers", [4, 5, 6, 7, 8], (t) => "T" + t, s.tiers);
    chips("enchs", [0, 1, 2, 3, 4], (e) => "." + e, s.enchs);
    chips("quals", [1, 2, 3, 4, 5], (q) => C.QUALITY_NAMES[q], s.quals);
    chips("cities", C.CITIES, (c) => c, s.cities);
    for (const k of TEXT) $(k).value = s[k] ?? "";
    for (const k of BOOL) $(k).checked = !!s[k];
    for (const k of SELECT) if (s[k]) $(k).value = s[k];
  }

  // ---------------------------------------------------------------- cálculo y render
  function computeOpps(f, thresholds) {
    const q = thresholds ? norm($("search").value.trim()) : "";
    const filtered = new Map();
    for (const [k, v] of entries) if (matches(k.slice(0, k.indexOf("|")), f, q)) filtered.set(k, v);
    let list = C.compute(filtered, stats, {
      cities: f.cities, qualities: f.quals, premium: f.premium, buyMode: f.buyOrder ? "order" : "instant",
      strategy: f.strategy, maxAgeH: num(f.maxAge, 24),
    });
    if (!thresholds) return list;
    const minPct = num(f.minPct, -Infinity), minSilver = num(f.minSilver, -Infinity), maxCost = num(f.maxCost, Infinity);
    list = list.filter((o) => o.percent >= minPct && o.profit >= minSilver && o.buyPrice <= maxCost && !(f.hideSusp && o.suspicious));
    return f.bestOnly ? C.bestPerItem(list) : list;
  }

  function refresh() {
    const f = readForm();
    opps = computeOpps(f, true);
    const bm = f.strategy === "bm";
    const n = variantIds(f, f.cats.filter((c) => !(bm && NOT_BM.has(c)))).length;
    $("count").textContent = `${fmt(n)} objetos a consultar con estos filtros.`;
    $("summary").textContent = entries.size
      ? `${C.STRATEGIES[f.strategy]} · ${fmt(opps.length)} oportunidades` + (lastUpdate ? ` · actualizado ${lastUpdate}` : "")
      : "Pulsa «Actualizar precios» para empezar.";
    renderList(f);
    renderPlan(f);
  }

  function renderList(f) {
    const sort = f.sort;
    const val = (o) => (sort === "age" ? -Math.max(o.buyAgeH, o.sellAgeH) : o[sort] == null ? -Infinity : o[sort]);
    const rows = opps.slice().sort((a, b) => val(b) - val(a));
    if (!rows.length) {
      $("list").innerHTML = `<div class="empty">${entries.size
        ? "Sin oportunidades con estos filtros. Prueba a bajar el beneficio mínimo o a subir «Datos máx.» en Ajustes."
        : "Todavía no hay precios. Pulsa «Actualizar precios»."}</div>`;
      return;
    }
    $("list").innerHTML = rows.slice(0, MAX_CARDS).map((o) => {
      const q = C.QUALITY_NAMES[o.quality] + (o.sellQuality !== o.quality ? ` (orden ${C.QUALITY_NAMES[o.sellQuality]})` : "");
      return `<article class="card${o.suspicious ? " susp" : ""}" data-id="${esc(o.itemId)}">
        <div class="top">
          <img loading="lazy" alt="" onerror="this.style.visibility='hidden'"
               src="https://render.albiononline.com/v1/item/${encodeURIComponent(o.itemId)}.png?quality=${o.quality}&size=96">
          <div><div class="name">${esc(itemName(o.itemId))}</div><div class="sub">${itemLabel(o.itemId)} · ${esc(q)}</div></div>
          <div class="pct ${o.profit > 0 ? "good" : "bad"}">${o.percent.toFixed(1)} %<div class="sub">+${fmt(o.profit)}/ud.</div></div>
          <button class="star" data-fav="${esc(o.itemId)}" data-q="${o.quality}" aria-label="Añadir a favoritos">☆</button>
        </div>
        <div class="route">${esc(o.city)} → <strong>${esc(CITY_LABEL(o.sellCity))}</strong></div>
        <dl>
          <div><dt>Compra</dt><dd>${fmt(o.buyPrice)}</dd></div>
          <div><dt>Venta</dt><dd>${fmt(o.sellPrice)}</dd></div>
          <div><dt>Media 7 d</dt><dd>${fmt(o.avgPrice)}</dd></div>
          <div><dt>Uds. (est.)</dt><dd>${o.units == null ? "—" : "~" + fmt(o.units)}</dd></div>
          <div><dt>Benef. total</dt><dd>${fmt(o.totalProfit)}</dd></div>
          <div><dt>Datos</dt><dd>${ago(Math.max(o.buyAgeH, o.sellAgeH))}</dd></div>
        </dl>
        ${o.suspicious ? '<div class="warn">⚠ Precio de venta muy por encima de la media: probablemente dato viejo o trampa.</div>' : ""}
      </article>`;
    }).join("") + (rows.length > MAX_CARDS ? `<div class="empty">Mostrando ${MAX_CARDS} de ${fmt(rows.length)}.</div>` : "");
  }

  function planOpts(f) {
    return { profile: f.profile, maxWeight: num(f.weight, 0) || null, weightOf: itemWeight };
  }

  function renderPlan(f) {
    const p = C.PROFILES[f.profile];
    $("profileDesc").textContent = p.description + " Nunca incluye precios sospechosos.";
    const capital = num(f.capital, 0);
    if (capital <= 0) { $("routes").innerHTML = '<div class="empty">Escribe tu capital para ver el plan.</div>'; return; }
    const all = C.plan(opps, capital, planOpts(f));
    const routes = C.planRoutes(opps, capital, planOpts(f));
    const blocks = [];
    if (all.lines.length) blocks.push({ title: "Todas las rutas mezcladas", lines: all.lines });
    for (const r of routes) blocks.push({ title: `${r.buyCity} → ${CITY_LABEL(r.sellCity)}`, lines: r.lines });
    if (!blocks.length) {
      $("routes").innerHTML = `<div class="empty">${entries.size
        ? "No hay oportunidades válidas para este perfil. Actualiza precios, afloja los filtros o elige un perfil menos estricto."
        : "Pulsa «Actualizar precios» primero."}</div>`;
      return;
    }
    $("routes").innerHTML = blocks.map((b, i) => {
      const inv = b.lines.reduce((s, l) => s + l.invest, 0), prof = b.lines.reduce((s, l) => s + l.profit, 0);
      const w = b.lines.reduce((s, l) => s + l.weight, 0);
      return `<details class="card"${i === 0 ? " open" : ""}>
        <summary><div class="rname">${esc(b.title)}</div>
          <div class="sub">${b.lines.length} objetos · inversión ${fmt(inv)} · ${fmt(w)} kg</div>
          <div class="good"><strong>+${fmt(prof)}</strong> (${(prof / inv * 100).toFixed(1)} %)</div></summary>
        <table><thead><tr><th>Objeto</th><th>Uds.</th><th>Precio</th><th>Benef.</th></tr></thead><tbody>
        ${b.lines.map((l) => `<tr><td>${esc(itemName(l.opp.itemId))} <span class="muted">${itemLabel(l.opp.itemId)} · ${C.QUALITY_NAMES[l.opp.quality]}
          · ${esc(l.opp.city)} → ${esc(CITY_LABEL(l.opp.sellCity))}</span></td>
          <td>~${fmt(l.units)}</td><td>${fmt(l.opp.buyPrice)}</td><td>${fmt(l.profit)}</td></tr>`).join("")}
        </tbody></table></details>`;
    }).join("");
  }

  // ---------------------------------------------------------------- API
  async function getJson(url) {
    for (let attempt = 0; attempt < 5; attempt++) {
      let res;
      try { res = await fetch(url); } catch (e) {
        if (attempt === 4) throw new Error("No se pudo conectar con la API. Revisa tu conexión.");
        await sleep(3000); continue;
      }
      if (res.ok) return res.json();
      if (res.status === 429 || res.status >= 500) { await sleep(5000 * (attempt + 1)); continue; }
      throw new Error(`La API respondió con un error (${res.status}).`);
    }
    throw new Error("La API no responde (límite de peticiones). Inténtalo en unos minutos.");
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const setProgress = (p) => { $("progress").firstElementChild.style.width = (p * 100).toFixed(1) + "%"; };
  const setStatus = (t) => { $("status").textContent = t; };

  async function fetchChunks(ids, maxChars, buildUrl, onRows, from, to) {
    const chunks = C.chunkIds(ids, maxChars);
    for (let i = 0; i < chunks.length && !stopFlag; i++) {
      onRows(await getJson(buildUrl(chunks[i].map(encodeURIComponent).join(","))) || []);
      setProgress(from + ((i + 1) / chunks.length) * (to - from));
      await sleep(PAUSE_MS);
    }
  }

  async function update() {
    if (running) return;
    const f = readForm();
    const bm = f.strategy === "bm";
    const ids = variantIds(f, f.cats.filter((c) => !(bm && NOT_BM.has(c))));
    if (!ids.length || !f.cities.length || !f.quals.length) {
      setStatus("No hay objetos, ciudades o calidades seleccionadas." +
        (bm ? " El Mercado Negro solo compra equipo: para recursos y demás elige una estrategia «Entre ciudades»." : ""));
      return;
    }
    if (ids.length > 4000 && !confirm(`Vas a consultar ${fmt(ids.length)} objetos; tardará varios minutos. ¿Continuar?`)) return;
    saveSettings();
    running = true; stopFlag = false;
    $("refresh").disabled = true; $("stop").hidden = false; $("progress").hidden = false; setProgress(0);
    const host = `https://${f.server}.albion-online-data.com/api/v2/stats`;
    const quals = Array.from({ length: Math.max(...f.quals) }, (_, i) => i + 1).join(",");
    const sellLocs = bm ? [C.BLACK_MARKET] : f.cities;
    const locs = f.cities.concat(bm ? [C.BLACK_MARKET] : []);
    try {
      setStatus(`Descargando precios de ${fmt(ids.length)} objetos en ${locs.length} mercados…`);
      let got = 0;
      await fetchChunks(ids, 1800,
        (p) => `${host}/prices/${p}.json?locations=${encodeURIComponent(locs.join(","))}&qualities=${quals}`,
        (rows) => { got += C.mergePrices(entries, rows); }, 0, 0.6);
      refresh();

      // Historial (ventas/día y precio medio) solo de lo que da beneficio
      const idSet = new Set(ids), best = new Map();
      for (const o of computeOpps(f, false)) {
        if (o.profit > 0 && idSet.has(o.itemId)) best.set(o.itemId, Math.max(best.get(o.itemId) || 0, o.profit));
      }
      const histIds = [...best.keys()].sort((a, b) => best.get(b) - best.get(a)).slice(0, MAX_HISTORY_ITEMS);
      if (histIds.length && !stopFlag) {
        setStatus(`Descargando historial de ventas de ${fmt(histIds.length)} objetos…`);
        await fetchChunks(histIds, Math.max(300, Math.floor(1800 / sellLocs.length)),
          (p) => `${host}/history/${p}.json?locations=${encodeURIComponent(sellLocs.join(","))}&qualities=${quals}&time-scale=24`,
          (rows) => { C.mergeHistory(stats, rows); }, 0.6, 1);
      }
      lastUpdate = new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
      setStatus(stopFlag ? "Actualización detenida." : `Actualización terminada: ${fmt(got)} precios.`);
    } catch (e) {
      setStatus("Error: " + e.message);
    } finally {
      running = false;
      $("refresh").disabled = false; $("stop").hidden = true; $("progress").hidden = true;
      refresh();
    }
  }

  // ---------------------------------------------------------------- informe para Claude
  function buildReport(f) {
    const capital = num(f.capital, 0), weight = num(f.weight, 0) || null, p = C.PROFILES[f.profile];
    const tax = f.premium ? C.TAX_PREMIUM : C.TAX_NO_PREMIUM;
    const L = [];
    L.push("# Informe de oportunidades de comercio · Albion Online", "",
      `Generado por AlbionBM web el ${new Date().toLocaleString("es-ES")}.`, "",
      "## Instrucciones para el asistente", "",
      `Soy jugador de Albion Online. Abajo tienes oportunidades de comprar objetos en una ciudad y venderlos en otro mercado. Estrategia: **${C.STRATEGIES[f.strategy]}**. Ayúdame a decidir en qué invertir mi capital para ganar lo máximo con un riesgo razonable. Ten en cuenta:`, "",
      "- **Cantidades:** «Uds.» es una estimación: lo que se vende en el destino en un día de media («Vol./día», últimos 7 días) valorado al mejor precio. La cantidad real en las órdenes es desconocida y el precio empeora al comprar más. «—» = sin datos.",
      "- **Sospechosos:** las filas con ⚠ venden a más de 1,6 veces la media de 7 días; casi siempre es un dato viejo o una orden trampa.",
      "- **Frescura:** «Datos» es la antigüedad del precio más viejo de los dos. Todos los precios vienen de una API alimentada por jugadores.",
      "- **Transporte:** vender en Caerleon o en el Mercado Negro obliga a cruzar zona roja. «Peso» es por unidad.", "",
      "Dame un plan concreto: qué comprar, cuántas unidades, dónde comprar y dónde vender, cuánto capital queda libre y los riesgos principales.", "",
      "## Contexto", "",
      `- **Capital disponible:** ${capital ? fmt(capital) + " de plata" : "(indícalo en tu mensaje)"}`,
      `- **Capacidad de carga por viaje:** ${weight ? weight + " kg" : "sin indicar"}`,
      `- **Perfil de riesgo:** ${p.name} — ${p.description}`,
      `- **Servidor:** ${f.server} · **Prémium:** ${f.premium ? "sí" : "no"} (impuesto ${tax * 100} %) · **Compra:** ${f.buyOrder ? "con orden de compra (+2,5 %)" : "directa"}`,
      `- **Filtros:** tiers ${f.tiers.join(", ")}; encantamientos ${f.enchs.join(", ")}; ciudades ${f.cities.join(", ")}; beneficio mín. ${f.minPct || "—"} % y ${f.minSilver || "—"} de plata; datos de hasta ${f.maxAge || 24} h`,
      `- **Oportunidades encontradas:** ${fmt(opps.length)}`, "");
    if (capital) {
      const routes = C.planRoutes(opps, capital, planOpts(f));
      if (routes.length) {
        L.push("## Mejores rutas para un solo viaje", "", "| Ruta | Objetos | Inversión | Benef. estimado | % | Peso (kg) |", "|---|--:|--:|--:|--:|--:|");
        for (const r of routes) L.push(`| ${r.buyCity} → ${r.sellCity} | ${r.lines.length} | ${fmt(r.invest)} | ${fmt(r.profit)} | ${(r.profit / r.invest * 100).toFixed(1)} % | ${fmt(r.weight)} |`);
        L.push("");
      }
    }
    const rows = opps.slice().sort((a, b) => b.percent - a.percent).slice(0, 120);
    L.push("## Oportunidades", "",
      "| # | Objeto | ID | Calidad | Comprar en | Vender en | Precio compra | Precio venta | Media 7d | Benef./ud. | % | Uds. | Benef. total | Vol./día | Peso | Datos |",
      "|--:|---|---|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|");
    rows.forEach((o, i) => L.push(`| ${i + 1} | ${o.suspicious ? "⚠ " : ""}${itemName(o.itemId)} (${itemLabel(o.itemId)}) | \`${o.itemId}\` | ${C.QUALITY_NAMES[o.quality]} | ${o.city} | ${o.sellCity} | ${fmt(o.buyPrice)} | ${fmt(o.sellPrice)} | ${fmt(o.avgPrice)} | ${fmt(o.profit)} | ${o.percent.toFixed(1)} % | ${o.units == null ? "—" : "~" + fmt(o.units)} | ${fmt(o.totalProfit)} | ${o.dailyVolume == null ? "—" : o.dailyVolume.toFixed(1)} | ${itemWeight(o.itemId) || "—"} | ${ago(Math.max(o.buyAgeH, o.sellAgeH))} |`));
    return L.join("\n");
  }

  let toastTimer;
  function toast(t) {
    $("toast").textContent = t; $("toast").hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { $("toast").hidden = true; }, 2500);
  }
  async function copy(text, okMsg) {
    try { await navigator.clipboard.writeText(text); toast(okMsg); }
    catch {
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); toast(okMsg); } catch { toast("No se pudo copiar."); }
      ta.remove();
    }
  }

  // ---------------------------------------------------------------- eventos
  function showTab(name) {
    document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
    document.querySelectorAll(".tab").forEach((s) => { s.hidden = s.id !== "tab-" + name; });
    $("updateBar").hidden = name === "calc" || name === "more";
    document.dispatchEvent(new CustomEvent("albion-tab", { detail: name }));
  }

  async function start() {
    initForm();
    document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
    $("refresh").addEventListener("click", update);
    $("stop").addEventListener("click", () => { stopFlag = true; });
    let t;
    const changed = () => { clearTimeout(t); t = setTimeout(() => { saveSettings(); refresh(); }, 200); };
    const inCalc = (e) => e.target.closest("#tab-calc, #tab-more");  // las calculadoras se gestionan en calcui.js
    document.querySelector("main").addEventListener("change", (e) => { if (!inCalc(e)) changed(); });
    document.querySelector("main").addEventListener("input", (e) => {
      if (!inCalc(e) && e.target.matches('input[type="text"], input[type="search"]')) changed();
    });
    $("list").addEventListener("click", (e) => {
      const star = e.target.closest(".star");
      if (star) {
        document.dispatchEvent(new CustomEvent("albion-fav", { detail: { id: star.dataset.fav, quality: Number(star.dataset.q) } }));
        star.textContent = "★"; star.classList.add("on");
        return;
      }
      const card = e.target.closest(".card");
      if (card) copy(itemName(card.dataset.id), "Nombre copiado: " + itemName(card.dataset.id));
    });
    $("export").addEventListener("click", () => {
      if (!opps.length) { toast("Primero actualiza los precios."); return; }
      copy(buildReport(readForm()), "Informe copiado. Pégalo en tu chat con Claude.");
    });
    try {
      // Publicada con el workflow, items.json está junto a la página; servida desde el repositorio, en ../data/
      let res = await fetch("items.json");
      if (!res.ok) res = await fetch("../data/items.json");
      items = await res.json();
      byId = new Map(items.map((i) => [i.id, i]));
    } catch (e) {
      setStatus("No se pudo cargar la lista de objetos. Recarga la página.");
    }
    refresh();
  }
  // Lo que usan las calculadoras (web/calcui.js)
  window.AlbionApp = { entries, getJson, itemName, itemLabel, getItems: () => items, readForm, fmt, esc, norm, num, toast,
    CITY_LABEL, variantIds, copy, ago, base, showTab };
  start();
})();
