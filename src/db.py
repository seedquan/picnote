"""PicNote SQLite database layer for tracking processed images."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime


SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS processed_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_uuid TEXT UNIQUE NOT NULL,
    photo_path TEXT,
    thumbnail_path TEXT,
    classification TEXT NOT NULL,
    source_type TEXT,
    ocr_text TEXT,
    structured_data TEXT,
    ai_summary TEXT,
    tags TEXT,
    note_path TEXT,
    device_name TEXT,
    latitude REAL,
    longitude REAL,
    captured_at TEXT,
    processed_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS processed_images_fts USING fts5(
    ocr_text,
    ai_summary,
    tags,
    content=processed_images,
    content_rowid=id
);

CREATE TABLE IF NOT EXISTS processing_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_uuid TEXT,
    stage TEXT,
    status TEXT,
    error_message TEXT,
    duration_ms INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class PicNoteDB:
    """SQLite database for PicNote processed images and search index."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        conn = self._connect()
        try:
            # Check if schema exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            if cursor.fetchone() is None:
                conn.executescript(SCHEMA_SQL)
                # Create triggers for FTS sync (executescript commits automatically)
                conn.executescript("""
                    CREATE TRIGGER IF NOT EXISTS processed_images_ai AFTER INSERT ON processed_images BEGIN
                        INSERT INTO processed_images_fts(rowid, ocr_text, ai_summary, tags)
                        VALUES (new.id, new.ocr_text, new.ai_summary, new.tags);
                    END;

                    CREATE TRIGGER IF NOT EXISTS processed_images_ad AFTER DELETE ON processed_images BEGIN
                        INSERT INTO processed_images_fts(processed_images_fts, rowid, ocr_text, ai_summary, tags)
                        VALUES('delete', old.id, old.ocr_text, old.ai_summary, old.tags);
                    END;

                    CREATE TRIGGER IF NOT EXISTS processed_images_au AFTER UPDATE ON processed_images BEGIN
                        INSERT INTO processed_images_fts(processed_images_fts, rowid, ocr_text, ai_summary, tags)
                        VALUES('delete', old.id, old.ocr_text, old.ai_summary, old.tags);
                        INSERT INTO processed_images_fts(rowid, ocr_text, ai_summary, tags)
                        VALUES (new.id, new.ocr_text, new.ai_summary, new.tags);
                    END;
                """)
                conn.execute(
                    "INSERT OR REPLACE INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )
                conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        """Create a new database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def is_processed(self, photo_uuid: str) -> bool:
        """Check if a photo has already been processed."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT 1 FROM processed_images WHERE photo_uuid = ?",
                (photo_uuid,),
            )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def insert_processed_image(
        self,
        photo_uuid: str,
        photo_path: str,
        thumbnail_path: str | None,
        classification: str,
        source_type: str | None = None,
        ocr_text: str | None = None,
        structured_data: dict | None = None,
        ai_summary: str | None = None,
        tags: list[str] | None = None,
        note_path: str | None = None,
        device_name: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        captured_at: str | None = None,
    ) -> int:
        """Insert a processed image record. Returns the row ID."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                """INSERT INTO processed_images
                (photo_uuid, photo_path, thumbnail_path, classification, source_type,
                 ocr_text, structured_data, ai_summary, tags, note_path,
                 device_name, latitude, longitude, captured_at, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    photo_uuid,
                    photo_path,
                    thumbnail_path,
                    classification,
                    source_type,
                    ocr_text,
                    json.dumps(structured_data) if structured_data else None,
                    ai_summary,
                    json.dumps(tags) if tags else None,
                    note_path,
                    device_name,
                    latitude,
                    longitude,
                    captured_at,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_by_uuid(self, photo_uuid: str) -> dict | None:
        """Get a processed image record by photo UUID."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT * FROM processed_images WHERE photo_uuid = ?",
                (photo_uuid,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_since(self, since: str) -> list[dict]:
        """Get all processed images since a given ISO timestamp."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT * FROM processed_images WHERE processed_at > ? ORDER BY processed_at",
                (since,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def search(self, query: str, limit: int = 20) -> list[dict]:
        """Full-text search across OCR text, summaries, and tags."""
        conn = self._connect()
        try:
            # Quote the query to handle special FTS5 characters (@, -, etc.)
            safe_query = '"' + query.replace('"', '""') + '"'
            cursor = conn.execute(
                """SELECT p.*, rank
                FROM processed_images_fts fts
                JOIN processed_images p ON p.id = fts.rowid
                WHERE processed_images_fts MATCH ?
                ORDER BY rank
                LIMIT ?""",
                (safe_query, limit),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def log_processing(
        self,
        photo_uuid: str,
        stage: str,
        status: str,
        error_message: str | None = None,
        duration_ms: int | None = None,
    ):
        """Log a processing step."""
        conn = self._connect()
        try:
            conn.execute(
                """INSERT INTO processing_log
                (photo_uuid, stage, status, error_message, duration_ms)
                VALUES (?, ?, ?, ?, ?)""",
                (photo_uuid, stage, status, error_message, duration_ms),
            )
            conn.commit()
        finally:
            conn.close()

    def get_stats(self) -> dict:
        """Get processing statistics."""
        conn = self._connect()
        try:
            total = conn.execute("SELECT COUNT(*) FROM processed_images").fetchone()[0]
            informational = conn.execute(
                "SELECT COUNT(*) FROM processed_images WHERE classification = 'informational'"
            ).fetchone()[0]
            casual = conn.execute(
                "SELECT COUNT(*) FROM processed_images WHERE classification = 'casual'"
            ).fetchone()[0]
            return {
                "total": total,
                "informational": informational,
                "casual": casual,
            }
        finally:
            conn.close()
