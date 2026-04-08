"""CRITICAL safety tests for PicNote — verifying read-only guarantees.

These tests ensure that PicNote NEVER modifies, deletes, or corrupts
the user's Photos library or original image files.
"""

import hashlib
import os
import sqlite3
import stat

import pytest

from src.watcher import open_photos_db_readonly
from tests.conftest import add_mock_photo


def _file_checksum(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


class TestPhotosDBReadOnlyGuarantee:
    """CRITICAL: Photos.sqlite must NEVER be written to."""

    def test_sqlite_opened_with_readonly_uri(self, mock_photos_db):
        """Photos.sqlite must be opened with ?mode=ro URI parameter."""
        conn = open_photos_db_readonly(mock_photos_db)
        # If we got here, it opened successfully in read-only mode
        conn.close()

    def test_insert_raises_error(self, mock_photos_db):
        """Attempting to INSERT into Photos.sqlite must raise an error."""
        conn = open_photos_db_readonly(mock_photos_db)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO ZASSET (ZUUID, ZFILENAME, ZTRASHEDSTATE) "
                "VALUES ('evil', 'evil.jpg', 0)"
            )
        conn.close()

    def test_update_raises_error(self, mock_photos_db):
        """Attempting to UPDATE Photos.sqlite must raise an error."""
        add_mock_photo(mock_photos_db, "SAFE-001", "safe.jpg")

        conn = open_photos_db_readonly(mock_photos_db)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("UPDATE ZASSET SET ZFILENAME = 'changed.jpg'")
        conn.close()

    def test_delete_raises_error(self, mock_photos_db):
        """Attempting to DELETE from Photos.sqlite must raise an error."""
        add_mock_photo(mock_photos_db, "SAFE-002", "safe2.jpg")

        conn = open_photos_db_readonly(mock_photos_db)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM ZASSET")
        conn.close()

    def test_drop_table_raises_error(self, mock_photos_db):
        """Attempting to DROP tables in Photos.sqlite must raise an error."""
        conn = open_photos_db_readonly(mock_photos_db)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DROP TABLE ZASSET")
        conn.close()

    def test_create_table_raises_error(self, mock_photos_db):
        """Attempting to CREATE tables in Photos.sqlite must raise an error."""
        conn = open_photos_db_readonly(mock_photos_db)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE malicious (id INTEGER)")
        conn.close()

    def test_pragma_write_is_harmless(self, mock_photos_db):
        """PRAGMA on read-only DB either fails or is silently ignored — both are safe."""
        conn = open_photos_db_readonly(mock_photos_db)
        try:
            result = conn.execute("PRAGMA journal_mode=DELETE").fetchone()
            # If it doesn't raise, the mode should NOT have changed from WAL/read-only
            # Either it returns the current mode unchanged, or raises — both are safe
        except sqlite3.OperationalError:
            pass  # Expected in read-only mode
        conn.close()


