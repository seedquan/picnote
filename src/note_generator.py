"""PicNote Markdown note generator."""

from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime

from PIL import Image

logger = logging.getLogger(__name__)

from .extractor import ExtractionResult
from .watcher import PhotoAsset


def generate_note(
    asset: PhotoAsset,
    extraction: ExtractionResult,
    analysis: dict | None,
    config: dict,
    output_paths: dict,
) -> str:
    """Generate a Markdown note for a processed image.

    Args:
        asset: The photo asset from Apple Photos
        extraction: OCR and structured data extraction results
        analysis: Claude CLI analysis results (may be None)
        config: Application configuration
        output_paths: Output directory paths

    Returns:
        Path to the generated note file.
    """
    # Determine organization
    organize_by = config.get("notes", {}).get("organize_by", "date")
    captured_at = asset.captured_at or datetime.now()

    if organize_by == "date":
        date_dir = captured_at.strftime("%Y/%m/%d")
        note_dir = os.path.join(output_paths["vault_dir"], "daily", date_dir)
    else:
        note_type = (analysis or {}).get("type", "note")
        note_dir = os.path.join(output_paths["vault_dir"], note_type)

    os.makedirs(note_dir, exist_ok=True)

    # Generate title and filename
    title = (analysis or {}).get("title", _default_title(asset))
    filename = _slugify(title) + ".md"
    note_path = os.path.join(note_dir, filename)

    # Handle duplicate filenames
    note_path = _ensure_unique_path(note_path)

    # Copy thumbnail
    thumbnail_path = _create_thumbnail(asset, captured_at, config, output_paths)
    thumbnail_rel = os.path.relpath(thumbnail_path, output_paths["vault_dir"]) if thumbnail_path else None

    # Build note content
    content = _build_note_content(
        asset=asset,
        extraction=extraction,
        analysis=analysis,
        title=title,
        captured_at=captured_at,
        thumbnail_rel=thumbnail_rel,
    )

    with open(note_path, "w", encoding="utf-8") as f:
        f.write(content)

    return note_path


def _build_note_content(
    asset: PhotoAsset,
    extraction: ExtractionResult,
    analysis: dict | None,
    title: str,
    captured_at: datetime,
    thumbnail_rel: str | None,
) -> str:
    """Build the Markdown content for a note."""
    lines = []

    # Header
    note_type = (analysis or {}).get("type", "note")
    tags = (analysis or {}).get("tags", [])
    tag_str = " ".join(f"#{t}" for t in tags) if tags else ""

    lines.append(f"# {title}")
    lines.append(f"**Captured**: {captured_at.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Type**: {note_type}")
    if tag_str:
        lines.append(f"**Tags**: {tag_str}")
    lines.append("")

    # Source section
    lines.append("## Source")
    lines.append(f"- **Photo UUID**: {asset.uuid}")
    lines.append(f"- **Original path**: {asset.file_path}")
    source_type = "screenshot" if asset.is_screenshot else "photo"
    lines.append(f"- **Source type**: {source_type}")
    lines.append("")

    # Summary
    summary = (analysis or {}).get("summary", "")
    if summary:
        lines.append("## Summary")
        lines.append(summary)
        lines.append("")

    # Extracted Data
    has_extracted = (
        extraction.urls or extraction.qr_codes or extraction.emails
        or extraction.phones or extraction.amounts
        or (analysis or {}).get("dates")
        or (analysis or {}).get("contacts")
        or (analysis or {}).get("action_items")
    )

    if has_extracted:
        lines.append("## Extracted Data")

        if extraction.urls:
            lines.append("**URLs**:")
            for url in extraction.urls:
                lines.append(f"- {url}")

        if extraction.qr_codes:
            lines.append("**QR Codes**:")
            for qr in extraction.qr_codes:
                lines.append(f"- {qr}")

        if extraction.emails:
            lines.append("**Emails**:")
            for email in extraction.emails:
                lines.append(f"- {email}")

        if extraction.phones:
            lines.append("**Phones**:")
            for phone in extraction.phones:
                lines.append(f"- {phone}")

        if extraction.amounts:
            lines.append("**Amounts**:")
            for amount in extraction.amounts:
                lines.append(f"- {amount}")

        analysis_dates = (analysis or {}).get("dates", [])
        if analysis_dates:
            lines.append("**Dates**:")
            for d in analysis_dates:
                lines.append(f"- {d}")

        analysis_contacts = (analysis or {}).get("contacts", [])
        if analysis_contacts:
            lines.append("**Contacts**:")
            for c in analysis_contacts:
                lines.append(f"- {c}")

        action_items = (analysis or {}).get("action_items", [])
        if action_items:
            lines.append("**Action Items**:")
            for item in action_items:
                lines.append(f"- [ ] {item}")

        lines.append("")

    # Raw Text
    if extraction.ocr_text.strip():
        lines.append("## Raw Text")
        lines.append("```")
        lines.append(extraction.ocr_text.strip())
        lines.append("```")
        lines.append("")

    # Thumbnail
    if thumbnail_rel:
        lines.append("## Thumbnail")
        lines.append(f"![[{thumbnail_rel}]]")
        lines.append("")

    return "\n".join(lines)


def _create_thumbnail(
    asset: PhotoAsset,
    captured_at: datetime,
    config: dict,
    output_paths: dict,
) -> str | None:
    """Create a thumbnail copy of the image. NEVER modifies the original."""
    if not os.path.exists(asset.file_path):
        return None

    date_dir = captured_at.strftime("%Y/%m/%d")
    thumb_dir = os.path.join(output_paths["assets_dir"], date_dir)
    os.makedirs(thumb_dir, exist_ok=True)

    thumb_filename = f"{asset.uuid}-thumb.jpg"
    thumb_path = os.path.join(thumb_dir, thumb_filename)

    if os.path.exists(thumb_path):
        return thumb_path

    processing = config.get("processing", {})
    max_size = processing.get("thumbnail_size", 800)
    quality = processing.get("thumbnail_quality", 85)

    try:
        with Image.open(asset.file_path) as img:
            img.thumbnail((max_size, max_size))
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            img.save(thumb_path, "JPEG", quality=quality)
        return thumb_path
    except Exception as e:
        logger.warning(f"Thumbnail creation failed for {asset.uuid}: {e}")
        try:
            shutil.copy2(asset.file_path, thumb_path)
            logger.info(f"Fell back to copying original for {asset.uuid}")
            return thumb_path
        except Exception as copy_err:
            logger.error(f"Thumbnail fallback copy also failed for {asset.uuid}: {copy_err}")
            return None


def _default_title(asset: PhotoAsset) -> str:
    """Generate a default title from the asset."""
    name = os.path.splitext(asset.filename)[0]
    if asset.is_screenshot:
        return f"Screenshot {name}"
    return f"Photo {name}"


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    # Replace non-alphanumeric chars (keeping CJK characters)
    slug = re.sub(r'[^\w\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff-]', '-', text)
    slug = re.sub(r'-+', '-', slug)
    slug = slug.strip('-').lower()
    return slug[:80] if slug else "untitled"


def _ensure_unique_path(path: str) -> str:
    """Ensure the file path is unique by appending -2, -3, etc."""
    if not os.path.exists(path):
        return path

    base, ext = os.path.splitext(path)
    counter = 2
    while os.path.exists(f"{base}-{counter}{ext}"):
        counter += 1
    return f"{base}-{counter}{ext}"
