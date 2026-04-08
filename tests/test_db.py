"""Tests for PicNote SQLite database layer."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime

import pytest

from src.db import PicNoteDB


class TestDatabaseInit:
    """Tests for database initialization."""

    def test_creates_database_file(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = PicNoteDB(db_path)
        assert os.path.exists(db_path)

    def test_creates_tables_on_first_run(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = PicNoteDB(db_path)

        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        conn.close()

        assert "processed_images" in table_names
        assert "processing_log" in table_names
        assert "schema_version" in table_names

    def test_creates_fts_index(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = PicNoteDB(db_path)

        conn = sqlite3.connect(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        conn.close()

        assert "processed_images_fts" in table_names

    def test_schema_version_recorded(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = PicNoteDB(db_path)

        conn = sqlite3.connect(db_path)
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
        conn.close()

        assert version == 1

    def test_creates_parent_directory(self, tmp_path):
        db_path = str(tmp_path / "subdir" / "deep" / "test.db")
        db = PicNoteDB(db_path)
        assert os.path.exists(db_path)

    def test_idempotent_init(self, tmp_path):
        """Creating PicNoteDB twice on same path should not error."""
        db_path = str(tmp_path / "test.db")
        db1 = PicNoteDB(db_path)
        db2 = PicNoteDB(db_path)
        # Should still work
        assert not db2.is_processed("nonexistent")


class TestInsertAndQuery:
    """Tests for inserting and querying processed images."""

    def test_insert_processed_image(self, test_db):
        row_id = test_db.insert_processed_image(
            photo_uuid="UUID-001",
            photo_path="/photos/test.jpg",
            thumbnail_path="/thumbs/test-thumb.jpg",
            classification="informational",
        )
        assert row_id > 0

    def test_query_by_uuid(self, test_db):
        test_db.insert_processed_image(
            photo_uuid="UUID-002",
            photo_path="/photos/test2.jpg",
            thumbnail_path=None,
            classification="casual",
        )
        result = test_db.get_by_uuid("UUID-002")
        assert result is not None
        assert result["photo_uuid"] == "UUID-002"
        assert result["classification"] == "casual"

    def test_query_nonexistent_uuid(self, test_db):
        result = test_db.get_by_uuid("NONEXISTENT")
        assert result is None

    def test_is_processed_true(self, test_db):
        test_db.insert_processed_image(
            photo_uuid="UUID-003",
            photo_path="/photos/test3.jpg",
            thumbnail_path=None,
            classification="informational",
        )
        assert test_db.is_processed("UUID-003") is True

    def test_is_processed_false(self, test_db):
        assert test_db.is_processed("NEVER-SEEN") is False

    def test_duplicate_uuid_raises(self, test_db):
        test_db.insert_processed_image(
            photo_uuid="UUID-DUP",
            photo_path="/photos/dup.jpg",
            thumbnail_path=None,
            classification="informational",
        )
        with pytest.raises(sqlite3.IntegrityError):
            test_db.insert_processed_image(
                photo_uuid="UUID-DUP",
                photo_path="/photos/dup2.jpg",
                thumbnail_path=None,
                classification="casual",
            )

    def test_insert_with_all_fields(self, test_db):
        row_id = test_db.insert_processed_image(
            photo_uuid="UUID-FULL",
            photo_path="/photos/full.jpg",
            thumbnail_path="/thumbs/full-thumb.jpg",
            classification="informational",
            source_type="screenshot",
            ocr_text="Hello World https://example.com",
            structured_data={"urls": ["https://example.com"]},
            ai_summary="A screenshot with a URL",
            tags=["link", "web"],
            note_path="/vault/daily/2026/04/08/hello-world.md",
            device_name="iPhone 15 Pro",
            latitude=39.9,
            longitude=116.4,
            captured_at="2026-04-08T14:30:00",
        )

        result = test_db.get_by_uuid("UUID-FULL")
        assert result["source_type"] == "screenshot"
        assert result["ocr_text"] == "Hello World https://example.com"
        assert json.loads(result["structured_data"]) == {"urls": ["https://example.com"]}
        assert result["ai_summary"] == "A screenshot with a URL"
        assert json.loads(result["tags"]) == ["link", "web"]
        assert result["note_path"] == "/vault/daily/2026/04/08/hello-world.md"
        assert result["device_name"] == "iPhone 15 Pro"
        assert result["latitude"] == 39.9
        assert result["longitude"] == 116.4

    def test_tags_stored_as_json_array(self, test_db):
        """Tags should be stored as JSON array, not comma-separated."""
        test_db.insert_processed_image(
            photo_uuid="UUID-JSONTAG",
            photo_path="/photos/tag.jpg",
            thumbnail_path=None,
            classification="informational",
            tags=["tag,with,commas", "normal"],
        )
        result = test_db.get_by_uuid("UUID-JSONTAG")
        parsed = json.loads(result["tags"])
        assert parsed == ["tag,with,commas", "normal"]

    def test_tags_none_stored_as_null(self, test_db):
        """No tags should store None/null."""
        test_db.insert_processed_image(
            photo_uuid="UUID-NOTAG",
            photo_path="/photos/notag.jpg",
            thumbnail_path=None,
            classification="informational",
            tags=None,
        )
        result = test_db.get_by_uuid("UUID-NOTAG")
        assert result["tags"] is None

    def test_tags_empty_list_stored_as_null(self, test_db):
        """Empty tag list should be stored as null (empty list is falsy)."""
        test_db.insert_processed_image(
            photo_uuid="UUID-EMPTYTAG",
            photo_path="/photos/empty.jpg",
            thumbnail_path=None,
            classification="informational",
            tags=[],
        )
        result = test_db.get_by_uuid("UUID-EMPTYTAG")
        assert result["tags"] is None

    def test_get_since_timestamp(self, test_db):
        test_db.insert_processed_image(
            photo_uuid="UUID-OLD",
            photo_path="/photos/old.jpg",
            thumbnail_path=None,
            classification="informational",
        )
        # Insert a second one (slightly after)
        test_db.insert_processed_image(
            photo_uuid="UUID-NEW",
            photo_path="/photos/new.jpg",
            thumbnail_path=None,
            classification="informational",
        )

        # Query for all since epoch
        results = test_db.get_since("2000-01-01T00:00:00")
        assert len(results) >= 2


class TestSearch:
    """Tests for full-text search."""

    def test_search_by_ocr_text(self, test_db):
        test_db.insert_processed_image(
            photo_uuid="UUID-SEARCH1",
            photo_path="/photos/s1.jpg",
            thumbnail_path=None,
            classification="informational",
            ocr_text="Important meeting notes about machine learning",
        )
        results = test_db.search("machine learning")
        assert len(results) >= 1
        assert results[0]["photo_uuid"] == "UUID-SEARCH1"

    def test_search_by_tag(self, test_db):
        test_db.insert_processed_image(
            photo_uuid="UUID-SEARCH2",
            photo_path="/photos/s2.jpg",
            thumbnail_path=None,
            classification="informational",
            tags=["restaurant", "food"],
        )
        results = test_db.search("restaurant")
        assert len(results) >= 1

    def test_search_by_summary(self, test_db):
        test_db.insert_processed_image(
            photo_uuid="UUID-SEARCH3",
            photo_path="/photos/s3.jpg",
            thumbnail_path=None,
            classification="informational",
            ai_summary="Receipt from Blue Bottle Coffee for $14.50",
        )
        results = test_db.search("Blue Bottle")
        assert len(results) >= 1

    def test_search_chinese_text(self, test_db):
        """FTS5 default tokenizer has limited CJK support.
        Search for an ASCII tag added alongside Chinese text."""
        test_db.insert_processed_image(
            photo_uuid="UUID-CHINESE",
            photo_path="/photos/cn.jpg",
            thumbnail_path=None,
            classification="informational",
            ocr_text="今天下午三点开会讨论项目进度",
            tags=["meeting", "chinese"],
        )
        results = test_db.search("meeting")
        assert len(results) >= 1

    def test_search_no_results(self, test_db):
        results = test_db.search("xyznonexistentquery")
        assert results == []

    def test_search_respects_limit(self, test_db):
        for i in range(10):
            test_db.insert_processed_image(
                photo_uuid=f"UUID-LIMIT-{i}",
                photo_path=f"/photos/l{i}.jpg",
                thumbnail_path=None,
                classification="informational",
                ocr_text=f"Common search term in document {i}",
            )
        results = test_db.search("common search term", limit=3)
        assert len(results) == 3


class TestProcessingLog:
    """Tests for the processing log."""

    def test_log_processing_step(self, test_db):
        test_db.log_processing(
            photo_uuid="UUID-LOG",
            stage="classification",
            status="informational",
            duration_ms=150,
        )
        # Should not raise

    def test_log_with_error(self, test_db):
        test_db.log_processing(
            photo_uuid="UUID-ERR",
            stage="analysis",
            status="error",
            error_message="Claude CLI timeout",
            duration_ms=30000,
        )


class TestStats:
    """Tests for processing statistics."""

    def test_stats_empty_db(self, test_db):
        stats = test_db.get_stats()
        assert stats["total"] == 0
        assert stats["informational"] == 0
        assert stats["casual"] == 0

    def test_stats_counts(self, test_db):
        test_db.insert_processed_image(
            photo_uuid="S1", photo_path="/p1", thumbnail_path=None,
            classification="informational",
        )
        test_db.insert_processed_image(
            photo_uuid="S2", photo_path="/p2", thumbnail_path=None,
            classification="casual",
        )
        test_db.insert_processed_image(
            photo_uuid="S3", photo_path="/p3", thumbnail_path=None,
            classification="informational",
        )
        stats = test_db.get_stats()
        assert stats["total"] == 3
        assert stats["informational"] == 2
        assert stats["casual"] == 1
