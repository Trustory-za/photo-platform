#!/usr/bin/env python3
"""
database.py — SQLite database layer for the Trustory Images photo platform.

Stores every processed image with its full IPTC metadata so we can
search and serve photos.

Usage:
    import database
    database.insert_photo(result_dict)
    photos = database.search_photos("cape town")
    photo = database.get_photo(1)
    all_photos = database.list_all_photos()
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── Database path ───────────────────────────────────────────────────────

DB_PATH = Path(__file__).resolve().parent / "photos.db"


# ── Connection helpers ──────────────────────────────────────────────────

def _get_connection() -> sqlite3.Connection:
    """Get a connection to the SQLite database (gets created on first call)."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # better concurrent read perf
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db() -> None:
    """Create the photos table if it does not already exist."""
    sql = """
    CREATE TABLE IF NOT EXISTS photos (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        filename            TEXT    NOT NULL,
        original_path       TEXT    NOT NULL,
        preview_path        TEXT    NOT NULL,
        file_size_original   INTEGER,
        file_size_preview    INTEGER,
        processed_at        TEXT,
        caption             TEXT,
        keywords            TEXT,
        byline              TEXT,
        copyright           TEXT,
        city                TEXT,
        country             TEXT,
        headline            TEXT,
        source              TEXT,
        full_iptc           TEXT,
        search_text         TEXT
    );
    """
    conn = _get_connection()
    conn.execute(sql)
    conn.commit()
    conn.close()


# ── Core functions ──────────────────────────────────────────────────────

def insert_photo(result: dict[str, Any]) -> int:
    """Insert a processed photo into the database.

    Args:
        result: The dict returned by process_image.py (must have
                success=True).

    Returns:
        The row ID of the newly inserted record.

    Raises:
        ValueError: If the result dict indicates failure.
    """
    if not result.get("success"):
        raise ValueError("Cannot insert a failed result into the database.")

    iptc = result.get("iptc", {})

    # Extract individual IPTC fields
    caption = _first_str(iptc.get("caption/abstract"))
    keywords_list = _flatten_list(iptc.get("keywords", []))
    keywords = ", ".join(keywords_list) if keywords_list else None
    byline = _first_str(iptc.get("by-line"))
    copyright_ = _first_str(iptc.get("copyright notice"))
    city = _first_str(iptc.get("city"))
    country = _first_str(iptc.get("country"))
    headline = _first_str(iptc.get("headline"))
    source = _first_str(iptc.get("source"))

    # Build search_text — combine all text fields for easy searching
    search_parts = [
        caption or "",
        headline or "",
        byline or "",
        city or "",
        country or "",
        " ".join(keywords_list) if keywords_list else "",
    ]
    search_text = " ".join(p.strip() for p in search_parts if p.strip())

    # Full IPTC dump as JSON
    full_iptc = json.dumps(iptc, ensure_ascii=False, default=str)

    # Derive filename from the original_path (strips "original_" prefix)
    filename = _derive_filename(result)

    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO photos (
                filename, original_path, preview_path,
                file_size_original, file_size_preview, processed_at,
                caption, keywords, byline, copyright, city, country,
                headline, source, full_iptc, search_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                filename,
                result.get("original_path", ""),
                result.get("preview_path", ""),
                result.get("file_size_original"),
                result.get("file_size_preview"),
                result.get("processed_at"),
                caption,
                keywords,
                byline,
                copyright_,
                city,
                country,
                headline,
                source,
                full_iptc,
                search_text,
            ),
        )
        conn.commit()
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("Database insert succeeded but returned no row ID.")
    finally:
        conn.close()

    return row_id


def _derive_filename(result: dict[str, Any]) -> str:
    """Try to extract a clean filename from the result dict."""
    orig = result.get("original_path", "")
    if orig:
        return Path(orig).name.replace("original_", "", 1)
    prev = result.get("preview_path", "")
    if prev:
        return Path(prev).name.replace("preview_", "", 1)
    return "unknown"


def search_photos(query: str) -> list[dict[str, Any]]:
    """Search photos by text query.

    Performs a case-insensitive LIKE search across the search_text column.
    Multi-word queries match all words (AND logic).

    Args:
        query: The search string.

    Returns:
        List of photo dicts ordered by processed_at DESC.
    """
    terms = query.strip().split()
    if not terms:
        return []

    conditions = " AND ".join("search_text LIKE ?" for _ in terms)
    params = [f"%{term}%" for term in terms]

    sql = f"""
        SELECT * FROM photos
        WHERE {conditions}
        ORDER BY processed_at DESC
    """

    conn = _get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_photo(photo_id: int) -> Optional[dict[str, Any]]:
    """Get a single photo by its database ID.

    Args:
        photo_id: The primary key of the photo.

    Returns:
        A dict of the photo row, or None if not found.
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM photos WHERE id = ?", (photo_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_all_photos() -> list[dict[str, Any]]:
    """Return every photo in the database.

    Returns:
        List of photo dicts ordered by processed_at DESC.
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM photos ORDER BY processed_at DESC"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


# ── Internal helpers ────────────────────────────────────────────────────

def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a sqlite3.Row to a plain dict, decoding full_iptc if present."""
    d = dict(row)
    if d.get("full_iptc"):
        try:
            d["full_iptc"] = json.loads(d["full_iptc"])
        except (json.JSONDecodeError, TypeError):
            pass  # leave as string if it can't be decoded
    return d


def _first_str(value: Any) -> Optional[str]:
    """Return the first string from a value that could be str, list, or None."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (list, tuple)) and len(value) > 0:
        v = value[0]
        return str(v).strip() if v else None
    return str(value).strip() or None


def _flatten_list(value: Any) -> list[str]:
    """Flatten a value into a list of non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if v and str(v).strip()]
    return [str(value).strip()] if str(value).strip() else []


# ── Initialise on import ────────────────────────────────────────────────

_init_db()