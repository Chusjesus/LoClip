"""Servidor local de LoClip (FastAPI). Solo escucha en 127.0.0.1."""
from __future__ import annotations

import io
import logging
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import hardware, media
from .config import data_dir, load_settings, save_settings, thumbs_dir
from .db import DB
from .embeddings import VisualModel, from_blob, to_blob
from .indexer import Indexer
from .search import Searcher, VectorIndex
from .transcribe import SpeechModel

log = logging.getLogger("loclip")
from . import __version__ as VERSION

UI_DIR = Path(__file__).resolve().parent.parent.parent / "ui"


class State:
    db: DB
    settings: dict
    hw: hardware.HardwareInfo
    rec: dict
    visual: VisualModel
    index: VectorIndex
    speech: SpeechModel | None
    indexer: Indexer
    searcher: Searcher
    ready: bool = False
    loading_msg: str = "Iniciando…"


S = State()
app = FastAPI(title="LoClip", version=VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def boot() -> None:
    S.db = DB()
    S.settings = load_settings()
    S.hw = hardware.detect()
    S.rec = hardware.recommend(S.hw)
    S.searcher = Searcher(S.db)
    device = S.settings.get("device", "auto")
    if device == "auto":
        device = S.rec["device"]
    vtier = S.settings.get("visual_model", "auto")
    if vtier == "auto":
        vtier = S.rec["visual_tier"]
    S.loading_msg = "Cargando modelo visual… (la primera vez descarga ~400 MB)"
    S.visual = VisualModel(vtier, device)
    S.index = VectorIndex(S.db, S.visual.dim, S.visual.name)
    S.speech = None
    if S.settings.get("transcribe", True):
        S.loading_msg = "Cargando modelo de voz… (la primera vez descarga el modelo)"
        size = S.settings.get("speech_model", "auto")
        if size == "auto":
            size = S.rec["speech_model"]
        try:
            S.speech = SpeechModel(size, S.rec["speech_device"], S.rec["speech_compute"])
        except Exception as e:  # noqa: BLE001
            log.warning("No se pudo cargar el modelo de voz: %s", e)
    S.indexer = Indexer(S.db, S.settings, S.visual, S.index, S.speech)
    S.ready = True
    S.loading_msg = ""


@app.on_event("startup")
def _startup():
    threading.Thread(target=boot, daemon=True, name="loclip-boot").start()


def require_ready():
    if not S.ready:
        raise HTTPException(503, S.loading_msg or "Cargando…")


# ------------------------------------------------------------------ sistema
@app.get("/api/health")
def health():
    return {"ok": True, "ready": S.ready, "loading": S.loading_msg, "version": VERSION}


@app.get("/api/system")
def system():
    out = {"version": VERSION, "ready": S.ready, "loading": S.loading_msg, "data_dir": str(data_dir()),
           "hardware": S.hw.to_dict() if hasattr(S, "hw") else {}, "recommendation": getattr(S, "rec", {}),
           "settings": getattr(S, "settings", {}), "visual_models": hardware.VISUAL_MODELS,
           "speech_models": hardware.SPEECH_MODELS}
    if S.ready:
        out["loaded"] = {"visual": S.visual.name, "visual_device": S.visual.device,
                         "speech": S.speech.size if S.speech else None,
                         "speech_device": S.speech.device if S.speech else None}
    return out


@app.put("/api/settings")
def put_settings(body: dict):
    s = load_settings()
    s.update(body or {})
    save_settings(s)
    if S.ready:
        S.settings.update(s)
    return {"ok": True, "settings": s, "restart_required": any(k in body for k in ("visual_model", "speech_model", "device", "port", "transcribe"))}


@app.post("/api/shutdown")
def shutdown():
    def _die():
        time.sleep(0.3)
        os._exit(0)
    threading.Thread(target=_die, daemon=True).start()
    return {"ok": True}


@app.get("/api/update")
def update_status(check: bool = False):
    from . import updater
    return updater.check(VERSION) if check else updater.status(VERSION)


@app.post("/api/update/apply")
def update_apply():
    from . import updater

    def before_launch():
        if S.ready:
            S.indexer.pause(True)
    return updater.apply(before_launch)


@app.get("/api/browse")
def browse(path: str = ""):
    """Lista carpetas (solo lectura) para el selector de fuentes."""
    if not path:
        if sys.platform == "win32":
            import string
            drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
            return {"path": "", "dirs": drives, "parent": ""}
        path = "/"
    p = Path(path)
    if not p.is_dir():
        raise HTTPException(404, "No existe la carpeta")
    dirs = []
    try:
        for e in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            if e.is_dir() and not e.name.startswith(".") and not e.name.startswith("$"):
                dirs.append(str(e))
    except PermissionError:
        pass
    parent = str(p.parent) if p.parent != p else ""
    return {"path": str(p), "dirs": dirs, "parent": parent}


# ------------------------------------------------------------------- fuentes
class SourceIn(BaseModel):
    path: str
    name: str = ""
    kind: str = "local"


@app.get("/api/sources")
def sources():
    rows = S.db.q("SELECT * FROM sources ORDER BY id") if hasattr(S, "db") else []
    out = []
    for r in rows:
        d = dict(r)
        d["available"] = os.path.isdir(r["path"])
        c = S.db.one("SELECT COUNT(*) n, SUM(status='done') d, SUM(status='pending') p, SUM(status='error') e FROM files WHERE source_id=?", (r["id"],))
        d.update(files=c["n"] or 0, done=c["d"] or 0, pending=c["p"] or 0, errors=c["e"] or 0)
        out.append(d)
    return out


@app.post("/api/sources")
def add_source(body: SourceIn):
    require_ready()
    p = os.path.abspath(body.path)
    if not os.path.isdir(p):
        raise HTTPException(400, "La carpeta no existe o no está disponible")
    name = body.name or os.path.basename(p.rstrip("\\/")) or p
    sid = S.db.x("INSERT OR IGNORE INTO sources(name, path, kind, enabled, read_only, created_at) VALUES (?,?,?,1,1,?)",
                 (name, p, body.kind, time.time()))
    if not sid:
        sid = S.db.one("SELECT id FROM sources WHERE path=?", (p,))["id"]
    res = S.indexer.scan_source(sid)
    return {"id": sid, **res}


@app.patch("/api/sources/{sid}")
def patch_source(sid: int, body: dict):
    if "enabled" in body:
        S.db.x("UPDATE sources SET enabled=? WHERE id=?", (1 if body["enabled"] else 0, sid))
    if "name" in body:
        S.db.x("UPDATE sources SET name=? WHERE id=?", (body["name"], sid))
    if "kind" in body:
        S.db.x("UPDATE sources SET kind=? WHERE id=?", (body["kind"], sid))
    return {"ok": True}


@app.delete("/api/sources/{sid}")
def del_source(sid: int):
    require_ready()
    for r in S.db.q("SELECT id FROM files WHERE source_id=?", (sid,)):
        S.indexer.remove_file(r["id"])
    S.db.x("DELETE FROM sources WHERE id=?", (sid,))
    return {"ok": True}


@app.post("/api/sources/{sid}/scan")
def scan_source(sid: int):
    require_ready()
    return S.indexer.scan_source(sid)


@app.post("/api/sources/{sid}/prune")
def prune_source(sid: int):
    require_ready()
    return {"removed": S.indexer.prune_missing(sid)}


@app.get("/api/status")
def status():
    if not S.ready:
        return {"ready": False, "loading": S.loading_msg}
    c = S.db.one("SELECT COUNT(*) n, SUM(status='done') d, SUM(status='pending') p, SUM(status='error') e, SUM(transcribed=1) t FROM files")
    m = S.db.one("SELECT COUNT(*) n FROM moments")["n"]
    return {"ready": True, "indexer": S.indexer.state, "files": c["n"] or 0, "done": c["d"] or 0, "pending": c["p"] or 0,
            "errors": c["e"] or 0, "transcribed": c["t"] or 0, "moments": m}


@app.post("/api/index/pause")
def pause():
    require_ready()
    S.indexer.pause(True)
    return {"ok": True}


@app.post("/api/index/resume")
def resume():
    require_ready()
    S.indexer.pause(False)
    return {"ok": True}


@app.post("/api/files/{fid}/reindex")
def reindex(fid: int, what: str = "all"):
    require_ready()
    S.indexer.reindex_file(fid, what)
    return {"ok": True}


@app.get("/api/files/errors")
def file_errors():
    return [dict(r) for r in S.db.q("SELECT id, name, path, error FROM files WHERE status='error' ORDER BY id DESC LIMIT 200")]


# ------------------------------------------------------------------ búsqueda
def _parse_ids(s: str | None) -> list[int] | None:
    if not s:
        return None
    return [int(x) for x in s.split(",") if x.strip().isdigit()]


def _fuse(lists: list[list[dict]], k: int, available_only: bool) -> list[dict]:
    """Fusión por rango recíproco: mezcla resultados visuales, de nombre y de voz en una sola lista."""
    scores: dict[tuple, float] = {}
    items: dict[tuple, dict] = {}
    for lst in lists:
        for rank, it in enumerate(lst):
            key = (it["file_id"], round(it["t_start"], 1))
            scores[key] = scores.get(key, 0.0) + 1.0 / (30 + rank)
            if key not in items:
                items[key] = it
            else:
                items[key]["why"] = items[key]["why"] + "+" + it["why"]
                for extra in ("text", "speaker", "segment_id"):
                    if extra in it and extra not in items[key]:
                        items[key][extra] = it[extra]
    out = sorted(items.values(), key=lambda it: -scores[(it["file_id"], round(it["t_start"], 1))])
    if available_only:
        out = [o for o in out if o["available"]]
    return out[:k]


@app.get("/api/search")
def search(q: str = "", mode: str = "all", k: int = 60, sources: str | None = None, kinds: str | None = None,
           per_file: int = 3, available_only: bool = False):
    require_ready()
    q = (q or "").strip()
    if not q:
        return {"results": [], "query": q}
    allowed = S.searcher.allowed_file_ids(_parse_ids(sources), kinds.split(",") if kinds else None)
    lists = []
    if q.startswith("#"):  # búsqueda por concepto
        c = S.db.one("SELECT * FROM concepts WHERE name=? COLLATE NOCASE", (q[1:].strip(),))
        if not c:
            raise HTTPException(404, "Concepto no encontrado")
        vec = from_blob(c["embedding"], S.visual.dim)[0]
        return {"results": S.searcher.search_visual(S.index, vec, allowed, k, per_file), "query": q}
    if mode in ("all", "visual"):
        vec = S.visual.encode_text([q])[0]
        lists.append(S.searcher.search_visual(S.index, vec, allowed, k, per_file))
    if mode in ("all", "name"):
        lists.append(S.searcher.search_files(q, allowed, k))
    if mode in ("all", "speech"):
        lists.append(S.searcher.search_speech(q, allowed, k))
    if mode == "all":
        return {"results": _fuse(lists, k, available_only), "query": q}
    res = lists[0] if lists else []
    if available_only:
        res = [r for r in res if r["available"]]
    return {"results": res[:k], "query": q}


@app.post("/api/search/image")
async def search_image(file: UploadFile = File(...), k: int = 60, sources: str | None = None, per_file: int = 3):
    require_ready()
    from PIL import Image
    data = await file.read()
    img = Image.open(io.BytesIO(data)).convert("RGB")
    vec = S.visual.encode_images([img])[0]
    allowed = S.searcher.allowed_file_ids(_parse_ids(sources))
    return {"results": S.searcher.search_visual(S.index, vec, allowed, k, per_file)}


@app.get("/api/similar/{moment_id}")
def similar(moment_id: int, k: int = 60, sources: str | None = None, per_file: int = 3):
    require_ready()
    vec = S.index.vec(moment_id)
    if vec is None:
        raise HTTPException(404, "Momento no encontrado")
    allowed = S.searcher.allowed_file_ids(_parse_ids(sources))
    res = S.searcher.search_visual(S.index, vec, allowed, k + 1, per_file)
    return {"results": [r for r in res if r["moment_id"] != moment_id][:k]}


class MatchFrameIn(BaseModel):
    path: str
    t: float = 0.0
    k: int = 60
    sources: str | None = None
    per_file: int = 3


@app.post("/api/match_frame")
def match_frame(body: MatchFrameIn):
    """'Match source monitor': recibe la ruta del clip abierto en Premiere y el tiempo del cabezal."""
    require_ready()
    if not os.path.exists(body.path):
        raise HTTPException(404, "El archivo no está disponible")
    kind = media.kind_of(body.path)
    img = media.load_image(body.path) if kind == "image" else media.frame_at(body.path, body.t)
    if img is None:
        raise HTTPException(400, "No se pudo leer el frame")
    vec = S.visual.encode_images([img])[0]
    allowed = S.searcher.allowed_file_ids(_parse_ids(body.sources))
    return {"results": S.searcher.search_visual(S.index, vec, allowed, body.k, body.per_file)}


# ------------------------------------------------------------------ archivos
@app.get("/api/thumb/{name}")
def thumb(name: str):
    p = thumbs_dir() / os.path.basename(name)
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.get("/api/frame/{fid}")
def frame(fid: int, t: float = 0.0):
    f = S.db.one("SELECT path, kind FROM files WHERE id=?", (fid,))
    if not f or not os.path.exists(f["path"]):
        raise HTTPException(404)
    img = media.load_image(f["path"]) if f["kind"] == "image" else media.frame_at(f["path"], t)
    if img is None:
        raise HTTPException(404)
    buf = io.BytesIO()
    img.thumbnail((640, 640))
    img.save(buf, "JPEG", quality=85)
    return Response(buf.getvalue(), media_type="image/jpeg")


@app.get("/api/media/{fid}")
def media_file(fid: int):
    """Sirve el archivo original (solo lectura) para previsualizar en la interfaz cuando el navegador puede."""
    f = S.db.one("SELECT path FROM files WHERE id=?", (fid,))
    if not f or not os.path.exists(f["path"]):
        raise HTTPException(404)
    return FileResponse(f["path"])


@app.get("/api/files/{fid}")
def file_info(fid: int):
    f = S.db.one("SELECT * FROM files WHERE id=?", (fid,))
    if not f:
        raise HTTPException(404)
    d = dict(f)
    d["available"] = os.path.exists(f["path"])
    kw = S.db.one("SELECT keywords FROM file_keywords WHERE file_id=?", (fid,))
    d["keywords"] = kw["keywords"] if kw else ""
    d["moments"] = [dict(r) for r in S.db.q("SELECT id AS moment_id, t_start, t_end, thumb, n_frames FROM moments WHERE file_id=? ORDER BY t_start", (fid,))]
    return d


@app.put("/api/files/{fid}/keywords")
def put_keywords(fid: int, body: dict):
    S.db.x("INSERT INTO file_keywords(file_id, keywords) VALUES (?,?) ON CONFLICT(file_id) DO UPDATE SET keywords=excluded.keywords",
           (fid, body.get("keywords", "")))
    S.db.reindex_file_fts(fid)
    return {"ok": True}


@app.get("/api/files/{fid}/transcript")
def transcript(fid: int):
    return [dict(r) for r in S.db.q("SELECT id, t_start, t_end, speaker, lang, text, edited FROM segments WHERE file_id=? ORDER BY t_start", (fid,))]


@app.put("/api/segments/{seg_id}")
def put_segment(seg_id: int, body: dict):
    if "text" in body:
        S.db.x("UPDATE segments SET text=?, edited=1 WHERE id=?", (body["text"], seg_id))
    if "speaker" in body:
        S.db.x("UPDATE segments SET speaker=? WHERE id=?", (body["speaker"], seg_id))
    return {"ok": True}


@app.get("/api/files/{fid}/transcript.txt")
def transcript_txt(fid: int):
    f = S.db.one("SELECT name FROM files WHERE id=?", (fid,))
    rows = S.db.q("SELECT t_start, t_end, speaker, text FROM segments WHERE file_id=? ORDER BY t_start", (fid,))

    def tc(t):
        h, r = divmod(int(t), 3600)
        m, s = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"
    lines = [f"[{tc(r['t_start'])} - {tc(r['t_end'])}] {(r['speaker'] + ': ') if r['speaker'] else ''}{r['text']}" for r in rows]
    return Response("\n".join(lines), media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{(f["name"] if f else "transcript")}.txt"'})


# ---------------------------------------------------------------- colecciones
@app.get("/api/collections")
def collections():
    out = []
    for c in S.db.q("SELECT * FROM collections ORDER BY name"):
        d = dict(c)
        d["count"] = S.db.one("SELECT COUNT(*) n FROM collection_items WHERE collection_id=?", (c["id"],))["n"]
        out.append(d)
    return out


@app.post("/api/collections")
def add_collection(body: dict):
    cid = S.db.x("INSERT INTO collections(name, color, created_at) VALUES (?,?,?)", (body.get("name", "Nueva"), body.get("color", ""), time.time()))
    return {"id": cid}


@app.patch("/api/collections/{cid}")
def patch_collection(cid: int, body: dict):
    if "name" in body:
        S.db.x("UPDATE collections SET name=? WHERE id=?", (body["name"], cid))
    if "color" in body:
        S.db.x("UPDATE collections SET color=? WHERE id=?", (body["color"], cid))
    return {"ok": True}


@app.delete("/api/collections/{cid}")
def del_collection(cid: int):
    S.db.x("DELETE FROM collections WHERE id=?", (cid,))
    return {"ok": True}


@app.get("/api/collections/{cid}/items")
def collection_items(cid: int):
    rows = S.db.q("SELECT moment_id FROM collection_items WHERE collection_id=? ORDER BY added_at DESC", (cid,))
    ids = [r["moment_id"] for r in rows]
    mr = S.searcher.moment_rows(ids)
    return {"results": [S.searcher.format(mr[i], 1.0, "collection") for i in ids if i in mr]}


@app.post("/api/collections/{cid}/items")
def add_item(cid: int, body: dict):
    S.db.x("INSERT OR IGNORE INTO collection_items(collection_id, moment_id, added_at) VALUES (?,?,?)", (cid, int(body["moment_id"]), time.time()))
    return {"ok": True}


@app.delete("/api/collections/{cid}/items/{moment_id}")
def del_item(cid: int, moment_id: int):
    S.db.x("DELETE FROM collection_items WHERE collection_id=? AND moment_id=?", (cid, moment_id))
    return {"ok": True}


@app.get("/api/moments/{moment_id}/collections")
def moment_collections(moment_id: int):
    return [r["collection_id"] for r in S.db.q("SELECT collection_id FROM collection_items WHERE moment_id=?", (moment_id,))]


# ------------------------------------------------------------------ conceptos
class ConceptIn(BaseModel):
    name: str
    positive: list[int] = []
    negative: list[int] = []


def _concept_vec(pos: list[int], neg: list[int]) -> np.ndarray:
    pv = [S.index.vec(m) for m in pos]
    pv = [v for v in pv if v is not None]
    if not pv:
        raise HTTPException(400, "Se necesitan ejemplos positivos indexados")
    v = np.mean(np.stack(pv), axis=0)
    nv = [S.index.vec(m) for m in neg]
    nv = [x for x in nv if x is not None]
    if nv:
        v = v - 0.5 * np.mean(np.stack(nv), axis=0)
    return v / (np.linalg.norm(v) + 1e-8)


@app.get("/api/concepts")
def concepts():
    return [dict(r, embedding=None) for r in S.db.q("SELECT id, name, visual_model, n_examples, created_at FROM concepts ORDER BY name")]


@app.post("/api/concepts")
def add_concept(body: ConceptIn):
    require_ready()
    vec = _concept_vec(body.positive, body.negative)
    name = body.name.strip().lstrip("#")
    cid = S.db.x("INSERT INTO concepts(name, visual_model, embedding, n_examples, created_at) VALUES (?,?,?,?,?) "
                 "ON CONFLICT(name) DO UPDATE SET embedding=excluded.embedding, n_examples=excluded.n_examples",
                 (name, S.visual.name, to_blob(vec), len(body.positive), time.time()))
    cid = S.db.one("SELECT id FROM concepts WHERE name=?", (name,))["id"]
    S.db.x("DELETE FROM concept_examples WHERE concept_id=?", (cid,))
    S.db.xmany("INSERT OR IGNORE INTO concept_examples(concept_id, moment_id, positive) VALUES (?,?,?)",
               [(cid, m, 1) for m in body.positive] + [(cid, m, 0) for m in body.negative])
    return {"id": cid, "name": name}


@app.post("/api/concepts/{cid}/examples")
def add_concept_example(cid: int, body: dict):
    """Agrega un ejemplo (positivo o negativo) y recalcula el concepto."""
    require_ready()
    S.db.x("INSERT OR REPLACE INTO concept_examples(concept_id, moment_id, positive) VALUES (?,?,?)",
           (cid, int(body["moment_id"]), 1 if body.get("positive", True) else 0))
    pos = [r["moment_id"] for r in S.db.q("SELECT moment_id FROM concept_examples WHERE concept_id=? AND positive=1", (cid,))]
    neg = [r["moment_id"] for r in S.db.q("SELECT moment_id FROM concept_examples WHERE concept_id=? AND positive=0", (cid,))]
    vec = _concept_vec(pos, neg)
    S.db.x("UPDATE concepts SET embedding=?, n_examples=? WHERE id=?", (to_blob(vec), len(pos), cid))
    return {"ok": True, "n_examples": len(pos)}


@app.delete("/api/concepts/{cid}")
def del_concept(cid: int):
    S.db.x("DELETE FROM concepts WHERE id=?", (cid,))
    return {"ok": True}


# ------------------------------------------------------------------ interfaz
if UI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
