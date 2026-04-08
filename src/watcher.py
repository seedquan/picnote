"""PicNote Photos.sqlite reader — queries for new photos. STRICTLY READ-ONLY."""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# Apple's Core Data epoch: 2001-01-01 00:00:00 UTC
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)


@dataclass
class PhotoAsset:
    """Represents a photo asset from the Apple Photos library."""

    uuid: str
    filename: str
    directory: str
    file_path: str
    is_screenshot: bool
    scene_labels: list[str]
    has_text: bool
    face_count: int
    captured_at: datetime | None
    width: int
    height: int


def apple_timestamp_to_datetime(timestamp: float | None) -> datetime | None:
    """Convert Apple Core Data timestamp to Python datetime."""
    if timestamp is None:
        return None
    from datetime import timedelta

    return APPLE_EPOCH + timedelta(seconds=timestamp)


def open_photos_db_readonly(photos_library: str) -> sqlite3.Connection:
    """Open Photos.sqlite in STRICTLY read-only mode.

    Uses SQLite URI with mode=ro to guarantee no writes can occur.
    Raises sqlite3.OperationalError if the database cannot be opened.
    """
    db_path = os.path.join(photos_library, "database", "Photos.sqlite")
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Photos database not found: {db_path}")

    # URI mode=ro ensures read-only access at the SQLite level
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_new_photos(
    photos_library: str,
    since_timestamp: float | None = None,
    limit: int = 50,
) -> list[PhotoAsset]:
    """Query Photos.sqlite for new photo assets since a given timestamp.

    Args:
        photos_library: Path to the Photos Library .photoslibrary directory
        since_timestamp: Apple Core Data timestamp to query from (None = get all)
        limit: Maximum number of results

    Returns:
        List of PhotoAsset objects for new photos
    """
    conn = open_photos_db_readonly(photos_library)
    try:
        return _query_assets(conn, photos_library, since_timestamp, limit)
    finally:
        conn.close()


def _query_assets(
    conn: sqlite3.Connection,
    photos_library: str,
    since_timestamp: float | None,
    limit: int,
) -> list[PhotoAsset]:
    """Query ZASSET table for photo assets."""
    # Build query — we need basic asset info plus classification metadata
    query = """
        SELECT
            a.ZUUID,
            a.ZFILENAME,
            a.ZDIRECTORY,
            a.ZDATECREATED,
            a.ZWIDTH,
            a.ZHEIGHT,
            COALESCE(aa.ZISDETECTEDSCREENSHOT, 0) as is_screenshot,
            COALESCE(aa.ZCHARACTERRECOGNITIONATTRIBUTES, 0) as has_ocr
        FROM ZASSET a
        LEFT JOIN ZADDITIONALASSETATTRIBUTES aa ON a.Z_PK = aa.ZASSET
        WHERE a.ZTRASHEDSTATE = 0
    """
    params = []

    if since_timestamp is not None:
        query += " AND a.ZDATECREATED > ?"
        params.append(since_timestamp)

    query += " ORDER BY a.ZDATECREATED DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(query, params)
    assets = []

    for row in cursor:
        uuid = row["ZUUID"]
        filename = row["ZFILENAME"]
        directory = row["ZDIRECTORY"] or ""

        # Resolve actual file path (with traversal protection)
        file_path = os.path.join(
            photos_library, "originals", directory, filename
        )
        # Defense-in-depth: ensure resolved path stays within library
        real_path = os.path.realpath(file_path)
        real_library = os.path.realpath(photos_library)
        if not real_path.startswith(real_library + os.sep) and real_path != real_library:
            logger.warning(f"Path traversal detected for {uuid}: {file_path}")
            continue

        # Get scene labels if available
        scene_labels = _get_scene_labels(conn, uuid)
        face_count = _get_face_count(conn, uuid)

        asset = PhotoAsset(
            uuid=uuid,
            filename=filename,
            directory=directory,
            file_path=file_path,
            is_screenshot=bool(row["is_screenshot"]),
            scene_labels=scene_labels,
            has_text=bool(row["has_ocr"]),
            face_count=face_count,
            captured_at=apple_timestamp_to_datetime(row["ZDATECREATED"]),
            width=row["ZWIDTH"] or 0,
            height=row["ZHEIGHT"] or 0,
        )
        assets.append(asset)

    return assets


def _get_scene_labels(conn: sqlite3.Connection, asset_uuid: str) -> list[str]:
    """Get scene classification labels for an asset."""
    try:
        cursor = conn.execute(
            """SELECT sc.ZLABEL
            FROM ZSCENECLASSIFICATION sc
            JOIN ZASSET a ON sc.ZASSET = a.Z_PK
            WHERE a.ZUUID = ? AND sc.ZCONFIDENCE > 0.5""",
            (asset_uuid,),
        )
        return [row["ZLABEL"] for row in cursor]
    except sqlite3.OperationalError:
        # Table might not exist in all Photos.sqlite versions
        return []


def _get_face_count(conn: sqlite3.Connection, asset_uuid: str) -> int:
    """Get the number of detected faces in an asset."""
    try:
        cursor = conn.execute(
            """SELECT COUNT(*) as cnt
            FROM ZDETECTEDFACE df
            JOIN ZASSET a ON df.ZASSET = a.Z_PK
            WHERE a.ZUUID = ?""",
            (asset_uuid,),
        )
        row = cursor.fetchone()
        return row["cnt"] if row else 0
    except sqlite3.OperationalError:
        return 0


def get_last_processed_timestamp(photos_library: str) -> float | None:
    """Get the Apple timestamp of the most recent photo in the library.

    Useful for determining the 'since' parameter for the next query.
    """
    conn = open_photos_db_readonly(photos_library)
    try:
        cursor = conn.execute(
            "SELECT MAX(ZDATECREATED) FROM ZASSET WHERE ZTRASHEDSTATE = 0"
        )
        row = cursor.fetchone()
        return row[0] if row else None
    finally:
        conn.close()
