"""PicNote text and data extraction — OCR via Apple Vision + regex parsing."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime

logger = logging.getLogger(__name__)

# Regex patterns for structured data extraction
URL_PATTERN = re.compile(
    r'https?://[^\s<>"\')\]]+|www\.[^\s<>"\')\]]+',
    re.IGNORECASE,
)

EMAIL_PATTERN = re.compile(
    r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
)

PHONE_PATTERN = re.compile(
    r'(?:\+?1[-.\s]?)?(?:\(?[0-9]{3}\)?[-.\s]?)?[0-9]{3}[-.\s]?[0-9]{4}'
    r'|(?:\+?86[-.\s]?)?1[3-9][0-9]{9}'  # Chinese mobile
    r'|(?:\+?[0-9]{1,3}[-.\s]?)?[0-9]{2,4}[-.\s]?[0-9]{3,4}[-.\s]?[0-9]{3,4}',
)

MONEY_PATTERN = re.compile(
    r'[$¥€£]\s*[\d,]+\.?\d*'
    r'|\d+\.?\d*\s*(?:USD|CNY|EUR|GBP|元|块)',
    re.IGNORECASE,
)


class ExtractionResult:
    """Container for extraction results from an image."""

    def __init__(self):
        self.ocr_text: str = ""
        self.urls: list[str] = []
        self.qr_codes: list[str] = []
        self.emails: list[str] = []
        self.phones: list[str] = []
        self.dates: list[str] = []
        self.amounts: list[str] = []

    def to_dict(self) -> dict:
        return {
            "urls": self.urls,
            "qr_codes": self.qr_codes,
            "emails": self.emails,
            "phones": self.phones,
            "dates": self.dates,
            "amounts": self.amounts,
        }

    @property
    def has_data(self) -> bool:
        return bool(
            self.urls or self.qr_codes or self.emails
            or self.phones or self.dates or self.amounts
            or self.ocr_text.strip()
        )


def extract_from_image(image_path: str, swift_cli_path: str | None = None) -> ExtractionResult:
    """Extract text and structured data from an image.

    Uses the Swift Vision CLI helper for OCR and QR code detection,
    then applies regex patterns for structured data extraction.
    """
    result = ExtractionResult()

    if not os.path.exists(image_path):
        logger.error(f"Image not found: {image_path}")
        return result

    # Run Swift Vision CLI for OCR + QR codes
    vision_output = _run_vision_cli(image_path, swift_cli_path)

    if vision_output:
        result.ocr_text = vision_output.get("text", "")
        result.qr_codes = vision_output.get("qr_codes", [])

    # Extract structured data from OCR text
    if result.ocr_text:
        result.urls = _extract_urls(result.ocr_text)
        result.emails = _extract_emails(result.ocr_text)
        result.phones = _extract_phones(result.ocr_text)
        result.amounts = _extract_amounts(result.ocr_text)

    # Add QR code URLs to URL list
    for qr in result.qr_codes:
        if qr.startswith("http") and qr not in result.urls:
            result.urls.append(qr)

    return result


def _run_vision_cli(image_path: str, swift_cli_path: str | None = None) -> dict | None:
    """Run the Swift Vision OCR CLI helper."""
    if swift_cli_path is None:
        # Look for compiled binary next to the swift source
        swift_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "swift")
        swift_cli_path = os.path.join(swift_dir, "vision_ocr")

    if not os.path.exists(swift_cli_path):
        logger.warning(f"Vision CLI not found at {swift_cli_path}. Skipping OCR.")
        return None

    try:
        result = subprocess.run(
            [swift_cli_path, image_path],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning(f"Vision CLI failed: {result.stderr}")
            return None

        return json.loads(result.stdout)

    except subprocess.TimeoutExpired:
        logger.warning(f"Vision CLI timed out for {image_path}")
        return None
    except json.JSONDecodeError as e:
        logger.warning(f"Vision CLI returned invalid JSON: {e}")
        return None


def _extract_urls(text: str) -> list[str]:
    """Extract URLs from text."""
    urls = URL_PATTERN.findall(text)
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for url in urls:
        # Clean trailing punctuation
        url = url.rstrip(".,;:!?)")
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def _extract_emails(text: str) -> list[str]:
    """Extract email addresses from text."""
    return list(set(EMAIL_PATTERN.findall(text)))


def _extract_phones(text: str) -> list[str]:
    """Extract phone numbers from text."""
    phones = PHONE_PATTERN.findall(text)
    # Filter out numbers that are too short (likely not phone numbers)
    return [p for p in set(phones) if len(re.sub(r'\D', '', p)) >= 7]


def _extract_amounts(text: str) -> list[str]:
    """Extract monetary amounts from text."""
    return list(set(MONEY_PATTERN.findall(text)))
