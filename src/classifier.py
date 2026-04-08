"""PicNote image classifier — determines if an image is informational or casual."""

from __future__ import annotations

import logging
import re
import subprocess

from .watcher import PhotoAsset

logger = logging.getLogger(__name__)

# Scene labels that strongly indicate informational content
INFORMATIONAL_SCENES = {
    "document", "whiteboard", "text", "receipt", "menu", "sign",
    "poster", "screen", "monitor", "label", "book", "newspaper",
    "magazine", "letter", "note", "card", "ticket", "map",
    "billboard", "blackboard", "chalkboard",
}

# Scene labels that strongly indicate casual/personal content
CASUAL_SCENES = {
    "selfie", "portrait", "landscape", "sunset", "sunrise", "beach",
    "mountain", "sky", "pet", "cat", "dog", "food", "meal",
    "flower", "garden", "party", "celebration", "sport",
}


class Classification:
    INFORMATIONAL = "informational"
    CASUAL = "casual"
    AMBIGUOUS = "ambiguous"


def classify_image(asset: PhotoAsset, config: dict) -> str:
    """Classify a photo asset as informational or casual.

    Uses a tiered approach:
    1. Local heuristics (free, instant)
    2. Claude Code CLI fallback (for ambiguous cases)

    Returns: 'informational' or 'casual'
    """
    classification_config = config.get("classification", {})

    # Tier 1: Local heuristics
    result = _classify_local(asset, classification_config)

    if result != Classification.AMBIGUOUS:
        logger.info(f"Classified {asset.uuid} as {result} (local heuristics)")
        return result

    # Tier 2: Claude Code CLI fallback
    if classification_config.get("claude_fallback", True):
        result = _classify_with_claude(asset, config)
        logger.info(f"Classified {asset.uuid} as {result} (Claude CLI)")
        return result

    # Default to informational if no fallback (conservative — process rather than skip)
    logger.info(f"Classified {asset.uuid} as informational (default, no fallback)")
    return Classification.INFORMATIONAL


def _classify_local(asset: PhotoAsset, config: dict) -> str:
    """Classify using local heuristics from Apple Photos metadata."""
    # Rule 1: Screenshots are almost always informational
    if asset.is_screenshot and config.get("auto_process_screenshots", True):
        return Classification.INFORMATIONAL

    # Rule 2: Has text content detected by Apple → likely informational
    if asset.has_text:
        # But if it also has faces and no other informational signals, it might be a chat screenshot
        if asset.face_count > 0 and not asset.is_screenshot:
            return Classification.AMBIGUOUS
        return Classification.INFORMATIONAL

    # Rule 3: Scene labels
    informational_matches = set(asset.scene_labels) & INFORMATIONAL_SCENES
    casual_matches = set(asset.scene_labels) & CASUAL_SCENES

    if informational_matches and not casual_matches:
        return Classification.INFORMATIONAL

    if casual_matches and not informational_matches:
        return Classification.CASUAL

    # Rule 4: Faces only, no text → casual
    if asset.face_count > 0 and not asset.has_text and config.get("skip_faces_only", True):
        return Classification.CASUAL

    # Rule 5: No signals at all
    if not asset.scene_labels and not asset.has_text and asset.face_count == 0:
        return Classification.AMBIGUOUS

    return Classification.AMBIGUOUS


def _classify_with_claude(asset: PhotoAsset, config: dict | None = None) -> str:
    """Use Claude Code CLI to classify an ambiguous image."""
    if not asset.file_path:
        return Classification.INFORMATIONAL

    prompt = (
        "Look at this image. Is it INFORMATIONAL (contains text, schedule, URL, QR code, "
        "receipt, document, whiteboard, contact info, event details, or any useful data to remember) "
        "or CASUAL (selfie, family photo, scenery, food, pet, social moment)? "
        "Reply with exactly one word: INFORMATIONAL or CASUAL"
    )

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--image", asset.file_path, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=(config or {}).get("processing", {}).get("claude_timeout_classify", 30),
        )

        if result.returncode != 0:
            logger.warning(f"Claude CLI failed for {asset.uuid}: {result.stderr}")
            return Classification.INFORMATIONAL  # Default to processing

        response = result.stdout.strip().upper()
        if re.search(r"\bINFORMATIONAL\b", response):
            return Classification.INFORMATIONAL
        elif re.search(r"\bCASUAL\b", response):
            return Classification.CASUAL
        else:
            logger.warning(f"Unexpected Claude response for {asset.uuid}: {response}")
            return Classification.INFORMATIONAL

    except subprocess.TimeoutExpired:
        logger.warning(f"Claude CLI timed out for {asset.uuid}")
        return Classification.INFORMATIONAL
    except FileNotFoundError:
        logger.error("Claude CLI not found. Install Claude Code CLI.")
        return Classification.INFORMATIONAL
