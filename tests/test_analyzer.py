"""Tests for PicNote Claude Code CLI analyzer."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.analyzer import _generate_local_analysis, _parse_json_response, analyze_image
from src.extractor import ExtractionResult


class TestParseJsonResponse:
    """Tests for parsing Claude CLI JSON responses."""

    def test_parse_clean_json(self):
        response = '{"title": "Test", "summary": "A test", "type": "note", "tags": ["test"]}'
        result = _parse_json_response(response)
        assert result["title"] == "Test"

    def test_parse_json_with_code_fences(self):
        response = '```json\n{"title": "Test", "type": "note"}\n```'
        result = _parse_json_response(response)
        assert result["title"] == "Test"

    def test_parse_json_with_generic_code_fences(self):
        response = '```\n{"title": "Test", "type": "note"}\n```'
        result = _parse_json_response(response)
        assert result["title"] == "Test"

    def test_invalid_json_returns_none(self):
        result = _parse_json_response("This is not JSON at all")
        assert result is None

    def test_empty_response_returns_none(self):
        result = _parse_json_response("")
        assert result is None

    def test_parse_json_with_text_before_and_after_fence(self):
        response = 'Here is the analysis:\n```json\n{"title": "Test"}\n```\nHope this helps!'
        result = _parse_json_response(response)
        assert result["title"] == "Test"

    def test_parse_json_multiple_code_blocks_takes_first(self):
        response = '```json\n{"title": "First"}\n```\nSome text\n```json\n{"title": "Second"}\n```'
        result = _parse_json_response(response)
        assert result["title"] == "First"

    def test_parse_json_with_whitespace_in_fence(self):
        response = '```json\n\n  {"title": "Spaced"}  \n\n```'
        result = _parse_json_response(response)
        assert result["title"] == "Spaced"

    def test_parse_json_unclosed_fence_falls_back(self):
        """Unclosed fence should fall back to trying the whole response."""
        response = '```json\n{"title": "Unclosed"}'
        result = _parse_json_response(response)
        # Regex won't match unclosed fence, falls back to raw parse which will fail
        # unless the raw text happens to be valid JSON
        assert result is None


class TestSensitiveKeywordNormalization:
    """Tests for the improved sensitive keyword matching with whitespace normalization."""

    def test_spaced_keyword_detected(self, tmp_path, test_config):
        """'p a s s w o r d' should be caught by normalized matching."""
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "spaced.jpg")
        _create_test_image(img_path, 640, 480)

        extraction = ExtractionResult()
        extraction.ocr_text = "My p a s s w o r d is secret"

        with patch("src.analyzer.subprocess.run") as mock_run:
            result = analyze_image(img_path, extraction, test_config)
            mock_run.assert_not_called()  # Should skip cloud analysis
        assert result is not None

    def test_keyword_with_newline_detected(self, tmp_path, test_config):
        """Keywords split across lines should be caught."""
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "newline.jpg")
        _create_test_image(img_path, 640, 480)

        extraction = ExtractionResult()
        extraction.ocr_text = "pass\nword: secret123"

        with patch("src.analyzer.subprocess.run") as mock_run:
            result = analyze_image(img_path, extraction, test_config)
            mock_run.assert_not_called()

    def test_keyword_with_zero_width_chars(self, tmp_path, test_config):
        """Zero-width characters between letters should be caught."""
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "zw.jpg")
        _create_test_image(img_path, 640, 480)

        extraction = ExtractionResult()
        extraction.ocr_text = "pass\u200bword: secret"  # Zero-width space

        with patch("src.analyzer.subprocess.run") as mock_run:
            result = analyze_image(img_path, extraction, test_config)
            mock_run.assert_not_called()

    def test_normal_text_not_blocked(self, tmp_path, test_config):
        """Text that doesn't contain sensitive keywords should proceed to Claude."""
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "safe.jpg")
        _create_test_image(img_path, 640, 480)

        extraction = ExtractionResult()
        extraction.ocr_text = "Meeting notes: discuss Q3 revenue targets"

        with patch("src.analyzer.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"title": "Meeting", "type": "note"}',
                stderr="",
            )
            analyze_image(img_path, extraction, test_config)
            mock_run.assert_called_once()  # Claude SHOULD be called

    def test_case_insensitive_keyword(self, tmp_path, test_config):
        """Keywords should be matched case-insensitively."""
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "caps.jpg")
        _create_test_image(img_path, 640, 480)

        extraction = ExtractionResult()
        extraction.ocr_text = "PASSWORD: admin123"

        with patch("src.analyzer.subprocess.run") as mock_run:
            result = analyze_image(img_path, extraction, test_config)
            mock_run.assert_not_called()


class TestLocalAnalysis:
    """Tests for local fallback analysis."""

    def test_receipt_detection(self):
        extraction = ExtractionResult()
        extraction.ocr_text = "Trader Joe's\nTotal: $14.50"
        extraction.amounts = ["$14.50"]
        result = _generate_local_analysis(extraction)
        assert result["type"] == "receipt"

    def test_link_detection(self):
        extraction = ExtractionResult()
        extraction.ocr_text = "Visit https://example.com"
        extraction.urls = ["https://example.com"]
        result = _generate_local_analysis(extraction)
        assert result["type"] == "link"

    def test_contact_detection(self):
        extraction = ExtractionResult()
        extraction.ocr_text = "Contact: user@example.com"
        extraction.emails = ["user@example.com"]
        result = _generate_local_analysis(extraction)
        assert result["type"] == "contact"

    def test_qr_code_detection(self):
        extraction = ExtractionResult()
        extraction.ocr_text = ""
        extraction.qr_codes = ["https://qr.example.com"]
        result = _generate_local_analysis(extraction)
        assert result["type"] == "code"

    def test_default_type_is_note(self):
        extraction = ExtractionResult()
        extraction.ocr_text = "Some general text content"
        result = _generate_local_analysis(extraction)
        assert result["type"] == "note"

    def test_title_from_first_line(self):
        extraction = ExtractionResult()
        extraction.ocr_text = "Meeting Notes\nDiscussed project timeline"
        result = _generate_local_analysis(extraction)
        assert result["title"] == "Meeting Notes"


