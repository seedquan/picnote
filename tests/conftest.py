"""Shared test fixtures for PicNote tests."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.config import DEFAULT_CONFIG, load_config
from src.db import PicNoteDB
from src.extractor import ExtractionResult
from src.watcher import PhotoAsset


# Path to test images
TEST_IMAGES_DIR = os.path.join(os.path.dirname(__file__), "test_images")


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory for test output."""
    return tmp_path


@pytest.fixture
def test_config(tmp_path):
    """Provide a test configuration with temporary output directory."""
    config = dict(DEFAULT_CONFIG)
    config["output_dir"] = str(tmp_path / "output")
    config["photos_library"] = str(tmp_path / "Photos.photoslibrary")
    return config


@pytest.fixture
def output_paths(test_config, tmp_path):
    """Create and return output directory paths."""
    from src.config import ensure_output_dirs
    return ensure_output_dirs(test_config)


@pytest.fixture
def test_db(tmp_path):
    """Provide a test database instance."""
    db_path = str(tmp_path / "test_picnote.db")
    return PicNoteDB(db_path)


@pytest.fixture
def sample_asset(tmp_path):
    """Create a sample PhotoAsset for testing."""
    # Create a dummy image file
    img_path = str(tmp_path / "test_photo.jpg")
    _create_test_image(img_path, 640, 480, text="Hello World")

    return PhotoAsset(
        uuid="TEST-UUID-12345",
        filename="test_photo.jpg",
        directory="A",
        file_path=img_path,
        is_screenshot=False,
        scene_labels=[],
        has_text=False,
        face_count=0,
        captured_at=datetime(2026, 4, 8, 14, 30, tzinfo=timezone.utc),
        width=640,
        height=480,
    )


@pytest.fixture
def screenshot_asset(tmp_path):
    """Create a sample screenshot asset."""
    img_path = str(tmp_path / "screenshot.png")
    _create_test_image(img_path, 390, 844, text="https://example.com")

    return PhotoAsset(
        uuid="SCREENSHOT-UUID-001",
        filename="screenshot.png",
        directory="B",
        file_path=img_path,
        is_screenshot=True,
        scene_labels=["text", "screen"],
        has_text=True,
        face_count=0,
        captured_at=datetime(2026, 4, 8, 15, 0, tzinfo=timezone.utc),
        width=390,
        height=844,
    )


@pytest.fixture
def selfie_asset(tmp_path):
    """Create a sample selfie asset that should be classified as casual."""
    img_path = str(tmp_path / "selfie.jpg")
    _create_test_image(img_path, 640, 480)

    return PhotoAsset(
        uuid="SELFIE-UUID-001",
        filename="selfie.jpg",
        directory="C",
        file_path=img_path,
        is_screenshot=False,
        scene_labels=["selfie", "portrait"],
        has_text=False,
        face_count=2,
        captured_at=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
        width=640,
        height=480,
    )


@pytest.fixture
def receipt_asset(tmp_path):
    """Create a sample receipt asset."""
    img_path = str(tmp_path / "receipt.jpg")
    _create_test_image(img_path, 400, 800, text="Trader Joe's $14.50")

    return PhotoAsset(
        uuid="RECEIPT-UUID-001",
        filename="receipt.jpg",
        directory="D",
        file_path=img_path,
        is_screenshot=False,
        scene_labels=["receipt", "document"],
        has_text=True,
        face_count=0,
        captured_at=datetime(2026, 4, 8, 18, 30, tzinfo=timezone.utc),
        width=400,
        height=800,
    )


@pytest.fixture
def sample_extraction():
    """Create a sample extraction result."""
    result = ExtractionResult()
    result.ocr_text = "Meeting at 2pm\nhttps://example.com\nCall: 555-0123"
    result.urls = ["https://example.com"]
    result.emails = []
    result.phones = ["555-0123"]
    result.dates = ["2pm"]
    result.amounts = []
    result.qr_codes = []
    return result


@pytest.fixture
def sample_analysis():
    """Create a sample analysis result."""
    return {
        "title": "Meeting Notes - Project Sync",
        "summary": "Meeting notes with a link to project resources and a contact number.",
        "type": "note",
        "tags": ["meeting", "work"],
        "urls": ["https://example.com"],
        "dates": ["2pm"],
        "contacts": ["555-0123"],
        "action_items": ["Follow up on project sync"],
    }


@pytest.fixture
def mock_photos_db(tmp_path):
    """Create a mock Photos.sqlite database for testing.

    This simulates the structure of Apple's Photos.sqlite without
    needing the actual Photos library.
    """
    db_dir = tmp_path / "Photos.photoslibrary" / "database"
    db_dir.mkdir(parents=True)
    db_path = str(db_dir / "Photos.sqlite")

    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE ZASSET (
            Z_PK INTEGER PRIMARY KEY,
            ZUUID TEXT,
            ZFILENAME TEXT,
            ZDIRECTORY TEXT,
            ZDATECREATED REAL,
            ZWIDTH INTEGER,
            ZHEIGHT INTEGER,
            ZTRASHEDSTATE INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE ZADDITIONALASSETATTRIBUTES (
            Z_PK INTEGER PRIMARY KEY,
            ZASSET INTEGER,
            ZISDETECTEDSCREENSHOT INTEGER DEFAULT 0,
            ZCHARACTERRECOGNITIONATTRIBUTES INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE ZDETECTEDFACE (
            Z_PK INTEGER PRIMARY KEY,
            ZASSET INTEGER
        )
    """)
    conn.commit()
    conn.close()

    return str(tmp_path / "Photos.photoslibrary")


def add_mock_photo(
    photos_library: str,
    uuid: str,
    filename: str,
    directory: str = "A",
    timestamp: float = 765432100.0,
    width: int = 640,
    height: int = 480,
    is_screenshot: int = 0,
    has_ocr: int = 0,
    face_count: int = 0,
    trashed: int = 0,
):
    """Add a mock photo entry to the mock Photos.sqlite database."""
    db_path = os.path.join(photos_library, "database", "Photos.sqlite")
    conn = sqlite3.connect(db_path)

    # Insert asset
    conn.execute(
        """INSERT INTO ZASSET (ZUUID, ZFILENAME, ZDIRECTORY, ZDATECREATED,
            ZWIDTH, ZHEIGHT, ZTRASHEDSTATE)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (uuid, filename, directory, timestamp, width, height, trashed),
    )
    pk = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Insert additional attributes
    conn.execute(
        """INSERT INTO ZADDITIONALASSETATTRIBUTES
            (ZASSET, ZISDETECTEDSCREENSHOT, ZCHARACTERRECOGNITIONATTRIBUTES)
        VALUES (?, ?, ?)""",
        (pk, is_screenshot, has_ocr),
    )

    # Insert faces
    for _ in range(face_count):
        conn.execute("INSERT INTO ZDETECTEDFACE (ZASSET) VALUES (?)", (pk,))

    conn.commit()
    conn.close()

    # Create a dummy image file
    originals_dir = os.path.join(photos_library, "originals", directory)
    os.makedirs(originals_dir, exist_ok=True)
    img_path = os.path.join(originals_dir, filename)
    _create_test_image(img_path, width, height)

    return img_path


def _create_test_image(path: str, width: int, height: int, text: str | None = None):
    """Create a simple test image using Pillow."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (width, height), color=(200, 200, 200))
    if text:
        draw = ImageDraw.Draw(img)
        draw.text((10, 10), text, fill=(0, 0, 0))

    fmt = "PNG" if path.endswith(".png") else "JPEG"
    img.save(path, fmt)
