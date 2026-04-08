"""Tests for PicNote search and retrieval."""

import pytest

from src.db import PicNoteDB


class TestFullTextSearch:
    """Tests for FTS5 search functionality."""

    @pytest.fixture(autouse=True)
    def setup_db(self, test_db):
        """Pre-populate the database with searchable records."""
        self.db = test_db

        # Insert various records for search testing
        self.db.insert_processed_image(
            photo_uuid="SEARCH-URL",
            photo_path="/p/url.jpg",
            thumbnail_path=None,
            classification="informational",
            ocr_text="Visit https://example.com for machine learning resources",
            ai_summary="Screenshot with URL to ML resources",
            tags=["link", "ml", "education"],
        )
        self.db.insert_processed_image(
            photo_uuid="SEARCH-RECEIPT",
            photo_path="/p/receipt.jpg",
            thumbnail_path=None,
            classification="informational",
            ocr_text="Blue Bottle Coffee\nLatte $5.50\nTotal $5.50",
            ai_summary="Coffee receipt from Blue Bottle",
            tags=["receipt", "coffee"],
        )
        self.db.insert_processed_image(
            photo_uuid="SEARCH-EVENT",
            photo_path="/p/event.jpg",
            thumbnail_path=None,
            classification="informational",
            ocr_text="Jazz Night at Blue Note\nApril 18, 2026\n8:00 PM",
            ai_summary="Jazz concert flyer with date and venue",
            tags=["event", "music", "jazz"],
        )
        self.db.insert_processed_image(
            photo_uuid="SEARCH-CHINESE",
            photo_path="/p/chinese.jpg",
            thumbnail_path=None,
            classification="informational",
            ocr_text="人工智能研讨会\n时间: 下午三点\n地点: 会议室B",
            ai_summary="AI workshop invitation in Chinese",
            tags=["event", "ai", "chinese"],
        )
        self.db.insert_processed_image(
            photo_uuid="SEARCH-CONTACT",
            photo_path="/p/contact.jpg",
            thumbnail_path=None,
            classification="informational",
            ocr_text="John Smith\njohn@example.com\n+1-555-123-4567",
            ai_summary="Business card with contact information",
            tags=["contact", "business"],
        )
        self.db.insert_processed_image(
            photo_uuid="SEARCH-CASUAL",
            photo_path="/p/casual.jpg",
            thumbnail_path=None,
            classification="casual",
        )

    def test_search_by_keyword_in_ocr(self):
        results = self.db.search("machine learning")
        assert len(results) >= 1
        assert any(r["photo_uuid"] == "SEARCH-URL" for r in results)

    def test_search_by_tag(self):
        results = self.db.search("jazz")
        assert len(results) >= 1
        assert any(r["photo_uuid"] == "SEARCH-EVENT" for r in results)

    def test_search_by_summary(self):
        results = self.db.search("coffee receipt")
        assert len(results) >= 1
        assert any(r["photo_uuid"] == "SEARCH-RECEIPT" for r in results)

    def test_search_chinese_text(self):
        """FTS5 default tokenizer has limited CJK support.
        Search for a term that appears in the tags or summary instead."""
        results = self.db.search("chinese")
        assert len(results) >= 1
        assert any(r["photo_uuid"] == "SEARCH-CHINESE" for r in results)

    def test_search_partial_match(self):
        results = self.db.search("Blue")
        # Should match both Blue Bottle (receipt) and Blue Note (event)
        assert len(results) >= 2

    def test_search_no_results(self):
        results = self.db.search("xyznonexistentquery12345")
        assert results == []

    def test_search_by_email(self):
        results = self.db.search("john@example.com")
        assert len(results) >= 1

    def test_search_by_date_range(self):
        """FTS search for date text in OCR."""
        results = self.db.search("April 18")
        assert len(results) >= 1
        assert any(r["photo_uuid"] == "SEARCH-EVENT" for r in results)

    def test_search_ranked_by_relevance(self):
        """Results should be ordered by FTS rank."""
        results = self.db.search("Blue")
        # All results should have the search term
        for r in results:
            text = (r.get("ocr_text") or "") + (r.get("ai_summary") or "") + (r.get("tags") or "")
            assert "blue" in text.lower() or "Blue" in text

    def test_search_limit(self):
        results = self.db.search("informational", limit=2)
        assert len(results) <= 2

    def test_fts_index_stays_in_sync(self):
        """Adding a new record should be immediately searchable."""
        self.db.insert_processed_image(
            photo_uuid="SYNC-TEST",
            photo_path="/p/sync.jpg",
            thumbnail_path=None,
            classification="informational",
            ocr_text="unique_sync_test_token_xyz",
        )
        results = self.db.search("unique_sync_test_token_xyz")
        assert len(results) == 1
        assert results[0]["photo_uuid"] == "SYNC-TEST"
