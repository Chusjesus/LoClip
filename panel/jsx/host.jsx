/* LoClip — lado ExtendScript (corre dentro de Premiere Pro).
   Usa solo la API interna de Premiere, que es idéntica en español, inglés y cualquier otro idioma. */

var LC_TICKS = 254016000000; // ticks por segundo en Premiere

function LC_parse(s) { try { return eval("(" + s + ")"); } catch (e) { return {}; } }
function LC_str(v) {
  if (v === null || v === undefined) return "null";
  var t = typeof v;
  if (t === "number" || t === "boolean") return String(v);
  if (t === "string") return '"' + v.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n").replace(/\r/g, "") + '"';
  if (v instanceof Array) { var a = []; for (var i = 0; i < v.length; i++) a.push(LC_str(v[i])); return "[" + a.join(",") + "]"; }
  var o = []; for (var k in v) if (v.hasOwnProperty(k)) o.push('"' + k + '":' + LC_str(v[k]));
  return "{" + o.join(",") + "}";
}
function LC_norm(p) { return String(p || "").replace(/\\/g, "/").toLowerCase(); }

function LC_findItem(root, path) {
  var want = LC_norm(path);
  for (var i = 0; i < root.children.numItems; i++) {
    var it = root.children[i];
    if (it.type === ProjectItemType.BIN) { var r = LC_findItem(it, path); if (r) return r; }
    else if (it.type === ProjectItemType.CLIP || it.type === ProjectItemType.FILE) {
      try { if (LC_norm(it.getMediaPath()) === want) return it; } catch (e) {}
    }
  }
  return null;
}
function LC_bin() {
  var root = app.project.rootItem;
  for (var i = 0; i < root.children.numItems; i++) {
    var it = root.children[i];
    if (it.type === ProjectItemType.BIN && it.name === "LoClip") return it;
  }
  return root.createBin("LoClip");
}
function LC_importOrFind(path) {
  var it = LC_findItem(app.project.rootItem, path);
  if (it) return it;
  var bin = LC_bin();
  app.project.importFiles([path], true, bin, false);
  return LC_findItem(bin, path) || LC_findItem(app.project.rootItem, path);
}

function LC_insert(json) {
  var a = LC_parse(json);
  try {
    var seq = app.project.activeSequence;
    if (!seq) return LC_str({ error: "no_sequence" });
    var item = LC_importOrFind(a.path);
    if (!item) return LC_str({ error: "No se pudo importar: " + a.path });
    var clip = item;
    if (a.kind !== "image" && a.t_end > a.t_start) {
      // Subclip con el tramo exacto del momento: no toca los puntos de entrada/salida del clip original.
      var name = item.name + " [" + LC_tc(a.t_start) + "-" + LC_tc(a.t_end) + "]";
      var sub = null;
      try { sub = item.createSubClip(name, String(Math.round(a.t_start * LC_TICKS)), String(Math.round(a.t_end * LC_TICKS)), 0, 1, 1); } catch (e1) { sub = null; }
      if (sub) { clip = sub; try { var b = LC_bin(); if (sub.parent !== b) sub.moveBin(b); } catch (e2) {} }
      else { try { item.setInPoint(a.t_start, 4); item.setOutPoint(a.t_end, 4); } catch (e3) {} }
    }
    var pos = seq.getPlayerPosition();
    var track = null;
    for (var i = 0; i < seq.videoTracks.numTracks; i++) { var tr = seq.videoTracks[i]; if (!tr.isLocked()) { track = tr; break; } }
    if (!track) return LC_str({ error: "all_tracks_locked" });
    var ok = false;
    try { track.insertClip(clip, pos.seconds); ok = true; } catch (e4) {}
    if (!ok) { try { track.insertClip(clip, pos); ok = true; } catch (e5) {} }
    if (!ok) { try { track.overwriteClip(clip, pos.seconds); ok = true; } catch (e6) { return LC_str({ error: "insert_failed: " + e6 }); } }
    return LC_str({ ok: true, name: clip.name });
  } catch (e) { return LC_str({ error: String(e) }); }
}

function LC_openSource(json) {
  var a = LC_parse(json);
  try {
    var item = LC_importOrFind(a.path);
    if (!item) return LC_str({ error: "No se pudo importar: " + a.path });
    if (a.kind !== "image") {
      try { item.setInPoint(a.t, 4); if (a.t_end > a.t) item.setOutPoint(a.t_end, 4); } catch (e1) {}
    }
    app.sourceMonitor.openProjectItem(item);
    return LC_str({ ok: true });
  } catch (e) { return LC_str({ error: String(e) }); }
}

function LC_sourceMonitor() {
  try {
    var item = app.sourceMonitor.getProjectItem();
    if (!item) return LC_str({ error: "no_source_clip" });
    var pos = app.sourceMonitor.getPosition();
    return LC_str({ path: item.getMediaPath(), t: pos ? pos.seconds : 0, name: item.name });
  } catch (e) { return LC_str({ error: String(e) }); }
}

function LC_playhead() {
  try {
    var seq = app.project.activeSequence;
    if (!seq) return LC_str({ error: "no_sequence" });
    return LC_str({ t: seq.getPlayerPosition().seconds, sequence: seq.name });
  } catch (e) { return LC_str({ error: String(e) }); }
}

function LC_tc(s) {
  s = Math.max(0, s || 0);
  var m = Math.floor(s / 60), r = Math.floor(s % 60);
  return (m < 10 ? "0" : "") + m + ":" + (r < 10 ? "0" : "") + r;
}
