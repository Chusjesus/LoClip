"""Base de datos SQLite de LoClip (archivos, momentos, transcripciones, colecciones, conceptos)."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from .config import db_path

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'local',     -- local | nas | cloud
  enabled INTEGER NOT NULL DEFAULT 1,     -- incluir en búsquedas
  read_only INTEGER NOT NULL DEFAULT 1,   -- siempre 1: LoClip nunca escribe en las fuentes
  created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  path TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  ext TEXT NOT NULL,
  kind TEXT NOT NULL,                     -- video | image | audio
  size INTEGER NOT NULL DEFAULT 0,
  mtime REAL NOT NULL DEFAULT 0,
  duration REAL NOT NULL DEFAULT 0,
  width INTEGER DEFAULT 0,
  height INTEGER DEFAULT 0,
  fps REAL DEFAULT 0,
  codec TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending', -- pending | visual | done | error | skipped
  error TEXT DEFAULT '',
  visual_model TEXT DEFAULT '',
  speech_model TEXT DEFAULT '',
  transcribed INTEGER NOT NULL DEFAULT 0,
  indexed_at REAL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_files_source ON files(source_id);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);

-- Un "momento" es un tramo visualmente homogéneo de un video (o una imagen completa).
CREATE TABLE IF NOT EXISTS moments (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  t_start REAL NOT NULL,
  t_end REAL NOT NULL,
  thumb TEXT NOT NULL DEFAULT '',
  embedding BLOB NOT NULL,                -- float16, normalizado
  n_frames INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_moments_file ON moments(file_id);

CREATE TABLE IF NOT EXISTS segments (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  t_start REAL NOT NULL,
  t_end REAL NOT NULL,
  speaker TEXT DEFAULT '',
  lang TEXT DEFAULT '',
  text TEXT NOT NULL,
  edited INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_segments_file ON segments(file_id);

CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(text, content='segments', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
  INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
  INSERT INTO segments_fts(segments_fts, rowid, text) VALUES('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_au AFTER UPDATE ON segments BEGIN
  INSERT INTO segments_fts(segments_fts, rowid, text) VALUES('delete', old.id, old.text);
  INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;

-- Búsqueda por nombre de archivo / ruta / palabras clave del usuario
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(name, path, keywords, tokenize='unicode61 remove_diacritics 2');

CREATE TABLE IF NOT EXISTS file_keywords (
  file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
  keywords TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS collections (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  color TEXT DEFAULT '',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_items (
  collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  moment_id INTEGER NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
  added_at REAL NOT NULL,
  PRIMARY KEY (collection_id, moment_id)
);

-- "Conceptos": el usuario enseña algo con ejemplos (momentos) y luego busca por el nombre.
CREATE TABLE IF NOT EXISTS concepts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  visual_model TEXT NOT NULL,
  embedding BLOB NOT NULL,
  n_examples INTEGER NOT NULL DEFAULT 0,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS concept_examples (
  concept_id INTEGER NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
  moment_id INTEGER NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
  positive INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (concept_id, moment_id)
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class DB:
    def __init__(self, path: Path | None = None):
        self.path = path or db_path()
        self._local = threading.local()
        with self.conn() as c:
            c.executescript(SCHEMA)

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            self._local.conn = c
        return c

    # ---- helpers -------------------------------------------------------
    def q(self, sql: str, args=()) -> list[sqlite3.Row]:
        return self.conn().execute(sql, args).fetchall()

    def one(self, sql: str, args=()):
        return self.conn().execute(sql, args).fetchone()

    def x(self, sql: str, args=()) -> int:
        c = self.conn()
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid

    def xmany(self, sql: str, rows) -> None:
        c = self.conn()
        c.executemany(sql, rows)
        c.commit()

    def now(self) -> float:
        return time.time()

    def reindex_file_fts(self, file_id: int) -> None:
        f = self.one("SELECT name, path FROM files WHERE id=?", (file_id,))
        if not f:
            return
        kw = self.one("SELECT keywords FROM file_keywords WHERE file_id=?", (file_id,))
        c = self.conn()
        c.execute("DELETE FROM files_fts WHERE rowid=?", (file_id,))
        # Separar el nombre en palabras (guiones, guiones bajos, puntos) para que "DIA2_cocina-01" encuentre "cocina".
        import re
        name_words = " ".join(re.split(r"[\s_\-\.\(\)\[\]]+", f["name"]))
        path_words = " ".join(re.split(r"[\\/\s_\-\.\(\)\[\]]+", f["path"]))
        c.execute("INSERT INTO files_fts(rowid, name, path, keywords) VALUES (?,?,?,?)",
                  (file_id, name_words, path_words, kw["keywords"] if kw else ""))
        c.commit()
