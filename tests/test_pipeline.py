"""Integration tests for PicNote end-to-end pipeline."""

import hashlib
import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.config import ensure_output_dirs, load_config
from src.db import PicNoteDB
from src.main import process_single_image
from src.watcher import PhotoAsset
from tests.conftest import _create_test_image


def _file_checksum(path: str) -> str:
    """Calculate MD5 checksum of a file."""
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


class TestPipelineIntegration:
    """End-to-end tests for the full processing pipeline."""

    @patch("src.analyzer.subprocess.run")
    @patch("src.extractor._run_vision_cli")
    def test_process_screenshot_with_url(
        self, mock_vision, mock_claude, tmp_path
    ):
        """Full pipeline: screenshot with URL → note created with extracted URL."""
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        config["output_dir"] = str(tmp_path / "output")
        output_paths = ensure_output_dirs(config)
        db = PicNoteDB(str(tmp_path / "test.db"))

        img_path = str(tmp_path / "screenshot.png")
        _create_test_image(img_path, 390, 844, text="Visit https://example.com")

        asset = PhotoAsset(
            uuid="E2E-URL-001",
            filename="screenshot.png",
            directory="A",
            file_path=img_path,
            is_screenshot=True,
            scene_labels=["text"],
            has_text=True,
            face_count=0,
            captured_at=datetime(2026, 4, 8, 14, 30, tzinfo=timezone.utc),
            width=390,
            height=844,
        )

        mock_vision.return_value = {
            "text": "Visit https://example.com",
            "qr_codes": [],
            "text_blocks": [],
        }
        mock_claude.return_value = MagicMock(
            returncode=0,
            stdout='{"title": "Web Link", "summary": "Screenshot with URL", "type": "link", "tags": ["link"], "urls": ["https://example.com"], "dates": [], "contacts": [], "action_items": []}',
            stderr="",
        )

        created = process_single_image(asset, db, config, output_paths)
        assert created is True

        record = db.get_by_uuid("E2E-URL-001")
        assert record is not None
        assert record["classification"] == "informational"
        assert "https://example.com" in record["ocr_text"]
        assert record["note_path"] is not None
        assert os.path.exists(record["note_path"])

    @patch("src.extractor._run_vision_cli")
    def test_process_selfie_skipped(self, mock_vision, tmp_path):
        """Selfie → classified as casual, NO note created."""
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        config["output_dir"] = str(tmp_path / "output")
        output_paths = ensure_output_dirs(config)
        db = PicNoteDB(str(tmp_path / "test.db"))

        img_path = str(tmp_path / "selfie.jpg")
        _create_test_image(img_path, 640, 480)

        asset = PhotoAsset(
            uuid="E2E-SELFIE-001",
            filename="selfie.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=["selfie", "portrait"],
            has_text=False,
            face_count=2,
            captured_at=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
            width=640,
            height=480,
        )

        created = process_single_image(asset, db, config, output_paths)
        assert created is False

        record = db.get_by_uuid("E2E-SELFIE-001")
        assert record is not None
        assert record["classification"] == "casual"
        assert record["note_path"] is None

        # Vision CLI should NOT be called for casual images
        mock_vision.assert_not_called()

    @patch("src.analyzer.subprocess.run")
    @patch("src.extractor._run_vision_cli")
    def test_process_receipt(self, mock_vision, mock_claude, tmp_path):
        """Receipt → note with merchant, amount, date."""
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        config["output_dir"] = str(tmp_path / "output")
        output_paths = ensure_output_dirs(config)
        db = PicNoteDB(str(tmp_path / "test.db"))

        img_path = str(tmp_path / "receipt.jpg")
        _create_test_image(img_path, 400, 800, text="Trader Joes Total $14.50")

        asset = PhotoAsset(
            uuid="E2E-RECEIPT-001",
            filename="receipt.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=["receipt"],
            has_text=True,
            face_count=0,
            captured_at=datetime(2026, 4, 8, 18, 30, tzinfo=timezone.utc),
            width=400,
            height=800,
        )

        mock_vision.return_value = {
            "text": "Trader Joe's\nTotal: $14.50\nDate: 04/08/2026",
            "qr_codes": [],
            "text_blocks": [],
        }
        mock_claude.return_value = MagicMock(
            returncode=0,
            stdout='{"title": "Receipt - Trader Joes", "summary": "Grocery receipt", "type": "receipt", "tags": ["receipt", "grocery"], "urls": [], "dates": ["2026-04-08"], "contacts": [], "action_items": []}',
            stderr="",
        )

        created = process_single_image(asset, db, config, output_paths)
        assert created is True

        record = db.get_by_uuid("E2E-RECEIPT-001")
        assert record["classification"] == "informational"
        assert os.path.exists(record["note_path"])

        with open(record["note_path"]) as f:
            content = f.read()
        assert "Trader" in content
        assert "$14.50" in content

    @patch("src.analyzer.subprocess.run")
    @patch("src.extractor._run_vision_cli")
    def test_process_qr_code(self, mock_vision, mock_claude, tmp_path):
        """QR code image → note with decoded QR content."""
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        config["output_dir"] = str(tmp_path / "output")
        output_paths = ensure_output_dirs(config)
        db = PicNoteDB(str(tmp_path / "test.db"))

        img_path = str(tmp_path / "qr.jpg")
        _create_test_image(img_path, 640, 480)

        asset = PhotoAsset(
            uuid="E2E-QR-001",
            filename="qr.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=["text"],
            has_text=True,
            face_count=0,
            captured_at=datetime(2026, 4, 8, 16, 0, tzinfo=timezone.utc),
            width=640,
            height=480,
        )

        mock_vision.return_value = {
            "text": "Scan QR for details",
            "qr_codes": ["https://event.example.com/tickets"],
            "text_blocks": [],
        }
        mock_claude.return_value = MagicMock(
            returncode=0,
            stdout='{"title": "QR Code - Event Tickets", "summary": "QR code linking to event tickets", "type": "code", "tags": ["qr", "event"], "urls": ["https://event.example.com/tickets"], "dates": [], "contacts": [], "action_items": []}',
            stderr="",
        )

        created = process_single_image(asset, db, config, output_paths)
        assert created is True

        record = db.get_by_uuid("E2E-QR-001")
        assert os.path.exists(record["note_path"])
        with open(record["note_path"]) as f:
            content = f.read()
        assert "https://event.example.com/tickets" in content

    @patch("src.analyzer.subprocess.run")
    @patch("src.extractor._run_vision_cli")
    def test_deduplication(self, mock_vision, mock_claude, tmp_path):
        """Processing same image twice should only create one note."""
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        config["output_dir"] = str(tmp_path / "output")
        output_paths = ensure_output_dirs(config)
        db = PicNoteDB(str(tmp_path / "test.db"))

        img_path = str(tmp_path / "dup.png")
        _create_test_image(img_path, 390, 844, text="Duplicate test")

        asset = PhotoAsset(
            uuid="E2E-DUP-001",
            filename="dup.png",
            directory="A",
            file_path=img_path,
            is_screenshot=True,
            scene_labels=["text"],
            has_text=True,
            face_count=0,
            captured_at=datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc),
            width=390,
            height=844,
        )

        mock_vision.return_value = {"text": "Dup", "qr_codes": [], "text_blocks": []}
        mock_claude.return_value = MagicMock(
            returncode=0,
            stdout='{"title": "Dup", "type": "note"}',
            stderr="",
        )

        # Process first time
        created1 = process_single_image(asset, db, config, output_paths)
        assert created1 is True

        # Process second time — should be skipped
        created2 = process_single_image(asset, db, config, output_paths)
        assert created2 is False

    @patch("src.analyzer.subprocess.run")
    @patch("src.extractor._run_vision_cli")
    def test_original_image_never_modified(self, mock_vision, mock_claude, tmp_path):
        """CRITICAL: Original image file must NEVER be modified during processing."""
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        config["output_dir"] = str(tmp_path / "output")
        output_paths = ensure_output_dirs(config)
        db = PicNoteDB(str(tmp_path / "test.db"))

        img_path = str(tmp_path / "original.jpg")
        _create_test_image(img_path, 640, 480, text="Do not modify")

        # Record original file state
        original_checksum = _file_checksum(img_path)
        original_mtime = os.path.getmtime(img_path)
        original_size = os.path.getsize(img_path)

        asset = PhotoAsset(
            uuid="E2E-SAFETY-001",
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

        mock_vision.return_value = {"text": "Test", "qr_codes": [], "text_blocks": []}
        mock_claude.return_value = MagicMock(
            returncode=0,
            stdout='{"title": "Test", "type": "note"}',
            stderr="",
        )

        process_single_image(asset, db, config, output_paths)

        # Verify original is untouched
        assert os.path.exists(img_path), "Original image was DELETED!"
        assert _file_checksum(img_path) == original_checksum, "Original image was MODIFIED!"
        assert os.path.getsize(img_path) == original_size, "Original image size changed!"

    @patch("src.analyzer.subprocess.run")
    @patch("src.extractor._run_vision_cli")
    def test_original_image_never_deleted(self, mock_vision, mock_claude, tmp_path):
        """CRITICAL: Original image file must NEVER be deleted during processing."""
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        config["output_dir"] = str(tmp_path / "output")
        output_paths = ensure_output_dirs(config)
        db = PicNoteDB(str(tmp_path / "test.db"))

        img_path = str(tmp_path / "keep_me.jpg")
        _create_test_image(img_path, 640, 480)

        asset = PhotoAsset(
            uuid="E2E-NODELETE-001",
            filename="keep_me.jpg",
            directory="A",
            file_path=img_path,
            is_screenshot=False,
            scene_labels=["selfie"],
            has_text=False,
            face_count=1,
            captured_at=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
            width=640,
            height=480,
        )

        # Even casual images should not delete the original
        process_single_image(asset, db, config, output_paths)
        assert os.path.exists(img_path), "Original image was DELETED during casual classification!"

    @patch("src.analyzer.subprocess.run")
    @patch("src.extractor._run_vision_cli")
    def test_batch_processing(self, mock_vision, mock_claude, tmp_path):
        """Process a batch of mixed images correctly."""
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        config["output_dir"] = str(tmp_path / "output")
        output_paths = ensure_output_dirs(config)
        db = PicNoteDB(str(tmp_path / "test.db"))

        mock_vision.return_value = {"text": "Some text", "qr_codes": [], "text_blocks": []}
        mock_claude.return_value = MagicMock(
            returncode=0,
            stdout='{"title": "Note", "type": "note"}',
            stderr="",
        )

        assets = []
        expected_informational = 0
        expected_casual = 0

        for i, (is_ss, scene, has_text, faces) in enumerate([
            (True, ["text"], True, 0),        # screenshot → informational
            (False, ["selfie"], False, 1),     # selfie → casual
            (False, ["document"], True, 0),    # document → informational
            (False, ["landscape"], False, 0),  # landscape → casual
            (True, [], True, 0),               # screenshot → informational
        ]):
            img_path = str(tmp_path / f"batch_{i}.jpg")
            _create_test_image(img_path, 640, 480)

            asset = PhotoAsset(
                uuid=f"BATCH-{i}",
                filename=f"batch_{i}.jpg",
                directory="A",
                file_path=img_path,
                is_screenshot=is_ss,
                scene_labels=scene,
                has_text=has_text,
                face_count=faces,
                captured_at=datetime(2026, 4, 8, 10 + i, 0, tzinfo=timezone.utc),
                width=640,
                height=480,
            )
            assets.append(asset)
            if is_ss or "document" in scene or has_text:
                expected_informational += 1
            else:
                expected_casual += 1

        notes_created = 0
        for asset in assets:
            if process_single_image(asset, db, config, output_paths):
                notes_created += 1

        assert notes_created == expected_informational
        stats = db.get_stats()
        assert stats["total"] == 5
        assert stats["informational"] == expected_informational
        assert stats["casual"] == expected_casual

    def test_missing_file_handled_gracefully(self, tmp_path):
        """Should handle missing original file without crashing."""
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        config["output_dir"] = str(tmp_path / "output")
        output_paths = ensure_output_dirs(config)
        db = PicNoteDB(str(tmp_path / "test.db"))

        asset = PhotoAsset(
            uuid="MISSING-001",
            filename="gone.jpg",
            directory="A",
            file_path=str(tmp_path / "gone.jpg"),  # File doesn't exist
            is_screenshot=True,
            scene_labels=[],
            has_text=False,
            face_count=0,
            captured_at=datetime(2026, 4, 8, 14, 0, tzinfo=timezone.utc),
            width=640,
            height=480,
        )

        created = process_single_image(asset, db, config, output_paths)
        assert created is False
