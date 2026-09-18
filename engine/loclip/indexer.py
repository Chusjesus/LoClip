"""Indexador en segundo plano: escanea fuentes, analiza video/imagen/audio y llena la base de datos."""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from . import media
from .config import data_dir
from .db import DB
from .embeddings import VisualModel, to_blob
from .search import VectorIndex
from .transcribe import SpeechModel

log = logging.getLogger("loclip.indexer")


class Indexer:
    def __init__(self, db: DB, settings: dict, visual: VisualModel, index: VectorIndex, speech: SpeechModel | None):
        self.db, self.settings, self.visual, self.index, self.speech = db, settings, visual, index, speech
        self.state = {
            "running": False, "paused": False, "current": "", "current_file_id": 0, "phase": "",
            "done": 0, "total": 0, "errors": 0, "started_at": 0.0, "eta_s": 0, "last_error": "",
            "progress": 0.0,
        }
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="loclip-indexer")
        self._thread.start()
        self.tmp = Path(tempfile.gettempdir()) / "loclip"
        self.tmp.mkdir(exist_ok=True)

    # ------------------------------------------------------------------ control
    def scan_source(self, source_id: int) -> dict:
        src = self.db.one("SELECT * FROM sources WHERE id=?", (source_id,))
        if not src:
            return {"added": 0, "updated": 0}
        added = updated = 0
        known = {r["path"]: r for r in self.db.q("SELECT id, path, size, mtime FROM files WHERE source_id=?", (source_id,))}
        rows = []
        for path, size, mtime in media.scan(src["path"]):
            k = media.kind_of(path)
            if not k:
                continue
            if path in known:
                r = known[path]
                if int(r["size"]) != size or abs(float(r["mtime"]) - mtime) > 1:
                    self.db.x("UPDATE files SET size=?, mtime=?, status='pending', transcribed=0 WHERE id=?", (size, mtime, r["id"]))
                    updated += 1
                continue
            rows.append((source_id, path, os.path.basename(path), Path(path).suffix.lower(), k, size, mtime))
            added += 1
        if rows:
            self.db.xmany(
                "INSERT OR IGNORE INTO files(source_id, path, name, ext, kind, size, mtime) VALUES (?,?,?,?,?,?,?)", rows
            )
            for r in self.db.q("SELECT id FROM files WHERE source_id=? AND id NOT IN (SELECT rowid FROM files_fts)", (source_id,)):
                self.db.reindex_file_fts(r["id"])
        self._wake.set()
        return {"added": added, "updated": updated}

    def prune_missing(self, source_id: int) -> int:
        """Quita del índice los archivos que ya no existen. Solo cuando el usuario lo pide."""
        n = 0
        for r in self.db.q("SELECT id, path FROM files WHERE source_id=?", (source_id,)):
            if not os.path.exists(r["path"]):
                self.remove_file(r["id"])
                n += 1
        return n

    def remove_file(self, file_id: int) -> None:
        for r in self.db.q("SELECT thumb FROM moments WHERE file_id=?", (file_id,)):
            try:
                (data_dir() / "thumbs" / r["thumb"]).unlink(missing_ok=True)
            except Exception:
                pass
        self.db.x("DELETE FROM files WHERE id=?", (file_id,))
        self.db.x("DELETE FROM files_fts WHERE rowid=?", (file_id,))
        self.index.remove_file(file_id)

    def reindex_file(self, file_id: int, what: str = "all") -> None:
        if what in ("all", "visual"):
            self.db.x("UPDATE files SET status='pending' WHERE id=?", (file_id,))
        if what in ("all", "speech"):
            self.db.x("UPDATE files SET transcribed=0 WHERE id=?", (file_id,))
        self._wake.set()

    def pause(self, paused: bool) -> None:
        self.state["paused"] = paused
        if not paused:
            self._wake.set()

    def kick(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    # ------------------------------------------------------------------- loop
    def _pending(self):
        return self.db.q(
            """SELECT f.* FROM files f JOIN sources s ON s.id=f.source_id
               WHERE (f.status='pending' OR (f.transcribed=0 AND f.status='done' AND f.kind IN ('video','audio')))
               ORDER BY f.status='pending' DESC, f.mtime DESC LIMIT 50"""
        )

    def _loop(self) -> None:
        while not self._stop.is_set():
            if self.state["paused"]:
                self._wake.wait(2)
                self._wake.clear()
                continue
            pend = self._pending()
            if not pend:
                self.state.update(running=False, current="", phase="", current_file_id=0)
                self._wake.wait(5)
                self._wake.clear()
                continue
            if not self.state["running"]:
                total = self.db.one("SELECT COUNT(*) c FROM files WHERE status='pending' OR (transcribed=0 AND kind IN ('video','audio'))")["c"]
                self.state.update(running=True, started_at=time.time(), done=0, total=total, errors=0)
            for f in pend:
                if self._stop.is_set() or self.state["paused"]:
                    break
                self._process(f)
                self.state["done"] += 1
                el = time.time() - self.state["started_at"]
                rate = self.state["done"] / el if el > 0 else 0
                remaining = max(0, self.state["total"] - self.state["done"])
                self.state["eta_s"] = int(remaining / rate) if rate > 0 else 0

    def _process(self, f) -> None:
        fid, path = f["id"], f["path"]
        self.state.update(current=f["name"], current_file_id=fid, progress=0.0)
        if not os.path.exists(path):
            # Fuente desconectada (LucidLink sin montar, disco externo…): lo dejamos pendiente, sin error.
            self.state["phase"] = "offline"
            time.sleep(0.05)
            return
        try:
            if f["status"] == "pending":
                self.state["phase"] = "visual"
                self._visual(f)
            if self.speech and self.settings.get("transcribe", True) and f["kind"] in ("video", "audio"):
                f2 = self.db.one("SELECT * FROM files WHERE id=?", (fid,))
                if f2 and not f2["transcribed"] and f2["status"] == "done":
                    self.state["phase"] = "speech"
                    self._speech(f2)
        except Exception as e:  # noqa: BLE001
            log.exception("Error indexando %s", path)
            self.state["errors"] += 1
            self.state["last_error"] = f"{f['name']}: {e}"
            self.db.x("UPDATE files SET status='error', error=? WHERE id=?", (str(e)[:500], fid))

    # ------------------------------------------------------------------ visual
    def _visual(self, f) -> None:
        fid, path, kind = f["id"], f["path"], f["kind"]
        pr = media.probe(path)
        self.db.x("UPDATE files SET duration=?, width=?, height=?, fps=?, codec=? WHERE id=?",
                  (pr.duration, pr.width, pr.height, pr.fps, pr.codec, fid))
        # Limpiar resultados anteriores de este archivo
        self.db.x("DELETE FROM moments WHERE file_id=?", (fid,))
        self.index.remove_file(fid)
        thumb_size = int(self.settings.get("thumb_size", 320))

        if kind == "image":
            img = media.load_image(path)
            if img is None:
                raise RuntimeError("No se pudo leer la imagen")
            vec = self.visual.encode_images([img])[0]
            th = media.save_thumb(img, media.thumb_name(fid, 0), thumb_size)
            mid = self.db.x("INSERT INTO moments(file_id, t_start, t_end, thumb, embedding, n_frames) VALUES (?,?,?,?,?,1)",
                            (fid, 0.0, 0.0, th, to_blob(vec)))
            self.index.add([mid], fid, vec[None, :])
        elif kind == "video" and pr.has_video:
            self._video_moments(fid, path, pr, thumb_size)
        elif kind == "audio" or (kind == "video" and not pr.has_video):
            # Sin imagen: creamos un único momento "vacío" para que aparezca en resultados de voz/nombre.
            from PIL import Image
            img = Image.new("RGB", (16, 9), (40, 40, 40))
            vec = np.zeros((self.visual.dim,), dtype=np.float32)
            th = media.save_thumb(img, media.thumb_name(fid, 0), thumb_size)
            self.db.x("INSERT INTO moments(file_id, t_start, t_end, thumb, embedding, n_frames) VALUES (?,?,?,?,?,1)",
                      (fid, 0.0, pr.duration, th, to_blob(vec)))
        self.db.x("UPDATE files SET status='done', error='', visual_model=?, indexed_at=? WHERE id=?",
                  (self.visual.name, time.time(), fid))
        self.db.reindex_file_fts(fid)

    def _video_moments(self, fid: int, path: str, pr: media.Probe, thumb_size: int) -> None:
        sample_fps = float(self.settings.get("sample_fps", 1.0))
        sim_thr = float(self.settings.get("moment_similarity", 0.90))
        max_s = float(self.settings.get("max_video_seconds", 0) or 0)
        batch_imgs, batch_ts = [], []
        moments: list[dict] = []  # {t_start, t_end, vecs:[...], thumb_img}
        cur: dict | None = None
        total_frames = max(1, int((min(pr.duration, max_s) if max_s else pr.duration) * sample_fps))

        def flush_batch():
            nonlocal cur
            if not batch_imgs:
                return
            vecs = self.visual.encode_images(batch_imgs)
            for t, img, v in zip(batch_ts, batch_imgs, vecs):
                if cur is not None and float(np.dot(cur["ref"], v)) >= sim_thr:
                    cur["t_end"] = t + 1.0 / sample_fps
                    cur["vecs"].append(v)
                else:
                    if cur is not None:
                        moments.append(cur)
                    cur = {"t_start": t, "t_end": t + 1.0 / sample_fps, "vecs": [v], "ref": v, "thumb_img": img.copy()}
            batch_imgs.clear()
            batch_ts.clear()

        n = 0
        for t, img in media.iter_frames(path, sample_fps, max_s):
            batch_imgs.append(img)
            batch_ts.append(t)
            n += 1
            if len(batch_imgs) >= 32:
                flush_batch()
                self.state["progress"] = min(0.99, n / total_frames)
        flush_batch()
        if cur is not None:
            moments.append(cur)
        if not moments:
            raise RuntimeError("No se pudieron leer frames del video")

        rows, vecs = [], []
        for m in moments:
            v = np.mean(np.stack(m["vecs"]), axis=0)
            v = v / (np.linalg.norm(v) + 1e-8)
            # Miniatura del centro del momento: usamos el primer frame (ya en memoria) para no re-decodificar.
            th = media.save_thumb(m["thumb_img"], media.thumb_name(fid, m["t_start"]), thumb_size)
            rows.append((fid, float(m["t_start"]), float(min(m["t_end"], pr.duration or m["t_end"])), th, to_blob(v), len(m["vecs"])))
            vecs.append(v)
        c = self.db.conn()
        ids = []
        for r in rows:
            cur_ = c.execute("INSERT INTO moments(file_id, t_start, t_end, thumb, embedding, n_frames) VALUES (?,?,?,?,?,?)", r)
            ids.append(cur_.lastrowid)
        c.commit()
        self.index.add(ids, fid, np.stack(vecs))

    # ------------------------------------------------------------------ speech
    def _speech(self, f) -> None:
        fid, path = f["id"], f["path"]
        pr = media.probe(path)
        if not pr.has_audio:
            self.db.x("UPDATE files SET transcribed=1, speech_model='none' WHERE id=?", (fid,))
            return
        wav = self.tmp / f"{media.file_key(path)}.wav"
        try:
            if not media.extract_audio_wav(path, wav, float(self.settings.get("max_video_seconds", 0) or 0)):
                self.db.x("UPDATE files SET transcribed=1, speech_model='none' WHERE id=?", (fid,))
                return
            langs = self.settings.get("transcribe_languages") or []
            language = langs[0] if len(langs) == 1 else None  # None = detectar automáticamente
            segs = self.speech.transcribe(wav, language=language)
            self.db.x("DELETE FROM segments WHERE file_id=?", (fid,))
            self.db.xmany("INSERT INTO segments(file_id, t_start, t_end, speaker, lang, text) VALUES (?,?,?,?,?,?)",
                          [(fid, s.start, s.end, s.speaker, s.lang, s.text) for s in segs])
            self.db.x("UPDATE files SET transcribed=1, speech_model=? WHERE id=?", (self.speech.size, fid))
        finally:
            try:
                wav.unlink(missing_ok=True)
            except Exception:
                pass
