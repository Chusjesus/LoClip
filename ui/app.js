/* LoClip — interfaz (funciona en el navegador y dentro del panel de Premiere). */
(() => {
  const API = "";                        // misma URL que sirve la interfaz
  const params = new URLSearchParams(location.search);
  const HOST = params.get("host") || ""; // "ppro" cuando corre dentro de Premiere
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

  // ------------------------------------------------------------ estado
  const state = {
    lang: localStorage.getItem("loclip.lang") || (navigator.language || "es").slice(0, 2),
    mode: "all", results: [], selected: new Set(), sources: [], collections: [], concepts: [],
    activeCollection: null, query: "", system: null, lastAction: null,
  };
  if (!["es", "en"].includes(state.lang)) state.lang = "es";
  if (HOST === "ppro") document.body.classList.add("ppro");
  const t = (k) => (I18N[state.lang] && I18N[state.lang][k]) || I18N.es[k] || k;

  function applyI18n() {
    $$("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
    $$("[data-i18n-title]").forEach((el) => (el.title = t(el.dataset.i18nTitle)));
    $("#q").placeholder = t("placeholder");
    document.documentElement.lang = state.lang;
  }

  // ------------------------------------------------------------ helpers
  async function api(path, opts = {}) {
    const r = await fetch(API + path, { headers: { "content-type": "application/json" }, ...opts });
    if (!r.ok) {
      let msg = r.statusText;
      try { msg = (await r.json()).detail || msg; } catch (e) {}
      throw new Error(msg);
    }
    return r.json();
  }
  const post = (p, body) => api(p, { method: "POST", body: JSON.stringify(body || {}) });
  const patch = (p, body) => api(p, { method: "PATCH", body: JSON.stringify(body || {}) });
  const put = (p, body) => api(p, { method: "PUT", body: JSON.stringify(body || {}) });
  const del = (p) => api(p, { method: "DELETE" });

  let toastTimer;
  function toast(msg, ms = 2200) {
    const el = $("#toast");
    el.textContent = msg; el.classList.remove("hidden");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.add("hidden"), ms);
  }
  function tc(sec, fps) {
    sec = Math.max(0, sec || 0);
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
    const f = fps ? Math.floor((sec - Math.floor(sec)) * fps) : null;
    const base = (h ? String(h).padStart(2, "0") + ":" : "") + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
    return f === null ? base : base + ":" + String(f).padStart(2, "0");
  }
  function modal(html) {
    $("#modalBox").innerHTML = html; $("#modal").classList.remove("hidden");
    const first = $("#modalBox input[type=text]"); if (first) first.focus();
  }
  function closeModal() { $("#modal").classList.add("hidden"); }
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ------------------------------------------------------------ puente con Premiere (panel CEP)
  const pending = new Map();
  let bridgeId = 0;
  function host(action, args = {}) {
    if (HOST !== "ppro") return Promise.reject(new Error("not in host"));
    return new Promise((resolve, reject) => {
      const id = ++bridgeId;
      pending.set(id, { resolve, reject });
      window.parent.postMessage({ loclip: true, id, action, args }, "*");
      setTimeout(() => { if (pending.has(id)) { pending.delete(id); reject(new Error(t("ppro_error"))); } }, 20000);
    });
  }
  window.addEventListener("message", (e) => {
    const d = e.data;
    if (!d || !d.loclip || !pending.has(d.id)) return;
    const p = pending.get(d.id); pending.delete(d.id);
    d.ok ? p.resolve(d.result) : p.reject(new Error(d.error || t("ppro_error")));
  });

  // ------------------------------------------------------------ fuentes
  async function loadSources() {
    state.sources = await api("/api/sources");
    const ul = $("#sourceList"); ul.innerHTML = "";
    for (const s of state.sources) {
      const li = document.createElement("li");
      const busy = s.pending > 0;
      li.innerHTML = `<input type="checkbox" ${s.enabled ? "checked" : ""} title="${t("available_only")}">
        <span class="dot ${s.available ? (busy ? "busy" : "") : "off"}" title="${s.available ? "" : t("offline")}"></span>
        <span class="name" title="${esc(s.path)}">${esc(s.name)}</span><span class="cnt">${s.done}/${s.files}</span>`;
      li.querySelector("input").addEventListener("click", async (e) => { e.stopPropagation(); await patch(`/api/sources/${s.id}`, { enabled: e.target.checked }); });
      li.addEventListener("click", () => sourceMenu(s));
      ul.appendChild(li);
    }
  }
  function sourceMenu(s) {
    modal(`<h3>${esc(s.name)}</h3><div class="kv">
      <div>${t("source_path")}</div><div>${esc(s.path)}</div>
      <div>${t("source_kind")}</div><div>${t("kind_" + s.kind)}</div>
      <div>Archivos</div><div>${s.done} / ${s.files} ${s.errors ? `· <a href="#" id="showErrors">${s.errors} ${t("error").toLowerCase()}</a>` : ""}</div>
      <div>Estado</div><div>${s.available ? "online" : t("offline")}</div></div>
      <div class="btns"><button id="mScan">${t("rescan")}</button><button id="mPrune">${t("prune")}</button><button id="mRemove">${t("remove")}</button><button id="mClose">${t("cancel")}</button></div>`);
    $("#mClose").onclick = closeModal;
    $("#mScan").onclick = async () => { const r = await post(`/api/sources/${s.id}/scan`); toast(`+${r.added} / ~${r.updated}`); closeModal(); loadSources(); };
    $("#mPrune").onclick = async () => { const r = await post(`/api/sources/${s.id}/prune`); toast(`-${r.removed}`); closeModal(); loadSources(); };
    $("#mRemove").onclick = async () => { if (confirm(t("confirm_remove_source"))) { await del(`/api/sources/${s.id}`); closeModal(); loadSources(); } };
    const se = $("#showErrors"); if (se) se.onclick = async (e) => { e.preventDefault(); const errs = await api("/api/files/errors"); modal(`<h3>${t("errors_title")}</h3><div class="small">${errs.map((x) => `<div><b>${esc(x.name)}</b><br><span class="muted">${esc(x.error)}</span></div>`).join("") || "—"}</div><div class="btns"><button onclick="document.getElementById('modal').classList.add('hidden')">OK</button></div>`); };
  }
  $("#btnAddSource").onclick = () => {
    modal(`<h3>${t("add_source_title")}</h3><p class="small muted">${t("add_source_help")}</p>
      <label>${t("source_path")}</label><div class="row"><input type="text" id="srcPath" style="flex:1"><button id="srcBrowse" class="mini">…</button></div>
      <label>${t("source_name")}</label><input type="text" id="srcName">
      <label>${t("source_kind")}</label><select id="srcKind"><option value="local">${t("kind_local")}</option><option value="nas">${t("kind_nas")}</option><option value="cloud">${t("kind_cloud")}</option></select>
      <div id="browse" class="small"></div>
      <div class="btns"><button id="mCancel">${t("cancel")}</button><button class="primary" id="mAdd">${t("add")}</button></div>`);
    $("#mCancel").onclick = closeModal;
    $("#srcBrowse").onclick = () => browse($("#srcPath").value);
    $("#mAdd").onclick = async () => {
      try {
        const r = await post("/api/sources", { path: $("#srcPath").value.trim(), name: $("#srcName").value.trim(), kind: $("#srcKind").value });
        toast(`${t("added")}: ${r.added}`); closeModal(); loadSources();
      } catch (e) { toast(t("error") + ": " + e.message, 4000); }
    };
  }
  async function browse(path) {
    try {
      const r = await api(`/api/browse?path=${encodeURIComponent(path || "")}`);
      $("#srcPath").value = r.path;
      $("#browse").innerHTML = `<div style="max-height:200px;overflow:auto;border:1px solid var(--line);border-radius:6px;padding:4px;margin-top:6px">
        ${r.parent !== "" || r.path ? `<div><a href="#" data-p="${esc(r.parent)}">⬆ ..</a></div>` : ""}
        ${r.dirs.map((d) => `<div><a href="#" data-p="${esc(d)}">📁 ${esc(d.split(/[\\/]/).filter(Boolean).pop() || d)}</a></div>`).join("")}</div>`;
      $$("#browse a").forEach((a) => (a.onclick = (e) => { e.preventDefault(); browse(a.dataset.p); }));
    } catch (e) { toast(e.message); }
  }

  // ------------------------------------------------------------ colecciones
  async function loadCollections() {
    state.collections = await api("/api/collections");
    const ul = $("#collectionList"); ul.innerHTML = "";
    for (const c of state.collections) {
      const li = document.createElement("li");
      li.className = state.activeCollection === c.id ? "active" : "";
      li.innerHTML = `<span class="name">★ ${esc(c.name)}</span><span class="cnt">${c.count}</span>`;
      li.onclick = () => showCollection(c);
      li.oncontextmenu = (e) => { e.preventDefault(); collectionMenu(c); };
      ul.appendChild(li);
    }
  }
  function collectionMenu(c) {
    modal(`<h3>★ ${esc(c.name)}</h3><label>${t("collection_name")}</label><input type="text" id="cName" value="${esc(c.name)}">
      <div class="btns"><button id="cDel">${t("delete")}</button><button id="cCancel">${t("cancel")}</button><button class="primary" id="cSave">${t("save")}</button></div>`);
    $("#cCancel").onclick = closeModal;
    $("#cSave").onclick = async () => { await patch(`/api/collections/${c.id}`, { name: $("#cName").value }); closeModal(); loadCollections(); };
    $("#cDel").onclick = async () => { if (confirm(t("delete_collection_confirm"))) { await del(`/api/collections/${c.id}`); state.activeCollection = null; closeModal(); loadCollections(); } };
  }
  $("#btnAddCollection").onclick = () => {
    modal(`<h3>${t("new_collection")}</h3><label>${t("collection_name")}</label><input type="text" id="cName">
      <div class="btns"><button id="cCancel">${t("cancel")}</button><button class="primary" id="cSave">${t("add")}</button></div>`);
    $("#cCancel").onclick = closeModal;
    $("#cSave").onclick = async () => { await post("/api/collections", { name: $("#cName").value || t("new_collection") }); closeModal(); loadCollections(); };
  };
  async function showCollection(c) {
    state.activeCollection = c.id;
    const r = await api(`/api/collections/${c.id}/items`);
    state.lastAction = { type: "collection", id: c.id };
    render(r.results, `★ ${c.name}`);
    loadCollections();
  }
  async function addToCollection(momentIds) {
    if (!state.collections.length) { $("#btnAddCollection").click(); return; }
    modal(`<h3>${t("add_to_collection")}</h3><select id="cSel">${state.collections.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select>
      <div class="btns"><button id="cCancel">${t("cancel")}</button><button class="primary" id="cOk">${t("add")}</button></div>`);
    $("#cCancel").onclick = closeModal;
    $("#cOk").onclick = async () => {
      const cid = $("#cSel").value;
      for (const m of momentIds) await post(`/api/collections/${cid}/items`, { moment_id: m });
      toast(t("added")); closeModal(); loadCollections();
    };
  }

  // ------------------------------------------------------------ conceptos
  async function loadConcepts() {
    state.concepts = await api("/api/concepts");
    const ul = $("#conceptList"); ul.innerHTML = "";
    for (const c of state.concepts) {
      const li = document.createElement("li");
      li.innerHTML = `<span class="name">#${esc(c.name)}</span><span class="cnt">${c.n_examples}</span>`;
      li.onclick = () => { $("#q").value = "#" + c.name; doSearch(); };
      li.oncontextmenu = async (e) => { e.preventDefault(); if (confirm(`${t("delete")} #${c.name}?`)) { await del(`/api/concepts/${c.id}`); loadConcepts(); } };
      ul.appendChild(li);
    }
  }
  function teachConcept(momentIds) {
    if (!momentIds.length) { toast(t("need_selection"), 3500); return; }
    modal(`<h3>${t("teach_concept")}</h3><p class="small muted">${t("concept_help")}</p>
      <label>${t("concept_name")}</label><input type="text" id="kName" list="kList"><datalist id="kList">${state.concepts.map((c) => `<option value="${esc(c.name)}">`).join("")}</datalist>
      <div class="btns"><button id="kCancel">${t("cancel")}</button><button class="primary" id="kOk">${t("save")}</button></div>`);
    $("#kCancel").onclick = closeModal;
    $("#kOk").onclick = async () => {
      const name = $("#kName").value.trim().replace(/^#/, "");
      if (!name) return;
      const existing = state.concepts.find((c) => c.name.toLowerCase() === name.toLowerCase());
      try {
        if (existing) { for (const m of momentIds) await post(`/api/concepts/${existing.id}/examples`, { moment_id: m, positive: true }); }
        else await post("/api/concepts", { name, positive: momentIds, negative: [] });
        toast(t("concept_created"), 3500); closeModal(); clearSelection(); loadConcepts();
      } catch (e) { toast(t("error") + ": " + e.message, 4000); }
    };
  }
  $("#btnAddConcept").onclick = () => teachConcept([...state.selected]);

  // ------------------------------------------------------------ búsqueda
  function sourceFilter() { return ""; /* las fuentes se filtran con su casilla "enabled" en el servidor */ }
  async function doSearch() {
    const q = $("#q").value.trim();
    if (!q) return;
    state.query = q; state.activeCollection = null;
    const per = $("#perFile").value, avail = $("#availableOnly").checked;
    try {
      const r = await api(`/api/search?q=${encodeURIComponent(q)}&mode=${state.mode}&k=80&per_file=${per}&available_only=${avail}`);
      state.lastAction = { type: "search", q };
      render(r.results, `${t("results_for")} “${q}”`);
    } catch (e) { toast(t("error") + ": " + e.message, 4000); }
  }
  $("#searchForm").onsubmit = (e) => { e.preventDefault(); doSearch(); };
  $$("#modes .chip").forEach((b) => (b.onclick = () => { $$("#modes .chip").forEach((x) => x.classList.remove("active")); b.classList.add("active"); state.mode = b.dataset.mode; if (state.query) doSearch(); }));
  $("#perFile").onchange = () => rerun();
  $("#availableOnly").onchange = () => rerun();
  function rerun() {
    const a = state.lastAction; if (!a) return;
    if (a.type === "search") doSearch();
    else if (a.type === "similar") similar(a.id);
  }
  $("#imgFile").onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    const r = await fetch(`${API}/api/search/image?per_file=${$("#perFile").value}`, { method: "POST", body: fd }).then((x) => x.json());
    state.lastAction = { type: "image" };
    render(r.results, `🖼 ${f.name}`);
    e.target.value = "";
  };
  document.addEventListener("paste", async (e) => {
    const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
    if (!item) return;
    const fd = new FormData(); fd.append("file", item.getAsFile(), "pasted.png");
    const r = await fetch(`${API}/api/search/image?per_file=${$("#perFile").value}`, { method: "POST", body: fd }).then((x) => x.json());
    render(r.results, "🖼 clipboard");
  });
  async function similar(momentId) {
    const r = await api(`/api/similar/${momentId}?per_file=${$("#perFile").value}`);
    state.lastAction = { type: "similar", id: momentId };
    render(r.results, t("similar"));
  }
  $("#btnMatchMonitor").onclick = async () => {
    try {
      const sm = await host("sourceMonitor");
      if (!sm || !sm.path) throw new Error(t("file_not_available"));
      const r = await post("/api/match_frame", { path: sm.path, t: sm.t || 0, per_file: Number($("#perFile").value) });
      render(r.results, `🎯 ${sm.path.split(/[\\/]/).pop()} @ ${tc(sm.t)}`);
    } catch (e) { toast(e.message, 4000); }
  };

  // ------------------------------------------------------------ resultados
  function render(results, title) {
    state.results = results; clearSelection(false);
    $("#resultsTitle").textContent = `${title} · ${results.length}`;
    const grid = $("#results"); grid.innerHTML = "";
    $("#empty").textContent = results.length ? "" : t("no_results");
    for (const r of results) {
      const card = document.createElement("div");
      card.className = "card"; card.dataset.mid = r.moment_id;
      const why = r.why.split("+").map((w) => `<span>${t(w + "_hit") !== w + "_hit" ? t(w + "_hit") : w}</span>`).join("");
      const range = r.kind === "image" ? "" : `${tc(r.t_start, r.fps)} – ${tc(r.t_end, r.fps)}`;
      card.innerHTML = `<input type="checkbox" class="sel">
        <div class="th"><img loading="lazy" src="${API}/api/thumb/${esc(r.thumb)}" alt="">${r.available ? "" : `<span class="off">${t("offline")}</span>`}<div class="why">${why}</div>${range ? `<span class="tc">${range}</span>` : ""}</div>
        <div class="body"><div class="name" title="${esc(r.path)}">${esc(r.name)}</div>${r.text ? `<div class="text">“${esc(r.text)}”</div>` : ""}</div>
        <div class="actions">
          <button class="ppro-only" data-a="insert">${t("insert")}</button>
          <button class="ppro-only" data-a="open">${t("open_source")}</button>
          <button data-a="similar">${t("similar")}</button>
          <button data-a="star">★</button>
          <button data-a="details">…</button>
        </div>`;
      card.querySelector(".sel").onchange = (e) => { e.target.checked ? state.selected.add(r.moment_id) : state.selected.delete(r.moment_id); card.classList.toggle("selected", e.target.checked); updateSelection(); };
      card.querySelector(".th").onclick = () => (HOST === "ppro" ? openInSource(r) : showDetail(r));
      card.querySelector(".th").ondblclick = () => (HOST === "ppro" ? insert(r) : null);
      const th = card.querySelector(".th img");
      if (r.kind === "video" && r.available) {
        // Al pasar el mouse, mostramos un frame de la mitad del momento (scrub ligero).
        let hoverT;
        card.querySelector(".th").onmousemove = (e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
          const tt = r.t_start + frac * Math.max(0.01, r.t_end - r.t_start);
          clearTimeout(hoverT); hoverT = setTimeout(() => (th.src = `${API}/api/frame/${r.file_id}?t=${tt.toFixed(2)}`), 120);
        };
        card.querySelector(".th").onmouseleave = () => { clearTimeout(hoverT); th.src = `${API}/api/thumb/${r.thumb}`; };
      }
      card.querySelectorAll("[data-a]").forEach((b) => (b.onclick = (e) => { e.stopPropagation(); action(b.dataset.a, r); }));
      grid.appendChild(card);
    }
  }
  function action(a, r) {
    if (a === "insert") insert(r);
    else if (a === "open") openInSource(r);
    else if (a === "similar") similar(r.moment_id);
    else if (a === "star") addToCollection([r.moment_id]);
    else if (a === "details") showDetail(r);
  }
  function updateSelection() {
    const n = state.selected.size;
    $("#selectionBar").classList.toggle("hidden", n === 0);
    $("#selCount").textContent = `${n} ${t("selected")}`;
  }
  function clearSelection(rerender = true) { state.selected.clear(); $$(".card.selected").forEach((c) => { c.classList.remove("selected"); c.querySelector(".sel").checked = false; }); updateSelection(); }
  $("#selClear").onclick = () => clearSelection();
  $("#selToCollection").onclick = () => addToCollection([...state.selected]);
  $("#selToConcept").onclick = () => teachConcept([...state.selected]);
  $("#selInsertAll").onclick = async () => { for (const r of state.results.filter((x) => state.selected.has(x.moment_id))) await insert(r, true); toast(t("inserted")); };
  $("#zoom").oninput = (e) => document.documentElement.style.setProperty("--card", e.target.value + "px");

  // ------------------------------------------------------------ Premiere
  async function insert(r, silent = false) {
    if (!r.available) { toast(t("file_not_available"), 3500); return; }
    try {
      const res = await host("insert", { path: r.path, t_start: r.t_start, t_end: r.kind === "image" ? 0 : r.t_end, name: r.name, kind: r.kind });
      if (res && res.error) throw new Error(res.error);
      if (!silent) toast(t("inserted"));
    } catch (e) { toast(e.message, 4000); }
  }
  async function openInSource(r) {
    if (!r.available) { toast(t("file_not_available"), 3500); return; }
    try { const res = await host("openSource", { path: r.path, t: r.t_start, t_end: r.t_end, kind: r.kind }); if (res && res.error) throw new Error(res.error); }
    catch (e) { toast(e.message, 4000); }
  }

  // ------------------------------------------------------------ detalle
  async function showDetail(r) {
    const d = await api(`/api/files/${r.file_id}`);
    const box = $("#detail"); box.classList.remove("hidden");
    $("#detailName").textContent = d.name;
    $("#detailMeta").textContent = `${d.width}×${d.height} · ${d.fps ? d.fps.toFixed(2) + " fps · " : ""}${tc(d.duration)} · ${d.codec} · ${(d.size / 1e6).toFixed(1)} MB · ${d.available ? "online" : t("offline")}\n${d.path}`;
    const pv = $("#detailPreview");
    const playable = d.available && d.kind !== "audio" && /\.(mp4|m4v|webm|mov|jpg|jpeg|png|webp|gif)$/i.test(d.name);
    pv.innerHTML = d.kind === "image" ? `<img src="${API}/api/media/${d.id}">` : playable
      ? `<video controls preload="metadata" src="${API}/api/media/${d.id}#t=${r.t_start || 0}"></video>`
      : `<img src="${API}/api/thumb/${esc(r.thumb || (d.moments[0] || {}).thumb || "")}">`;
    $("#detailActions").innerHTML = HOST === "ppro" ? `<button id="dInsert">${t("insert")}</button><button id="dOpen">${t("open_source")}</button>` : "";
    if (HOST === "ppro") { $("#dInsert").onclick = () => insert(r); $("#dOpen").onclick = () => openInSource(r); }
    $("#detailKeywords").value = d.keywords || "";
    $("#detailSaveKw").onclick = async () => { await put(`/api/files/${d.id}/keywords`, { keywords: $("#detailKeywords").value }); toast(t("saved")); };
    $("#detailMoments").innerHTML = d.moments.map((m) => `<img src="${API}/api/thumb/${esc(m.thumb)}" title="${tc(m.t_start)}" data-mid="${m.moment_id}" data-t="${m.t_start}">`).join("");
    $$("#detailMoments img").forEach((im) => (im.onclick = () => { const v = pv.querySelector("video"); if (v) v.currentTime = Number(im.dataset.t); else similar(Number(im.dataset.mid)); }));
    $("#detailTxt").href = `${API}/api/files/${d.id}/transcript.txt`;
    const segs = await api(`/api/files/${d.id}/transcript`);
    $("#detailTranscript").innerHTML = segs.length ? segs.map((s) => `<div class="seg" data-id="${s.id}"><span class="t" data-t="${s.t_start}">${tc(s.t_start)}</span><span class="sp" contenteditable spellcheck="false" title="${t("speaker")}">${esc(s.speaker)}</span><span class="x" contenteditable spellcheck="false">${esc(s.text)}</span></div>`).join("") : `<span class="muted small">—</span>`;
    $$("#detailTranscript .seg").forEach((seg) => {
      const id = seg.dataset.id;
      seg.querySelector(".t").onclick = () => { const v = pv.querySelector("video"); const tt = Number(seg.querySelector(".t").dataset.t); if (v) v.currentTime = tt; if (HOST === "ppro") host("openSource", { path: d.path, t: tt, t_end: tt, kind: d.kind }).catch(() => {}); };
      seg.querySelector(".x").onblur = (e) => put(`/api/segments/${id}`, { text: e.target.textContent }).then(() => toast(t("saved"), 900));
      seg.querySelector(".sp").onblur = (e) => put(`/api/segments/${id}`, { speaker: e.target.textContent.trim() });
    });
  }
  $("#detailClose").onclick = () => $("#detail").classList.add("hidden");

  // ------------------------------------------------------------ estado / ajustes
  async function pollStatus() {
    try {
      const s = await api("/api/status");
      if (!s.ready) { $("#statusText").textContent = s.loading || t("loading"); $("#statusFill").style.width = "0"; return; }
      const ix = s.indexer;
      let txt;
      if (ix.paused) txt = t("paused");
      else if (ix.running) txt = `${t("indexing")} ${ix.done}/${ix.total} · ${ix.phase} · ${ix.current}${ix.eta_s ? " · ~" + tc(ix.eta_s) : ""}`;
      else txt = `${t("idle")} · ${s.files} files · ${s.moments} moments · ${s.transcribed} transcribed${s.errors ? " · " + s.errors + " err" : ""}`;
      $("#statusText").textContent = txt;
      const frac = ix.running && ix.total ? (ix.done + (ix.progress || 0)) / ix.total : 0;
      $("#statusFill").style.width = (frac * 100).toFixed(1) + "%";
      $("#btnPause").textContent = ix.paused ? t("resume") : t("pause");
      $("#btnPause").onclick = () => post(ix.paused ? "/api/index/resume" : "/api/index/pause");
      if (ix.running && !pollStatus._lastRefresh || Date.now() - (pollStatus._lastRefresh || 0) > 15000) { pollStatus._lastRefresh = Date.now(); loadSources(); }
    } catch (e) { $("#statusText").textContent = "⚠ " + e.message; }
  }
  $("#btnLang").onclick = () => { state.lang = state.lang === "es" ? "en" : "es"; localStorage.setItem("loclip.lang", state.lang); applyI18n(); };
  $("#btnSettings").onclick = async () => {
    const s = await api("/api/system");
    const hw = s.hardware || {}, rec = s.recommendation || {}, st = s.settings || {};
    const vopts = Object.entries(s.visual_models).map(([k, m]) => `<option value="${k}" ${st.visual_model === k ? "selected" : ""}>${k} — ${m.name} (${m.size_mb} MB)${(rec.visual_options || []).includes(k) ? "" : " ⚠"}</option>`).join("");
    const sopts = s.speech_models.map((m) => `<option value="${m}" ${st.speech_model === m ? "selected" : ""}>${m}</option>`).join("");
    modal(`<h3>${t("settings")}</h3>
      <h4>${t("settings_hw")}</h4><div class="kv"><div>OS</div><div>${esc(hw.os)} ${esc(hw.arch)}</div><div>GPU</div><div>${esc(hw.gpu_name || "—")} ${hw.vram_gb ? hw.vram_gb + " GB" : ""}</div><div>Device</div><div>${esc(hw.device)}</div><div>RAM</div><div>${hw.ram_gb || "?"} GB</div>
      <div>${t("data_dir")}</div><div>${esc(s.data_dir)}</div><div>Loaded</div><div>${s.loaded ? esc(s.loaded.visual) + " · " + esc(s.loaded.speech || "—") : t("loading")}</div></div>
      <p class="small muted">${(rec.notes || []).join(" ")}</p>
      <h4>${t("settings_models")}</h4>
      <label>${t("settings_visual")}</label><select id="sVisual"><option value="auto" ${st.visual_model === "auto" ? "selected" : ""}>auto (${rec.visual_tier})</option>${vopts}</select>
      <label>${t("settings_speech")}</label><select id="sSpeech"><option value="auto" ${st.speech_model === "auto" ? "selected" : ""}>auto (${rec.speech_model})</option>${sopts}</select>
      <label><input type="checkbox" id="sTranscribe" ${st.transcribe ? "checked" : ""}> ${t("settings_transcribe")}</label>
      <label>${t("settings_fps")}</label><select id="sFps">${[0.5, 1, 2].map((f) => `<option value="${f}" ${Number(st.sample_fps) === f ? "selected" : ""}>${f}</option>`).join("")}</select>
      <p class="small muted">${t("settings_note_models")}</p>
      <div class="btns"><button id="sCancel">${t("cancel")}</button><button class="primary" id="sSave">${t("save")}</button></div>`);
    $("#sCancel").onclick = closeModal;
    $("#sSave").onclick = async () => {
      const r = await put("/api/settings", { visual_model: $("#sVisual").value, speech_model: $("#sSpeech").value, transcribe: $("#sTranscribe").checked, sample_fps: Number($("#sFps").value) });
      toast(r.restart_required ? t("restart_required") : t("saved"), 4000); closeModal();
    };
  };

  // ------------------------------------------------------------ inicio
  applyI18n();
  $("#empty").textContent = t("welcome");
  loadSources(); loadCollections(); loadConcepts();
  pollStatus(); setInterval(pollStatus, 2500);
  $("#q").focus();
})();
