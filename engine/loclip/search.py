"""Índice vectorial en memoria y búsqueda híbrida (visual + nombre/keywords + voz)."""
from __future__ import annotations

import os
import re
import threading
import time

import numpy as np

from .db import DB
from .embeddings import from_blob


class VectorIndex:
    """Matriz de embeddings de todos los momentos, en RAM. Búsqueda = un producto de matrices."""

    def __init__(self, db: DB, dim: int, model_name: str):
        self.db, self.dim, self.model_name = db, dim, model_name
        self.lock = threading.Lock()
        self.ids = np.zeros((0,), dtype=np.int64)
        self.file_ids = np.zeros((0,), dtype=np.int64)
        self.mat = np.zeros((0, dim), dtype=np.float32)
        self.loaded_at = 0.0
        self.reload()

    def reload(self) -> None:
        rows = self.db.q(
            "SELECT m.id, m.file_id, m.embedding FROM moments m JOIN files f ON f.id=m.file_id WHERE f.visual_model=?",
            (self.model_name,),
        )
        # Los archivos de solo audio tienen un vector de ceros: no se incluyen en la búsqueda visual.
        rows = [r for r in rows if np.any(np.frombuffer(r["embedding"], dtype=np.float16))]
        ids = np.array([r["id"] for r in rows], dtype=np.int64)
        fids = np.array([r["file_id"] for r in rows], dtype=np.int64)
        if rows:
            mat = np.stack([from_blob(r["embedding"], self.dim)[0] for r in rows]).astype(np.float32)
        else:
            mat = np.zeros((0, self.dim), dtype=np.float32)
        with self.lock:
            self.ids, self.file_ids, self.mat, self.loaded_at = ids, fids, mat, time.time()

    def add(self, moment_ids: list[int], file_id: int, vecs: np.ndarray) -> None:
        with self.lock:
            self.ids = np.concatenate([self.ids, np.asarray(moment_ids, dtype=np.int64)])
            self.file_ids = np.concatenate([self.file_ids, np.full(len(moment_ids), file_id, dtype=np.int64)])
            self.mat = np.concatenate([self.mat, vecs.astype(np.float32)])

    def remove_file(self, file_id: int) -> None:
        with self.lock:
            keep = self.file_ids != file_id
            self.ids, self.file_ids, self.mat = self.ids[keep], self.file_ids[keep], self.mat[keep]

    def vec(self, moment_id: int) -> np.ndarray | None:
        with self.lock:
            idx = np.nonzero(self.ids == moment_id)[0]
            return self.mat[idx[0]].copy() if len(idx) else None

    def query(self, q: np.ndarray, allowed_files: np.ndarray | None, k: int = 200) -> list[tuple[int, int, float]]:
        with self.lock:
            if len(self.ids) == 0:
                return []
            scores = self.mat @ q.astype(np.float32)
            if allowed_files is not None:
                mask = np.isin(self.file_ids, allowed_files)
                scores = np.where(mask, scores, -1.0)
            k = min(k, len(scores))
            top = np.argpartition(-scores, k - 1)[:k]
            top = top[np.argsort(-scores[top])]
            return [(int(self.ids[i]), int(self.file_ids[i]), float(scores[i])) for i in top if scores[i] > -1.0]


def fts_query(text: str, any_word: bool = False) -> str:
    """Convierte texto libre en una consulta FTS5 segura (cada palabra con prefijo).

    any_word=True relaja la búsqueda a "cualquiera de las palabras" (se usa como
    segundo intento cuando la frase exacta no aparece en un mismo segmento).
    """
    words = [w for w in re.split(r"[^\w]+", text, flags=re.UNICODE) if len(w) >= 2]
    if not words:
        return ""
    if any_word:
        words = [w for w in words if len(w) >= 3] or words
    return (" OR " if any_word else " ").join(f'"{w}"*' for w in words)


