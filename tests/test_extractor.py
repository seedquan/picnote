"""Tests for PicNote text and data extraction."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.extractor import (
    ExtractionResult,
    _extract_amounts,
    _extract_emails,
    _extract_phones,
    _extract_urls,
    extract_from_image,
)


class TestURLExtraction:
    """Tests for URL extraction from text."""

    def test_extract_http_url(self):
        urls = _extract_urls("Visit https://example.com for more")
        assert "https://example.com" in urls

    def test_extract_https_url(self):
        urls = _extract_urls("Check https://docs.google.com/document/d/1234")
        assert len(urls) == 1
        assert "https://docs.google.com/document/d/1234" in urls

    def test_extract_multiple_urls(self):
        text = "Links: https://a.com and https://b.com/path"
        urls = _extract_urls(text)
        assert len(urls) == 2

    def test_extract_url_with_query_params(self):
        urls = _extract_urls("https://example.com/search?q=test&page=1")
        assert len(urls) == 1

    def test_no_urls_returns_empty(self):
        urls = _extract_urls("No links here, just plain text.")
        assert urls == []

    def test_deduplicates_urls(self):
        text = "https://example.com and again https://example.com"
        urls = _extract_urls(text)
        assert len(urls) == 1

    def test_strips_trailing_punctuation(self):
        urls = _extract_urls("See https://example.com.")
        assert urls[0] == "https://example.com"

    def test_extract_www_url(self):
        urls = _extract_urls("Visit www.example.com")
        assert len(urls) == 1


class TestEmailExtraction:
    """Tests for email extraction from text."""

    def test_extract_email(self):
        emails = _extract_emails("Contact: user@example.com")
        assert "user@example.com" in emails

    def test_extract_multiple_emails(self):
        text = "Email a@b.com or c@d.org"
        emails = _extract_emails(text)
        assert len(emails) == 2

    def test_no_emails_returns_empty(self):
        emails = _extract_emails("No email addresses here")
        assert emails == []

    def test_complex_email(self):
        emails = _extract_emails("john.doe+tag@company.co.uk")
        assert len(emails) == 1


class TestPhoneExtraction:
    """Tests for phone number extraction."""

    def test_extract_us_phone(self):
        phones = _extract_phones("Call 555-123-4567")
        assert len(phones) >= 1

    def test_extract_chinese_mobile(self):
        phones = _extract_phones("联系电话 13912345678")
        assert len(phones) >= 1

    def test_extract_international_format(self):
        phones = _extract_phones("Phone: +1-555-123-4567")
        assert len(phones) >= 1

    def test_no_phones_returns_empty(self):
        phones = _extract_phones("No phone numbers in this text")
        assert phones == []

    def test_short_numbers_filtered(self):
        """Numbers with less than 7 digits should be filtered out."""
        phones = _extract_phones("Room 123")
        assert phones == []


class TestAmountExtraction:
    """Tests for monetary amount extraction."""

    def test_extract_dollar_amount(self):
        amounts = _extract_amounts("Total: $14.50")
        assert len(amounts) >= 1
        assert any("14.50" in a for a in amounts)

    def test_extract_yuan_amount(self):
        amounts = _extract_amounts("价格: ¥128.00")
        assert len(amounts) >= 1

    def test_extract_euro_amount(self):
        amounts = _extract_amounts("Price: €25.99")
        assert len(amounts) >= 1

    def test_no_amounts_returns_empty(self):
        amounts = _extract_amounts("No money here")
        assert amounts == []

    def test_extract_cny_text_format(self):
        amounts = _extract_amounts("50元")
        assert len(amounts) >= 1


class TestExtractionResult:
    """Tests for ExtractionResult container."""

    def test_empty_result_has_no_data(self):
        result = ExtractionResult()
        assert result.has_data is False

    def test_result_with_text_has_data(self):
        result = ExtractionResult()
        result.ocr_text = "Some text"
        assert result.has_data is True

    def test_result_with_urls_has_data(self):
        result = ExtractionResult()
        result.urls = ["https://example.com"]
        assert result.has_data is True

    def test_to_dict(self):
        result = ExtractionResult()
        result.urls = ["https://example.com"]
        result.emails = ["a@b.com"]
        d = result.to_dict()
        assert d["urls"] == ["https://example.com"]
        assert d["emails"] == ["a@b.com"]
        assert d["phones"] == []


class TestExtractFromImage:
    """Tests for the full image extraction pipeline."""

    @patch("src.extractor._run_vision_cli")
    def test_extract_with_vision_cli(self, mock_vision, tmp_path):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "test.jpg")
        _create_test_image(img_path, 640, 480)

        mock_vision.return_value = {
            "text": "Meeting at 2pm\nhttps://example.com\nCall: 555-123-4567",
            "qr_codes": [],
            "text_blocks": [],
        }

        result = extract_from_image(img_path)
        assert "https://example.com" in result.urls
        assert result.ocr_text != ""
        assert len(result.phones) >= 1

    @patch("src.extractor._run_vision_cli")
    def test_extract_qr_code(self, mock_vision, tmp_path):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "qr.jpg")
        _create_test_image(img_path, 640, 480)

        mock_vision.return_value = {
            "text": "",
            "qr_codes": ["https://qr-target.com"],
            "text_blocks": [],
        }

        result = extract_from_image(img_path)
        assert "https://qr-target.com" in result.qr_codes
        assert "https://qr-target.com" in result.urls  # QR URLs added to URL list

    @patch("src.extractor._run_vision_cli")
    def test_extract_chinese_text(self, mock_vision, tmp_path):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "chinese.jpg")
        _create_test_image(img_path, 640, 480)

        mock_vision.return_value = {
            "text": "今天下午三点开会\n联系人: 张三\n电话: 13912345678",
            "qr_codes": [],
            "text_blocks": [],
        }

        result = extract_from_image(img_path)
        assert "开会" in result.ocr_text
        assert len(result.phones) >= 1

    @patch("src.extractor._run_vision_cli")
    def test_extract_mixed_chinese_english(self, mock_vision, tmp_path):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "mixed.jpg")
        _create_test_image(img_path, 640, 480)

        mock_vision.return_value = {
            "text": "AI Workshop 人工智能研讨会\nhttps://example.com",
            "qr_codes": [],
            "text_blocks": [],
        }

        result = extract_from_image(img_path)
        assert "AI Workshop" in result.ocr_text
        assert "人工智能" in result.ocr_text
        assert len(result.urls) == 1

    @patch("src.extractor._run_vision_cli")
    def test_extract_no_text_returns_empty(self, mock_vision, tmp_path):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "blank.jpg")
        _create_test_image(img_path, 640, 480)

        mock_vision.return_value = {
            "text": "",
            "qr_codes": [],
            "text_blocks": [],
        }

        result = extract_from_image(img_path)
        assert result.ocr_text == ""
        assert result.urls == []

    def test_extract_missing_image(self, tmp_path):
        result = extract_from_image(str(tmp_path / "nonexistent.jpg"))
        assert result.has_data is False

    @patch("src.extractor._run_vision_cli")
    def test_vision_cli_returns_valid_json(self, mock_vision, tmp_path):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "test.jpg")
        _create_test_image(img_path, 640, 480)

        mock_vision.return_value = {
            "text": "Test",
            "qr_codes": [],
            "text_blocks": [{"text": "Test", "confidence": 0.95, "x": 0.1, "y": 0.1, "width": 0.5, "height": 0.1}],
        }

        result = extract_from_image(img_path)
        assert result.ocr_text == "Test"

    @patch("src.extractor._run_vision_cli")
    def test_vision_cli_failure_handled(self, mock_vision, tmp_path):
        from tests.conftest import _create_test_image
        img_path = str(tmp_path / "test.jpg")
        _create_test_image(img_path, 640, 480)

        mock_vision.return_value = None  # Simulates CLI failure

        result = extract_from_image(img_path)
        assert result.ocr_text == ""


class TestDateExtraction:
    """Tests for date extraction patterns."""

    def test_extract_iso_date(self):
        urls = _extract_urls("Date: 2026-04-08")
        # Dates are extracted by analyzer, not extractor regex
        # This test verifies URLs are NOT falsely matched on dates
        assert len(urls) == 0

    def test_various_date_formats_in_ocr(self):
        """Verify OCR text with dates passes through without errors."""
        result = ExtractionResult()
        result.ocr_text = "April 8, 2026\n4/8/26\n2026-04-08\n四月八日"
        assert result.has_data is True
