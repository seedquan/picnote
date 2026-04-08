"""PicNote Claude Code CLI analyzer — deep image analysis."""

from __future__ import annotations

import json
import logging
import re
import subprocess

from .extractor import ExtractionResult

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """Analyze this image and extract structured information. You are given OCR text that was already extracted from the image.

OCR Text:
{ocr_text}

Already extracted data:
{extracted_data}

Based on the image and the OCR text, provide a JSON response with these fields:
{{
    "title": "A concise descriptive title for this capture (under 60 chars)",
    "summary": "2-3 sentence summary of what this image contains and why it might be useful",
    "type": "one of: receipt, event, link, contact, note, code, document",
    "tags": ["list", "of", "relevant", "tags"],
    "urls": ["any additional URLs found"],
    "dates": ["any dates/times found, in ISO format when possible"],
    "contacts": ["any contact info found"],
    "action_items": ["any action items or things to remember"]
}}

Respond with ONLY the JSON object, no other text."""


def analyze_image(
    image_path: str,
    extraction_result: ExtractionResult,
    config: dict,
) -> dict | None:
    """Use Claude Code CLI to perform deep analysis on an informational image.

    Args:
        image_path: Path to the image (thumbnail, not original)
        extraction_result: Already-extracted OCR text and structured data
        config: Application configuration

    Returns:
        Analysis dict with title, summary, type, tags, etc. or None on failure.
    """
    # Check for sensitive content (normalize OCR text for robust matching)
    sensitive_keywords = config.get("sensitive_keywords", [])
    # Normalize: collapse whitespace, remove zero-width chars for robust matching
    ocr_normalized = re.sub(r'[\s\u200b\u200c\u200d\ufeff]+', '', extraction_result.ocr_text.lower())
    ocr_lower = extraction_result.ocr_text.lower()
    for keyword in sensitive_keywords:
        kw_lower = keyword.lower()
        kw_collapsed = re.sub(r'\s+', '', kw_lower)
        if kw_lower in ocr_lower or kw_collapsed in ocr_normalized:
            logger.info(f"Sensitive content detected ('{keyword}'), skipping cloud analysis")
            return _generate_local_analysis(extraction_result)

    prompt = ANALYSIS_PROMPT.format(
        ocr_text=extraction_result.ocr_text[:2000],  # Limit OCR text size
        extracted_data=json.dumps(extraction_result.to_dict(), indent=2),
    )

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--image", image_path, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=config.get("processing", {}).get("claude_timeout_analyze", 60),
        )

        if result.returncode != 0:
            logger.warning(f"Claude CLI analysis failed: {result.stderr}")
            return _generate_local_analysis(extraction_result)

        response = result.stdout.strip()
        # Try to parse JSON from response (may have markdown code fences)
        return _parse_json_response(response)

    except subprocess.TimeoutExpired:
        logger.warning("Claude CLI analysis timed out")
        return _generate_local_analysis(extraction_result)
    except FileNotFoundError:
        logger.error("Claude CLI not found. Install Claude Code CLI.")
        return _generate_local_analysis(extraction_result)


def _parse_json_response(response: str) -> dict | None:
    """Parse JSON from Claude's response, handling code fences."""
    # Try to extract from markdown code fences first (regex handles nested backticks)
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", response, re.DOTALL)
    if match:
        candidate = match.group(1).strip()
    else:
        candidate = response.strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse Claude response as JSON: {response[:200]}")
        return None


def _generate_local_analysis(extraction_result: ExtractionResult) -> dict:
    """Generate a basic analysis locally when Claude CLI is unavailable or skipped."""
    # Determine type from extracted data
    note_type = "note"
    if extraction_result.amounts:
        note_type = "receipt"
    elif extraction_result.qr_codes:
        note_type = "code"
    elif extraction_result.urls:
        note_type = "link"
    elif extraction_result.emails or extraction_result.phones:
        note_type = "contact"

    # Generate a basic title from first line of OCR text
    first_line = extraction_result.ocr_text.split("\n")[0][:60] if extraction_result.ocr_text else "Untitled capture"

    return {
        "title": first_line,
        "summary": f"Captured {note_type} with extracted text content.",
        "type": note_type,
        "tags": [note_type],
        "urls": extraction_result.urls,
        "dates": extraction_result.dates,
        "contacts": extraction_result.emails + extraction_result.phones,
        "action_items": [],
    }
