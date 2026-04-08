"""PicNote main entry point — orchestrates the photo processing pipeline.

Called by launchd when Photos.sqlite changes (new photos synced via iCloud).
Can also be run manually: python -m src.main [--reprocess UUID] [--search QUERY]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

from .analyzer import analyze_image
from .classifier import Classification, classify_image
from .config import ensure_output_dirs, load_config
from .db import PicNoteDB
from .extractor import extract_from_image
from .note_generator import generate_note
from .watcher import APPLE_EPOCH, PhotoAsset, get_new_photos

logger = logging.getLogger("picnote")


def setup_logging(log_dir: str):
    """Configure logging to file and stderr."""
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"picnote-{datetime.now().strftime('%Y-%m-%d')}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stderr),
        ],
    )


def process_single_image(
    asset: PhotoAsset,
    db: PicNoteDB,
    config: dict,
    output_paths: dict,
) -> bool:
    """Process a single photo asset through the full pipeline.

    Returns True if a note was created, False if skipped.
    """
    start_time = time.time()
    uuid = asset.uuid

    # Skip if already processed
    if db.is_processed(uuid):
        logger.debug(f"Skipping already processed: {uuid}")
        return False

    # Skip if original file doesn't exist
    if not os.path.exists(asset.file_path):
        logger.warning(f"Original file not found: {asset.file_path}")
        db.log_processing(uuid, "check", "skipped", "File not found")
        return False

    # Stage 1: Classification
    classification = classify_image(asset, config)
    db.log_processing(uuid, "classification", classification,
                      duration_ms=int((time.time() - start_time) * 1000))

    if classification == Classification.CASUAL:
        # Record as processed but casual — no note needed
        db.insert_processed_image(
            photo_uuid=uuid,
            photo_path=asset.file_path,
            thumbnail_path=None,
            classification=classification,
            source_type="screenshot" if asset.is_screenshot else "photo",
            captured_at=asset.captured_at.isoformat() if asset.captured_at else None,
        )
        logger.info(f"Skipped casual image: {uuid} ({asset.filename})")
        return False

    # Stage 2: OCR + Extraction
    extraction_start = time.time()
    extraction = extract_from_image(asset.file_path)
    db.log_processing(uuid, "extraction", "success" if extraction.has_data else "empty",
                      duration_ms=int((time.time() - extraction_start) * 1000))

    # Stage 3: AI Analysis (only for informational images)
    analysis_start = time.time()
    analysis = analyze_image(asset.file_path, extraction, config)
    db.log_processing(uuid, "analysis", "success" if analysis else "failed",
                      duration_ms=int((time.time() - analysis_start) * 1000))

    # Stage 4: Note Generation
    note_start = time.time()
    note_path = generate_note(asset, extraction, analysis, config, output_paths)
    db.log_processing(uuid, "note_generation", "success",
                      duration_ms=int((time.time() - note_start) * 1000))

    # Record in database
    db.insert_processed_image(
        photo_uuid=uuid,
        photo_path=asset.file_path,
        thumbnail_path=None,  # Updated by note_generator
        classification=classification,
        source_type="screenshot" if asset.is_screenshot else "photo",
        ocr_text=extraction.ocr_text,
        structured_data=extraction.to_dict(),
        ai_summary=(analysis or {}).get("summary"),
        tags=(analysis or {}).get("tags"),
        note_path=note_path,
        captured_at=asset.captured_at.isoformat() if asset.captured_at else None,
    )

    total_ms = int((time.time() - start_time) * 1000)
    logger.info(f"Processed {uuid} ({asset.filename}) → {note_path} [{total_ms}ms]")
    return True


def run_pipeline(config: dict):
    """Run the main processing pipeline for new photos."""
    output_paths = ensure_output_dirs(config)
    setup_logging(output_paths["logs_dir"])

    logger.info("PicNote pipeline starting")

    db = PicNoteDB(os.path.join(output_paths["data_dir"], "picnote.db"))
    photos_library = config["photos_library"]

    if not os.path.exists(photos_library):
        logger.error(f"Photos library not found: {photos_library}")
        return

    # Load last processed timestamp from our DB
    # For now, use a simple state file
    state_file = os.path.join(output_paths["data_dir"], "last_timestamp.txt")
    since_timestamp = None
    if os.path.exists(state_file):
        with open(state_file) as f:
            try:
                since_timestamp = float(f.read().strip())
            except ValueError:
                pass

    # Query for new photos
    max_batch = config.get("processing", {}).get("max_batch_size", 50)
    try:
        assets = get_new_photos(photos_library, since_timestamp, limit=max_batch)
    except Exception as e:
        logger.error(f"Failed to query Photos database: {e}")
        return

    if not assets:
        logger.info("No new photos to process")
        return

    logger.info(f"Found {len(assets)} new photos to process")

    # Process each photo
    notes_created = 0
    latest_timestamp = since_timestamp

    for asset in assets:
        try:
            created = process_single_image(asset, db, config, output_paths)
            if created:
                notes_created += 1

            # Track the latest timestamp for next run
            if asset.captured_at:
                ts = (asset.captured_at - APPLE_EPOCH).total_seconds()
                if latest_timestamp is None or ts > latest_timestamp:
                    latest_timestamp = ts

        except Exception as e:
            logger.error(f"Error processing {asset.uuid}: {e}", exc_info=True)
            db.log_processing(asset.uuid, "pipeline", "error", str(e))

    # Save state for next run (atomic write to prevent corruption)
    if latest_timestamp is not None:
        import tempfile
        fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(state_file), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                f.write(str(latest_timestamp))
            os.replace(tmp_path, state_file)  # atomic on POSIX
        except BaseException:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    stats = db.get_stats()
    logger.info(
        f"Pipeline complete: {notes_created} notes created from {len(assets)} photos. "
        f"Total: {stats['total']} processed ({stats['informational']} informational, "
        f"{stats['casual']} casual)"
    )


def search_notes(config: dict, query: str):
    """Search processed notes."""
    output_paths = ensure_output_dirs(config)
    db = PicNoteDB(os.path.join(output_paths["data_dir"], "picnote.db"))

    results = db.search(query)
    if not results:
        print(f"No results for: {query}")
        return

    print(f"Found {len(results)} results for: {query}\n")
    for r in results:
        print(f"  [{r['classification']}] {r['ai_summary'] or r['ocr_text'][:80]}")
        if r['note_path']:
            print(f"  Note: {r['note_path']}")
        print(f"  Captured: {r['captured_at']}")
        print()


def main():
    parser = argparse.ArgumentParser(description="PicNote — AI photo intelligence")
    parser.add_argument("--config", help="Path to config.yaml")
    parser.add_argument("--search", help="Search processed notes")
    parser.add_argument("--stats", action="store_true", help="Show processing stats")
    parser.add_argument("--reprocess", help="Reprocess a specific photo UUID")

    args = parser.parse_args()
    config = load_config(args.config)

    if args.search:
        search_notes(config, args.search)
    elif args.stats:
        output_paths = ensure_output_dirs(config)
        db = PicNoteDB(os.path.join(output_paths["data_dir"], "picnote.db"))
        stats = db.get_stats()
        print(f"Total processed: {stats['total']}")
        print(f"  Informational: {stats['informational']}")
        print(f"  Casual: {stats['casual']}")
    else:
        run_pipeline(config)


if __name__ == "__main__":
    main()
