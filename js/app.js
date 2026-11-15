(function () {
  "use strict";
  const C = window.AlbionCalc;
  const ITEMS = window.ALBION_ITEMS || [];
  const $ = (id) => document.getElementById(id);
  const fmt = new Intl.NumberFormat("es-ES");

  const CATEGORY_NAMES = {
    weapons: "Armas", armors: "Armaduras", head: "Cascos", shoes: "Botas",
    offhands: "Secundarias", bags: "Bolsas", capes: "Capas", gathering: "Recolección",
  };
  const DEFAULTS = {
    cats: ["weapons", "armors", "head", "shoes", "offhands", "bags", "capes"],
    tiers: [4, 5, 6], enchs: [0, 1], quals: [1, 2, 3], cities: C.CITIES.filter((c) => c !== "Caerleon").concat("Caerleon"),
  };
  const CONCURRENCY = 3;
  const STORE_KEY = "albionbm.settings.v1";

  const byId = new Map(ITEMS.map((i) => [i.id, i]));
  let results = [];
  let sort = { key: "percent", asc: false };
  let abort = null;
  let lastRows = null;

  // ---------- Filtros ----------
  function chips(container, values, labelFn, checked) {
    $(container).innerHTML = values.map((v) =>
      `<label><input type="checkbox" value="${v}" ${checked.includes(v) ? "checked" : ""}> ${labelFn(v)}</label>`
    ).join("");
  }
  const checkedValues = (id, num) =>
    [...$(id).querySelectorAll("input:checked")].map((i) => (num ? Number(i.value) : i.value));

  function loadSettings() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; } catch { return {}; }
  }
  function saveSettings() {
    const s = readForm();
    try { localStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch { /* sin almacenamiento */ }
  }

  function initForm() {
    const s = Object.assign({}, DEFAULTS, loadSettings());
    chips("cats", Object.keys(CATEGORY_NAMES), (c) => CATEGORY_NAMES[c], s.cats);
    chips("tiers", [4, 5, 6, 7, 8], (t) => "T" + t, s.tiers);
    chips("enchs", [0, 1, 2, 3, 4], (e) => "." + e, s.enchs);
    chips("quals", [1, 2, 3, 4, 5], (q) => C.QUALITY_NAMES[q], s.quals);
    chips("cities", C.CITIES, (c) => c, s.cities);
    for (const k of ["server", "search", "buyMode", "minPct", "minSilver", "maxCost", "maxAge"]) {
      if (s[k] !== undefined && s[k] !== null) $(k).value = s[k];
    }
    for (const k of ["premium", "bestOnly"]) if (typeof s[k] === "boolean") $(k).checked = s[k];
  }

  function readForm() {
    return {
      server: $("server").value, search: $("search").value.trim(), buyMode: $("buyMode").value,
      premium: $("premium").checked, bestOnly: $("bestOnly").checked,
      minPct: $("minPct").value, minSilver: $("minSilver").value, maxCost: $("maxCost").value, maxAge: $("maxAge").value,
      cats: checkedValues("cats"), tiers: checkedValues("tiers", true), enchs: checkedValues("enchs", true),
      quals: checkedValues("quals", true), cities: checkedValues("cities"),
    };
  }

  function norm(s) { return s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }

  /** Lista de IDs de API (con encantamiento) que cumplen los filtros. */
  function selectedIds(f) {
    const q = norm(f.search);
    const ids = [];
    for (const it of ITEMS) {
      if (!f.cats.includes(it.c) || !f.tiers.includes(it.t)) continue;
      if (q && !norm(it.es).includes(q) && !norm(it.en).includes(q) && !norm(it.id).includes(q)) continue;
      for (const e of it.e) if (f.enchs.includes(e)) ids.push(C.variantId(it.id, e));
    }
    return ids;
  }

  function updateCount() {
    const n = selectedIds(readForm()).length;
    $("count").textContent = `${fmt.format(n)} objetos a consultar`;
  }

  // ---------- API ----------
  async function fetchChunk(server, ids, locations, qualities, signal) {
    const url = `https://${server}.albion-online-data.com/api/v2/stats/prices/${ids.map(encodeURIComponent).join(",")}.json` +
      `?locations=${encodeURIComponent(locations.join(","))}&qualities=${qualities.join(",")}`;
    for (let attempt = 0; attempt < 4; attempt++) {
      const res = await fetch(url, { signal });
      if (res.ok) return res.json();
      if (res.status === 429 || res.status >= 500) {
        await new Promise((r) => setTimeout(r, 2000 * (attempt + 1)));
        continue;
      }
      throw new Error(`HTTP ${res.status}`);
    }
    throw new Error("La API no responde (límite de peticiones). Prueba con menos objetos.");
  }

  async function run() {
    const f = readForm();
    saveSettings();
    const ids = selectedIds(f);
    if (!ids.length) return setStatus("No hay objetos con esos filtros.");
    if (!f.cities.length || !f.quals.length) return setStatus("Elige al menos una ciudad y una calidad.");

    // Para el MN hacen falta también las calidades inferiores (una orden de calidad Q acepta >= Q).
    const qualities = [1, 2, 3, 4, 5].filter((q) => q <= Math.max(...f.quals));
    const locations = f.cities.concat(C.BLACK_MARKET);
    const chunks = C.chunkIds(ids);

    abort = new AbortController();
    setBusy(true);
    const rows = [];
    lastRows = rows;
    let done = 0, failed = 0, next = 0;
    progress(0);
    setStatus(`Consultando ${fmt.format(ids.length)} objetos en ${chunks.length} peticiones…`);

    const worker = async () => {
      while (next < chunks.length && !abort.signal.aborted) {
        const chunk = chunks[next++];
        try {
          rows.push(...(await fetchChunk(f.server, chunk, locations, qualities, abort.signal)));
        } catch (e) {
          if (abort.signal.aborted) return;
          failed++;
          console.warn(e);
        }
        done++;
        progress(done / chunks.length);
        compute(rows, f);
      }
    };
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, chunks.length) }, worker));
    setBusy(false);
    compute(rows, f);
    const msg = abort.signal.aborted ? "Búsqueda detenida." : "Búsqueda terminada.";
    setStatus(`${msg} ${fmt.format(results.length)} oportunidades encontradas` +
      (failed ? ` · ${failed} peticiones fallaron (revisa tu conexión o vuelve a intentarlo).` : "."));
  }

  function compute(rows, f) {
    let list = C.computeOpportunities(rows, {
      premium: f.premium, buyMode: f.buyMode, maxAgeHours: Number(f.maxAge) || 24,
      cities: f.cities, qualities: f.quals,
    });
    const minPct = Number(f.minPct) || -Infinity, minSilver = Number(f.minSilver) || -Infinity;
    const maxCost = Number(f.maxCost) || Infinity;
    list = list.filter((r) => r.percent >= minPct && r.profit >= minSilver && r.buyPrice <= maxCost);
    if (f.bestOnly) {
      const best = new Map();
      for (const r of list) {
        const k = r.itemId + "|" + r.quality;
        if (!best.has(k) || best.get(k).profit < r.profit) best.set(k, r);
      }
      list = [...best.values()];
    }
    for (const r of list) {
      const base = byId.get(r.itemId.split("@")[0]);
      r.ench = Number(r.itemId.split("@")[1] || 0);
      r.tier = base ? base.t : "";
      r.name = base ? base.es : r.itemId;
      r.age = Math.max(r.buyAge, r.bmAge);
    }
    results = list;
    render();
  }

  // ---------- Render ----------
  function ago(h) {
    if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
    if (h < 48) return `${Math.round(h)} h`;
    return `${Math.round(h / 24)} d`;
  }
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function render() {
    const { key, asc } = sort;
    const sorted = results.slice().sort((a, b) => {
      const x = a[key], y = b[key];
      const d = typeof x === "string" ? x.localeCompare(y, "es") : x - y;
      return asc ? d : -d;
    });
    document.querySelectorAll("th[data-sort]").forEach((th) => {
      th.classList.toggle("sorted", th.dataset.sort === key);
      th.classList.toggle("asc", th.dataset.sort === key && asc);
    });
    const tbody = $("results").tBodies[0];
    if (!sorted.length) {
      tbody.innerHTML = `<tr><td colspan="9" class="empty">Sin oportunidades con estos filtros todavía.</td></tr>`;
      return;
    }
    tbody.innerHTML = sorted.slice(0, 500).map((r) => `
      <tr>
        <td class="item">
          <img loading="lazy" alt="" onerror="this.style.visibility='hidden'" src="https://render.albiononline.com/v1/item/${encodeURIComponent(r.itemId)}.png?quality=${r.quality}&size=64">
          <span>${esc(r.name)}<small>T${r.tier}.${r.ench} · ${esc(r.itemId)}</small></span>
        </td>
        <td>${C.QUALITY_NAMES[r.quality]}${r.bmQuality !== r.quality ? `<small class="muted"> (orden MN: ${C.QUALITY_NAMES[r.bmQuality]})</small>` : ""}</td>
        <td>${esc(r.city)}</td>
        <td class="num">${fmt.format(r.buyPrice)}</td>
        <td class="num">${fmt.format(r.bmPrice)}</td>
        <td class="num">${fmt.format(r.revenue)}</td>
        <td class="num ${r.profit > 0 ? "good" : "bad"}">${fmt.format(r.profit)}</td>
        <td class="num ${r.percent > 0 ? "good" : "bad"}">${r.percent.toFixed(1)} %</td>
        <td class="num" title="Compra: hace ${ago(r.buyAge)} · MN: hace ${ago(r.bmAge)}">${ago(r.age)}</td>
      </tr>`).join("") +
      (sorted.length > 500 ? `<tr><td colspan="9" class="empty">Mostrando 500 de ${fmt.format(sorted.length)}. Ajusta los filtros para ver menos.</td></tr>` : "");
  }

  function setStatus(t) { $("status").textContent = t; }
  function progress(p) { $("progress").firstElementChild.style.width = (p * 100).toFixed(1) + "%"; }
  function setBusy(b) {
    $("run").disabled = b; $("stop").hidden = !b; $("progress").hidden = !b;
  }

  // ---------- Eventos ----------
  initForm();
  updateCount();
  $("filters").addEventListener("change", () => {
    updateCount(); saveSettings();
    if (lastRows && !abort?.signal.aborted && $("run").disabled === false) compute(lastRows, readForm());
  });
  $("search").addEventListener("input", updateCount);
  $("run").addEventListener("click", run);
  $("stop").addEventListener("click", () => abort && abort.abort());
  document.querySelectorAll("th[data-sort]").forEach((th) => th.addEventListener("click", () => {
    const k = th.dataset.sort;
    sort = { key: k, asc: sort.key === k ? !sort.asc : k === "name" || k === "city" };
    render();
  }));
})();
