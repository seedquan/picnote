"""Tests for PicNote Photos.sqlite reader (watcher)."""

import os
import sqlite3

import pytest

from src.watcher import (
    PhotoAsset,
    apple_timestamp_to_datetime,
    get_new_photos,
    open_photos_db_readonly,
)
from tests.conftest import add_mock_photo


class TestAppleTimestamp:
    """Tests for Apple Core Data timestamp conversion."""

    def test_convert_known_timestamp(self):
        """April 8, 2026 14:30 UTC in Apple time."""
        # Apple epoch is 2001-01-01, so 2026-04-08 is about 797956200 seconds later
        dt = apple_timestamp_to_datetime(797956200.0)
        assert dt is not None
        assert dt.year == 2026

    def test_none_timestamp(self):
        assert apple_timestamp_to_datetime(None) is None

    def test_zero_timestamp(self):
        """Zero should return Apple epoch (2001-01-01)."""
        dt = apple_timestamp_to_datetime(0.0)
        assert dt.year == 2001
        assert dt.month == 1
        assert dt.day == 1


class TestOpenPhotosDBReadonly:
    """Tests for read-only database access."""

    def test_opens_existing_database(self, mock_photos_db):
        conn = open_photos_db_readonly(mock_photos_db)
        assert conn is not None
        conn.close()

    def test_raises_on_missing_database(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            open_photos_db_readonly(str(tmp_path / "nonexistent.photoslibrary"))

    def test_readonly_mode_prevents_writes(self, mock_photos_db):
        """CRITICAL: Verify that the database is opened in read-only mode."""
        conn = open_photos_db_readonly(mock_photos_db)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO ZASSET (ZUUID, ZFILENAME) VALUES ('test', 'test.jpg')")
        conn.close()

    def test_readonly_mode_prevents_table_creation(self, mock_photos_db):
        """CRITICAL: Cannot create tables in read-only mode."""
        conn = open_photos_db_readonly(mock_photos_db)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE evil (id INTEGER)")
        conn.close()

    def test_readonly_mode_prevents_deletes(self, mock_photos_db):
        """CRITICAL: Cannot delete data in read-only mode."""
        # First add some data
        db_path = os.path.join(mock_photos_db, "database", "Photos.sqlite")
        write_conn = sqlite3.connect(db_path)
        write_conn.execute(
            "INSERT INTO ZASSET (ZUUID, ZFILENAME, ZTRASHEDSTATE) VALUES ('del-test', 'test.jpg', 0)"
        )
        write_conn.commit()
        write_conn.close()

        # Now try to delete via read-only connection
        conn = open_photos_db_readonly(mock_photos_db)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM ZASSET WHERE ZUUID = 'del-test'")
        conn.close()


class TestGetNewPhotos:
    """Tests for querying new photos from Photos.sqlite."""

    def test_get_photos_returns_assets(self, mock_photos_db):
        add_mock_photo(mock_photos_db, "UUID-1", "photo1.jpg", timestamp=765432100.0)
        add_mock_photo(mock_photos_db, "UUID-2", "photo2.jpg", timestamp=765432200.0)

        assets = get_new_photos(mock_photos_db)
        assert len(assets) == 2
        uuids = {a.uuid for a in assets}
        assert "UUID-1" in uuids
        assert "UUID-2" in uuids

    def test_resolves_file_path(self, mock_photos_db):
        add_mock_photo(mock_photos_db, "UUID-PATH", "photo.jpg", directory="E")

        assets = get_new_photos(mock_photos_db)
        assert len(assets) == 1
        expected = os.path.join(mock_photos_db, "originals", "E", "photo.jpg")
        assert assets[0].file_path == expected

    def test_detects_screenshot_flag(self, mock_photos_db):
        add_mock_photo(mock_photos_db, "UUID-SS", "screenshot.png", is_screenshot=1)
        add_mock_photo(mock_photos_db, "UUID-PH", "photo.jpg", is_screenshot=0)

        assets = get_new_photos(mock_photos_db)
        ss = next(a for a in assets if a.uuid == "UUID-SS")
        ph = next(a for a in assets if a.uuid == "UUID-PH")
        assert ss.is_screenshot is True
        assert ph.is_screenshot is False

    def test_detects_text_content(self, mock_photos_db):
        add_mock_photo(mock_photos_db, "UUID-TXT", "doc.jpg", has_ocr=1)
        add_mock_photo(mock_photos_db, "UUID-NOTXT", "selfie.jpg", has_ocr=0)

        assets = get_new_photos(mock_photos_db)
        txt = next(a for a in assets if a.uuid == "UUID-TXT")
        notxt = next(a for a in assets if a.uuid == "UUID-NOTXT")
        assert txt.has_text is True
        assert notxt.has_text is False

    def test_counts_faces(self, mock_photos_db):
        add_mock_photo(mock_photos_db, "UUID-FACES", "group.jpg", face_count=3)
        add_mock_photo(mock_photos_db, "UUID-NOFACE", "landscape.jpg", face_count=0)

        assets = get_new_photos(mock_photos_db)
        faces = next(a for a in assets if a.uuid == "UUID-FACES")
        noface = next(a for a in assets if a.uuid == "UUID-NOFACE")
        assert faces.face_count == 3
        assert noface.face_count == 0

    def test_since_timestamp_filter(self, mock_photos_db):
        add_mock_photo(mock_photos_db, "UUID-OLD", "old.jpg", timestamp=100.0)
        add_mock_photo(mock_photos_db, "UUID-NEW", "new.jpg", timestamp=200.0)

        assets = get_new_photos(mock_photos_db, since_timestamp=150.0)
        assert len(assets) == 1
        assert assets[0].uuid == "UUID-NEW"

    def test_skips_trashed_photos(self, mock_photos_db):
        add_mock_photo(mock_photos_db, "UUID-ACTIVE", "active.jpg", trashed=0)
        add_mock_photo(mock_photos_db, "UUID-TRASHED", "trashed.jpg", trashed=1)

        assets = get_new_photos(mock_photos_db)
        uuids = {a.uuid for a in assets}
        assert "UUID-ACTIVE" in uuids
        assert "UUID-TRASHED" not in uuids

    def test_limit_parameter(self, mock_photos_db):
        for i in range(10):
            add_mock_photo(mock_photos_db, f"UUID-LIM-{i}", f"photo{i}.jpg",
                           timestamp=765432100.0 + i)

        assets = get_new_photos(mock_photos_db, limit=3)
        assert len(assets) == 3

    def test_handles_missing_directory(self, mock_photos_db):
        """Photos with empty directory should still work."""
        db_path = os.path.join(mock_photos_db, "database", "Photos.sqlite")
        conn = sqlite3.connect(db_path)
        conn.execute(
            """INSERT INTO ZASSET (ZUUID, ZFILENAME, ZDIRECTORY, ZDATECREATED,
                ZWIDTH, ZHEIGHT, ZTRASHEDSTATE)
            VALUES (?, ?, NULL, ?, ?, ?, ?)""",
            ("UUID-NODIR", "nodir.jpg", 765432100.0, 640, 480, 0),
        )
        pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO ZADDITIONALASSETATTRIBUTES (ZASSET) VALUES (?)", (pk,)
        )
        conn.commit()
        conn.close()

        assets = get_new_photos(mock_photos_db)
        nodir = next(a for a in assets if a.uuid == "UUID-NODIR")
        assert nodir.directory == ""

    def test_path_traversal_filtered_out(self, mock_photos_db):
        """Assets with directory traversal paths should be silently skipped."""
        db_path = os.path.join(mock_photos_db, "database", "Photos.sqlite")
        conn = sqlite3.connect(db_path)
        # Insert an asset with a traversal path in the directory
        conn.execute(
            """INSERT INTO ZASSET (ZUUID, ZFILENAME, ZDIRECTORY, ZDATECREATED,
                ZWIDTH, ZHEIGHT, ZTRASHEDSTATE)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("UUID-TRAVERSAL", "evil.jpg", "../../etc", 765432100.0, 640, 480, 0),
        )
        pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO ZADDITIONALASSETATTRIBUTES (ZASSET) VALUES (?)", (pk,)
        )
        # Also add a normal asset
        conn.execute(
            """INSERT INTO ZASSET (ZUUID, ZFILENAME, ZDIRECTORY, ZDATECREATED,
                ZWIDTH, ZHEIGHT, ZTRASHEDSTATE)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("UUID-SAFE", "safe.jpg", "A", 765432200.0, 640, 480, 0),
        )
        pk2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO ZADDITIONALASSETATTRIBUTES (ZASSET) VALUES (?)", (pk2,)
        )
        conn.commit()
        conn.close()

        # Create only the safe image file
        safe_dir = os.path.join(mock_photos_db, "originals", "A")
        os.makedirs(safe_dir, exist_ok=True)
        from tests.conftest import _create_test_image
        _create_test_image(os.path.join(safe_dir, "safe.jpg"), 640, 480)

        assets = get_new_photos(mock_photos_db)
        uuids = {a.uuid for a in assets}
        # Traversal path should be filtered out
        assert "UUID-TRAVERSAL" not in uuids
        assert "UUID-SAFE" in uuids

    def test_absolute_path_in_filename_filtered(self, mock_photos_db):
        """Absolute path in filename should be caught by traversal check."""
        db_path = os.path.join(mock_photos_db, "database", "Photos.sqlite")
        conn = sqlite3.connect(db_path)
        conn.execute(
            """INSERT INTO ZASSET (ZUUID, ZFILENAME, ZDIRECTORY, ZDATECREATED,
                ZWIDTH, ZHEIGHT, ZTRASHEDSTATE)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("UUID-ABSPATH", "/etc/passwd", "A", 765432100.0, 640, 480, 0),
        )
        pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO ZADDITIONALASSETATTRIBUTES (ZASSET) VALUES (?)", (pk,)
        )
        conn.commit()
        conn.close()

        assets = get_new_photos(mock_photos_db)
        uuids = {a.uuid for a in assets}
        assert "UUID-ABSPATH" not in uuids

    def test_handles_locked_database(self, mock_photos_db):
        """Should handle Photos.sqlite being busy/locked gracefully."""
        # Lock the database with a write transaction
        db_path = os.path.join(mock_photos_db, "database", "Photos.sqlite")
        lock_conn = sqlite3.connect(db_path)
        lock_conn.execute("BEGIN EXCLUSIVE")

        # Reading should still work in WAL mode or raise a clear error
        try:
            assets = get_new_photos(mock_photos_db)
            # If it works, that's fine (WAL mode)
        except sqlite3.OperationalError as e:
            assert "locked" in str(e).lower() or "readonly" in str(e).lower()
        finally:
            lock_conn.rollback()
            lock_conn.close()