class Searcher:
    def __init__(self, db: DB):
        self.db = db
        self._avail_cache: dict[str, tuple[float, bool]] = {}

    # --- disponibilidad (online/offline) ---------------------------------
    def available(self, path: str) -> bool:
        now = time.time()
        c = self._avail_cache.get(path)
        if c and now - c[0] < 30:
            return c[1]
        ok = os.path.exists(path)
        self._avail_cache[path] = (now, ok)
        return ok

    def allowed_file_ids(self, source_ids: list[int] | None = None, kinds: list[str] | None = None) -> np.ndarray:
        sql = "SELECT f.id FROM files f JOIN sources s ON s.id=f.source_id WHERE s.enabled=1"
        args: list = []
        if source_ids:
            sql += f" AND s.id IN ({','.join('?' * len(source_ids))})"
            args += source_ids
        if kinds:
            sql += f" AND f.kind IN ({','.join('?' * len(kinds))})"
            args += kinds
        return np.array([r["id"] for r in self.db.q(sql, args)], dtype=np.int64)

    # --- resultados --------------------------------------------------------
    def moment_rows(self, moment_ids: list[int]) -> dict[int, dict]:
        if not moment_ids:
            return {}
        out = {}
        for i in range(0, len(moment_ids), 500):
            chunk = moment_ids[i:i + 500]
            rows = self.db.q(
                f"""SELECT m.id, m.file_id, m.t_start, m.t_end, m.thumb, f.path, f.name, f.kind, f.duration, f.fps,
                           f.width, f.height, f.source_id
                    FROM moments m JOIN files f ON f.id=m.file_id WHERE m.id IN ({','.join('?' * len(chunk))})""",
                chunk,
            )
            for r in rows:
                out[r["id"]] = dict(r)
        return out

    def format(self, r: dict, score: float, why: str) -> dict:
        return {
            "moment_id": r["id"], "file_id": r["file_id"], "path": r["path"], "name": r["name"], "kind": r["kind"],
            "t_start": r["t_start"], "t_end": r["t_end"], "thumb": r["thumb"], "duration": r["duration"],
            "fps": r["fps"], "width": r["width"], "height": r["height"], "source_id": r["source_id"],
            "score": round(float(score), 4), "why": why, "available": self.available(r["path"]),
        }

    def search_visual(self, index: VectorIndex, qvec: np.ndarray, allowed: np.ndarray, k: int, per_file: int = 0) -> list[dict]:
        hits = index.query(qvec, allowed, k=k * 3 if per_file else k)
        rows = self.moment_rows([h[0] for h in hits])
        out, per = [], {}
        for mid, fid, score in hits:
            if per_file:
                per[fid] = per.get(fid, 0) + 1
                if per[fid] > per_file:
                    continue
            if mid in rows:
                out.append(self.format(rows[mid], score, "visual"))
            if len(out) >= k:
                break
        return out

    def search_files(self, text: str, allowed: np.ndarray, k: int) -> list[dict]:
        q = fts_query(text)
        if not q:
            return []
        rows = self.db.q(
            "SELECT rowid AS file_id, bm25(files_fts, 3.0, 1.0, 2.0) AS rank FROM files_fts WHERE files_fts MATCH ? ORDER BY rank LIMIT ?",
            (q, k * 2),
        )
        allowed_set = set(allowed.tolist())
        out = []
        for r in rows:
            if r["file_id"] not in allowed_set:
                continue
            m = self.db.one("SELECT id FROM moments WHERE file_id=? ORDER BY t_start LIMIT 1", (r["file_id"],))
            if not m:
                continue
            mr = self.moment_rows([m["id"]]).get(m["id"])
            if mr:
                out.append(self.format(mr, 1.0 / (1.0 + abs(r["rank"])), "name"))
            if len(out) >= k:
                break
        return out

    def search_speech(self, text: str, allowed: np.ndarray, k: int) -> list[dict]:
        q = fts_query(text)
        if not q:
            return []
        sql = """SELECT s.id, s.file_id, s.t_start, s.t_end, s.text, s.speaker, bm25(segments_fts) AS rank
                 FROM segments_fts JOIN segments s ON s.id = segments_fts.rowid
                 WHERE segments_fts MATCH ? ORDER BY rank LIMIT ?"""
        rows = self.db.q(sql, (q, k * 2))
        if not rows:
            q2 = fts_query(text, any_word=True)
            if q2 and q2 != q:
                rows = self.db.q(sql, (q2, k * 2))
        allowed_set = set(allowed.tolist())
        out = []
        for r in rows:
            if r["file_id"] not in allowed_set:
                continue
            m = self.db.one(
                "SELECT id FROM moments WHERE file_id=? AND t_start<=? ORDER BY t_start DESC LIMIT 1",
                (r["file_id"], r["t_start"]),
            ) or self.db.one("SELECT id FROM moments WHERE file_id=? ORDER BY t_start LIMIT 1", (r["file_id"],))
            f = self.db.one("SELECT * FROM files WHERE id=?", (r["file_id"],))
            if not f:
                continue
            base = {"id": m["id"] if m else 0, "file_id": f["id"], "t_start": r["t_start"], "t_end": r["t_end"],
                    "thumb": "", "path": f["path"], "name": f["name"], "kind": f["kind"], "duration": f["duration"],
                    "fps": f["fps"], "width": f["width"], "height": f["height"], "source_id": f["source_id"]}
            if m:
                mr = self.moment_rows([m["id"]]).get(m["id"])
                if mr:
                    base["thumb"] = mr["thumb"]
            item = self.format(base, 1.0 / (1.0 + abs(r["rank"])), "speech")
            item["text"] = r["text"]
            item["speaker"] = r["speaker"]
            item["segment_id"] = r["id"]
            out.append(item)
            if len(out) >= k:
                break
        return out
