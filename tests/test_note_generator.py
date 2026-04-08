"""Tests for PicNote Markdown note generator."""

import os
from datetime import datetime, timezone

import pytest

from src.extractor import ExtractionResult
from src.note_generator import (
    _ensure_unique_path,
    _slugify,
    generate_note,
)
from src.watcher import PhotoAsset


class TestSlugify:
    """Tests for filename slugification."""

    def test_basic_text(self):
        assert _slugify("Hello World") == "hello-world"

    def test_special_characters(self):
        slug = _slugify("Receipt: $14.50 @ Trader Joe's")
        assert "/" not in slug
        assert ":" not in slug
        assert "$" not in slug

    def test_chinese_characters_preserved(self):
        slug = _slugify("会议记录 Meeting Notes")
        assert "会议记录" in slug

    def test_long_title_truncated(self):
        long_title = "A" * 200
        slug = _slugify(long_title)
        assert len(slug) <= 80

    def test_empty_string(self):
        assert _slugify("") == "untitled"

    def test_only_special_chars(self):
        assert _slugify("!!!@@@###") == "untitled"


class TestEnsureUniquePath:
    """Tests for unique file path generation."""

    def test_unique_path_no_conflict(self, tmp_path):
        path = str(tmp_path / "note.md")
        assert _ensure_unique_path(path) == path

    def test_appends_counter_on_conflict(self, tmp_path):
        path = str(tmp_path / "note.md")
        # Create the conflicting file
        with open(path, "w") as f:
            f.write("existing")

        unique = _ensure_unique_path(path)
        assert unique == str(tmp_path / "note-2.md")

    def test_increments_counter(self, tmp_path):
        base = str(tmp_path / "note.md")
        # Create note.md and note-2.md
        with open(base, "w") as f:
            f.write("1")
        with open(str(tmp_path / "note-2.md"), "w") as f:
            f.write("2")

        unique = _ensure_unique_path(base)
        assert unique == str(tmp_path / "note-3.md")