class TestAnalyzeImage:
    """Tests for the full analysis pipeline."""

    @patch("src.analyzer.subprocess.run")
    def test_successful_analysis(self, mock_run, tmp_path, test_config):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "test.jpg")
        _create_test_image(img_path, 640, 480)

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "title": "Meeting Notes",
                "summary": "Notes from team meeting",
                "type": "note",
                "tags": ["meeting"],
                "urls": [],
                "dates": ["2026-04-08T14:00:00"],
                "contacts": [],
                "action_items": ["Follow up"],
            }),
            stderr="",
        )

        extraction = ExtractionResult()
        extraction.ocr_text = "Meeting at 2pm"
        result = analyze_image(img_path, extraction, test_config)

        assert result is not None
        assert result["title"] == "Meeting Notes"
        assert result["type"] == "note"
        mock_run.assert_called_once()

    @patch("src.analyzer.subprocess.run")
    def test_claude_called_with_correct_args(self, mock_run, tmp_path, test_config):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "test.jpg")
        _create_test_image(img_path, 640, 480)

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"title": "T", "type": "note"}',
            stderr="",
        )

        extraction = ExtractionResult()
        extraction.ocr_text = "test"
        analyze_image(img_path, extraction, test_config)

        call_args = mock_run.call_args
        cmd = call_args[0][0]
        assert cmd[0] == "claude"
        assert "-p" in cmd
        assert "--image" in cmd
        assert img_path in cmd

    @patch("src.analyzer.subprocess.run")
    def test_claude_timeout_falls_back_to_local(self, mock_run, tmp_path, test_config):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("claude", 60)

        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "test.jpg")
        _create_test_image(img_path, 640, 480)

        extraction = ExtractionResult()
        extraction.ocr_text = "Some text"
        result = analyze_image(img_path, extraction, test_config)

        # Should fall back to local analysis
        assert result is not None
        assert "title" in result

    @patch("src.analyzer.subprocess.run")
    def test_claude_error_falls_back_to_local(self, mock_run, tmp_path, test_config):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error",
        )

        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "test.jpg")
        _create_test_image(img_path, 640, 480)

        extraction = ExtractionResult()
        extraction.ocr_text = "Some text"
        result = analyze_image(img_path, extraction, test_config)

        assert result is not None

    def test_sensitive_content_skips_claude(self, tmp_path, test_config):
        """Images with sensitive keywords should NOT be sent to Claude."""
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "sensitive.jpg")
        _create_test_image(img_path, 640, 480)

        extraction = ExtractionResult()
        extraction.ocr_text = "My password is secret123"

        with patch("src.analyzer.subprocess.run") as mock_run:
            result = analyze_image(img_path, extraction, test_config)
            mock_run.assert_not_called()  # Claude should NOT be called

        assert result is not None

    def test_sensitive_ssn_skips_claude(self, tmp_path, test_config):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "ssn.jpg")
        _create_test_image(img_path, 640, 480)

        extraction = ExtractionResult()
        extraction.ocr_text = "SSN: 123-45-6789"

        with patch("src.analyzer.subprocess.run") as mock_run:
            result = analyze_image(img_path, extraction, test_config)
            mock_run.assert_not_called()

    @patch("src.analyzer.subprocess.run")
    def test_analysis_for_receipt(self, mock_run, tmp_path, test_config):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "receipt.jpg")
        _create_test_image(img_path, 400, 800)

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "title": "Receipt - Blue Bottle Coffee",
                "summary": "Receipt for coffee purchase",
                "type": "receipt",
                "tags": ["receipt", "coffee"],
                "urls": [],
                "dates": ["2026-04-08"],
                "contacts": [],
                "action_items": [],
            }),
            stderr="",
        )

        extraction = ExtractionResult()
        extraction.ocr_text = "Blue Bottle Coffee\nTotal: $14.50"
        extraction.amounts = ["$14.50"]
        result = analyze_image(img_path, extraction, test_config)

        assert result["type"] == "receipt"
        assert "Blue Bottle" in result["title"]

    @patch("src.analyzer.subprocess.run")
    def test_analysis_for_event_flyer(self, mock_run, tmp_path, test_config):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "flyer.jpg")
        _create_test_image(img_path, 640, 480)

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "title": "Jazz Night at Blue Note",
                "summary": "Jazz concert event flyer",
                "type": "event",
                "tags": ["event", "music", "jazz"],
                "urls": [],
                "dates": ["2026-04-18T20:00:00"],
                "contacts": [],
                "action_items": ["Buy tickets"],
            }),
            stderr="",
        )

        extraction = ExtractionResult()
        extraction.ocr_text = "Jazz Night\nApril 18, 8pm\nBlue Note"
        result = analyze_image(img_path, extraction, test_config)

        assert result["type"] == "event"

    def test_casual_images_never_analyzed(self):
        """Verify the design: casual images should never reach analyze_image.
        This is enforced by main.py, but we document the expectation here."""
        # This is a design contract test — analyze_image itself doesn't check
        # classification, it's the caller's responsibility
        pass