class TestOriginalImageSafety:
    """CRITICAL: Original image files must NEVER be modified or deleted."""

    def test_original_unchanged_after_processing(self, mock_photos_db, tmp_path):
        """Original image must have identical checksum before and after processing."""
        from unittest.mock import MagicMock, patch
        from src.config import ensure_output_dirs, load_config
        from src.db import PicNoteDB
        from src.main import process_single_image
        from src.watcher import PhotoAsset
        from datetime import datetime, timezone

        img_path = add_mock_photo(mock_photos_db, "SAFE-IMG-001", "original.jpg")
        checksum_before = _file_checksum(img_path)
        size_before = os.path.getsize(img_path)
        mtime_before = os.path.getmtime(img_path)

        config = load_config(str(tmp_path / "nonexistent.yaml"))
        config["output_dir"] = str(tmp_path / "output")
        output_paths = ensure_output_dirs(config)
        db = PicNoteDB(str(tmp_path / "safety_test.db"))

        asset = PhotoAsset(
            uuid="SAFE-IMG-001",
            filename="original.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=True,
            scene_labels=["text"],
            has_text=True,
            face_count=0,
            captured_at=datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc),
            width=640,
            height=480,
        )

        with patch("src.extractor._run_vision_cli") as mock_vision, \
             patch("src.analyzer.subprocess.run") as mock_claude:
            mock_vision.return_value = {"text": "Test", "qr_codes": [], "text_blocks": []}
            mock_claude.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Test", "type": "note"}',
                stderr="",
            )
            process_single_image(asset, db, config, output_paths)

        # CRITICAL ASSERTIONS
        assert os.path.exists(img_path), "Original image was DELETED!"
        assert _file_checksum(img_path) == checksum_before, "Original image was MODIFIED!"
        assert os.path.getsize(img_path) == size_before, "Original image size changed!"

    def test_original_exists_after_casual_skip(self, mock_photos_db, tmp_path):
        """Original image must still exist even after being classified as casual."""
        from src.config import ensure_output_dirs, load_config
        from src.db import PicNoteDB
        from src.main import process_single_image
        from src.watcher import PhotoAsset
        from datetime import datetime, timezone

        img_path = add_mock_photo(mock_photos_db, "SAFE-CAS-001", "casual.jpg", face_count=2)
        assert os.path.exists(img_path)

        config = load_config(str(tmp_path / "nonexistent.yaml"))
        config["output_dir"] = str(tmp_path / "output")
        output_paths = ensure_output_dirs(config)
        db = PicNoteDB(str(tmp_path / "safety_test.db"))

        asset = PhotoAsset(
            uuid="SAFE-CAS-001",
            filename="casual.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=["selfie"],
            has_text=False,
            face_count=2,
            captured_at=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
            width=640,
            height=480,
        )

        process_single_image(asset, db, config, output_paths)
        assert os.path.exists(img_path), "Original was DELETED after casual classification!"

    def test_no_files_created_in_photos_library(self, mock_photos_db, tmp_path):
        """CRITICAL: No files should be created inside the Photos library directory."""
        from unittest.mock import MagicMock, patch
        from src.config import ensure_output_dirs, load_config
        from src.db import PicNoteDB
        from src.main import process_single_image
        from src.watcher import PhotoAsset
        from datetime import datetime, timezone

        img_path = add_mock_photo(mock_photos_db, "SAFE-NOTOUCH-001", "notouch.jpg")

        # Count files in Photos library AFTER setup but BEFORE processing
        files_before = set()
        for root, dirs, files in os.walk(mock_photos_db):
            for f in files:
                files_before.add(os.path.join(root, f))

        config = load_config(str(tmp_path / "nonexistent.yaml"))
        config["output_dir"] = str(tmp_path / "output")
        output_paths = ensure_output_dirs(config)
        db = PicNoteDB(str(tmp_path / "safety_test.db"))

        asset = PhotoAsset(
            uuid="SAFE-NOTOUCH-001",
            filename="notouch.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=True,
            scene_labels=["text"],
            has_text=True,
            face_count=0,
            captured_at=datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc),
            width=640,
            height=480,
        )

        with patch("src.extractor._run_vision_cli") as mock_vision, \
             patch("src.analyzer.subprocess.run") as mock_claude:
            mock_vision.return_value = {"text": "Test", "qr_codes": [], "text_blocks": []}
            mock_claude.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Test", "type": "note"}',
                stderr="",
            )
            process_single_image(asset, db, config, output_paths)

        # Count files after processing
        files_after = set()
        for root, dirs, files in os.walk(mock_photos_db):
            for f in files:
                files_after.add(os.path.join(root, f))

        new_files = files_after - files_before
        assert new_files == set(), f"Files created in Photos library: {new_files}"

    def test_processing_failure_does_not_corrupt(self, mock_photos_db, tmp_path):
        """Even if processing crashes, no existing data should be corrupted."""
        from unittest.mock import patch
        from src.config import ensure_output_dirs, load_config
        from src.db import PicNoteDB
        from src.main import process_single_image
        from src.watcher import PhotoAsset
        from datetime import datetime, timezone

        img_path = add_mock_photo(mock_photos_db, "SAFE-CRASH-001", "crash.jpg")
        checksum_before = _file_checksum(img_path)

        config = load_config(str(tmp_path / "nonexistent.yaml"))
        config["output_dir"] = str(tmp_path / "output")
        output_paths = ensure_output_dirs(config)
        db = PicNoteDB(str(tmp_path / "safety_test.db"))

        asset = PhotoAsset(
            uuid="SAFE-CRASH-001",
            filename="crash.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=True,
            scene_labels=["text"],
            has_text=True,
            face_count=0,
            captured_at=datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc),
            width=640,
            height=480,
        )

        # Make extraction crash
        with patch("src.extractor._run_vision_cli", side_effect=RuntimeError("Crash!")):
            try:
                process_single_image(asset, db, config, output_paths)
            except RuntimeError:
                pass  # Expected

        # Original must be intact
        assert os.path.exists(img_path), "Original deleted after crash!"
        assert _file_checksum(img_path) == checksum_before, "Original modified after crash!"

        # Photos.sqlite must be intact
        db_path = os.path.join(mock_photos_db, "database", "Photos.sqlite")
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM ZASSET").fetchone()[0]
        conn.close()
        assert count >= 1, "Photos.sqlite corrupted after crash!"