class TestGenerateNote:
    """Tests for full note generation."""

    def test_generates_note_file(
        self, sample_asset, sample_extraction, sample_analysis, test_config, output_paths
    ):
        note_path = generate_note(
            sample_asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        assert os.path.exists(note_path)
        assert note_path.endswith(".md")

    def test_note_contains_title(
        self, sample_asset, sample_extraction, sample_analysis, test_config, output_paths
    ):
        note_path = generate_note(
            sample_asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        with open(note_path) as f:
            content = f.read()
        assert "# Meeting Notes - Project Sync" in content

    def test_note_contains_source_section(
        self, sample_asset, sample_extraction, sample_analysis, test_config, output_paths
    ):
        note_path = generate_note(
            sample_asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        with open(note_path) as f:
            content = f.read()
        assert "## Source" in content
        assert sample_asset.uuid in content
        assert sample_asset.file_path in content

    def test_note_contains_source_type(
        self, screenshot_asset, sample_extraction, sample_analysis, test_config, output_paths
    ):
        note_path = generate_note(
            screenshot_asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        with open(note_path) as f:
            content = f.read()
        assert "screenshot" in content

    def test_note_contains_summary(
        self, sample_asset, sample_extraction, sample_analysis, test_config, output_paths
    ):
        note_path = generate_note(
            sample_asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        with open(note_path) as f:
            content = f.read()
        assert "## Summary" in content
        assert "Meeting notes" in content

    def test_note_contains_extracted_urls(
        self, sample_asset, sample_extraction, sample_analysis, test_config, output_paths
    ):
        note_path = generate_note(
            sample_asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        with open(note_path) as f:
            content = f.read()
        assert "https://example.com" in content

    def test_note_contains_raw_text(
        self, sample_asset, sample_extraction, sample_analysis, test_config, output_paths
    ):
        note_path = generate_note(
            sample_asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        with open(note_path) as f:
            content = f.read()
        assert "## Raw Text" in content
        assert "Meeting at 2pm" in content

    def test_note_contains_tags(
        self, sample_asset, sample_extraction, sample_analysis, test_config, output_paths
    ):
        note_path = generate_note(
            sample_asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        with open(note_path) as f:
            content = f.read()
        assert "#meeting" in content
        assert "#work" in content

    def test_note_contains_thumbnail(
        self, sample_asset, sample_extraction, sample_analysis, test_config, output_paths
    ):
        note_path = generate_note(
            sample_asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        with open(note_path) as f:
            content = f.read()
        assert "## Thumbnail" in content
        assert "-thumb.jpg" in content

    def test_thumbnail_created_in_assets(
        self, sample_asset, sample_extraction, sample_analysis, test_config, output_paths
    ):
        generate_note(
            sample_asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        # Check thumbnail exists in assets directory
        assets_dir = output_paths["assets_dir"]
        thumbs = []
        for root, dirs, files in os.walk(assets_dir):
            for f in files:
                if f.endswith("-thumb.jpg"):
                    thumbs.append(os.path.join(root, f))
        assert len(thumbs) >= 1

    def test_note_organized_by_date(
        self, sample_asset, sample_extraction, sample_analysis, test_config, output_paths
    ):
        note_path = generate_note(
            sample_asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        # Should be under vault/daily/YYYY/MM/DD/
        assert "daily" in note_path
        assert "2026" in note_path

    def test_note_with_minimal_fields(self, sample_asset, test_config, output_paths):
        """Note generation should work with minimal extraction and no analysis."""
        extraction = ExtractionResult()
        extraction.ocr_text = "Just some text"

        note_path = generate_note(
            sample_asset, extraction, None, test_config, output_paths
        )
        assert os.path.exists(note_path)
        with open(note_path) as f:
            content = f.read()
        assert "Just some text" in content

    def test_note_with_no_analysis(self, sample_asset, sample_extraction, test_config, output_paths):
        """Should generate a note even when analysis returns None."""
        note_path = generate_note(
            sample_asset, sample_extraction, None, test_config, output_paths
        )
        assert os.path.exists(note_path)

    def test_duplicate_note_filenames_handled(
        self, sample_asset, sample_extraction, sample_analysis, test_config, output_paths
    ):
        """Generating two notes with the same title should create unique files."""
        path1 = generate_note(
            sample_asset, sample_extraction, sample_analysis, test_config, output_paths
        )

        # Create a second asset with different UUID but same analysis title
        from tests.conftest import _create_test_image
        img_path2 = os.path.join(os.path.dirname(sample_asset.file_path), "photo2.jpg")
        _create_test_image(img_path2, 640, 480)

        asset2 = PhotoAsset(
            uuid="UUID-SECOND",
            filename="photo2.jpg",
            directory="A",
            file_path=img_path2,
            is_screenshot=False,
            scene_labels=[],
            has_text=False,
            face_count=0,
            captured_at=sample_asset.captured_at,
            width=640,
            height=480,
        )
        path2 = generate_note(asset2, sample_extraction, sample_analysis, test_config, output_paths)

        assert path1 != path2
        assert os.path.exists(path1)
        assert os.path.exists(path2)

    def test_note_contains_action_items(
        self, sample_asset, sample_extraction, sample_analysis, test_config, output_paths
    ):
        note_path = generate_note(
            sample_asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        with open(note_path) as f:
            content = f.read()
        assert "- [ ] Follow up on project sync" in content

    def test_note_type_in_header(
        self, sample_asset, sample_extraction, sample_analysis, test_config, output_paths
    ):
        note_path = generate_note(
            sample_asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        with open(note_path) as f:
            content = f.read()
        assert "**Type**: note" in content

    def test_thumbnail_fallback_on_corrupt_image(
        self, sample_extraction, sample_analysis, test_config, output_paths, tmp_path
    ):
        """When PIL can't process an image, it should fall back to copying."""
        # Create a corrupt "image" file
        corrupt_path = str(tmp_path / "corrupt.jpg")
        with open(corrupt_path, "w") as f:
            f.write("not a real image")

        asset = PhotoAsset(
            uuid="CORRUPT-001",
            filename="corrupt.jpg",
            directory="A",
            file_path=corrupt_path,
            is_screenshot=False,
            scene_labels=[],
            has_text=True,
            face_count=0,
            captured_at=datetime(2026, 4, 8, 14, 0),
            width=640,
            height=480,
        )

        # Should still generate a note (using fallback copy)
        note_path = generate_note(
            asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        assert os.path.exists(note_path)
        # Thumbnail should exist (copied original)
        with open(note_path) as f:
            content = f.read()
        assert "## Thumbnail" in content

    def test_note_generated_when_image_missing(
        self, sample_extraction, sample_analysis, test_config, output_paths, tmp_path
    ):
        """Note should be generated even when the original image file doesn't exist."""
        asset = PhotoAsset(
            uuid="MISSING-THUMB",
            filename="gone.jpg",
            directory="A",
            file_path=str(tmp_path / "nonexistent.jpg"),
            is_screenshot=False,
            scene_labels=[],
            has_text=True,
            face_count=0,
            captured_at=datetime(2026, 4, 8, 14, 0),
            width=640,
            height=480,
        )

        note_path = generate_note(
            asset, sample_extraction, sample_analysis, test_config, output_paths
        )
        assert os.path.exists(note_path)
        with open(note_path) as f:
            content = f.read()
        # Note should still have the source section
        assert "MISSING-THUMB" in content
