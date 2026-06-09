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
    conn.execute(_PURCHASES_SCHEMA)
    conn.commit()
    conn.close()


# ── Purchases table schema ──────────────────────────────────────────

_PURCHASES_SCHEMA = """
CREATE TABLE IF NOT EXISTS purchases (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id          INTEGER NOT NULL,
    paystack_reference TEXT   NOT NULL UNIQUE,
    email             TEXT    NOT NULL,
    amount_zar        INTEGER NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'pending',
    download_token    TEXT    UNIQUE,
    created_at        TEXT    NOT NULL,
    paid_at           TEXT,
    FOREIGN KEY (photo_id) REFERENCES photos(id)
);
"""


# ── Purchase functions ──────────────────────────────────────────────

def create_purchase(photo_id: int, email: str, reference: str, amount_zar: int = 15000) -> int:
    """Insert a pending purchase row.

    Args:
        photo_id: The ID of the photo being purchased.
        email: The buyer's email address.
        reference: The Paystack transaction reference (must be unique).
        amount_zar: The price in cents (default R150.00 = 15000).

    Returns:
        The row ID of the newly inserted purchase.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO purchases (photo_id, paystack_reference, email, amount_zar, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (photo_id, reference, email, amount_zar, now),
        )
        conn.commit()
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("Purchase insert succeeded but returned no row ID.")
        return row_id
    finally:
        conn.close()


def confirm_purchase(reference: str, download_token: str) -> Optional[int]:
    """Mark a purchase as paid.

    Sets status to 'paid', records paid_at timestamp, and stores the
    download token.

    Args:
        reference: The Paystack transaction reference.
        download_token: A unique UUID string for download access.

    Returns:
        The purchase ID if found and updated, or None if not found.
    """
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            UPDATE purchases
            SET status = 'paid', paid_at = ?, download_token = ?
            WHERE paystack_reference = ? AND status = 'pending'
            """,
            (now, download_token, reference),
        )
        conn.commit()
        if cursor.rowcount == 0:
            return None
        row = conn.execute(
            "SELECT id FROM purchases WHERE paystack_reference = ?",
            (reference,),
        ).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def get_purchase_by_token(token: str) -> Optional[dict[str, Any]]:
    """Look up a purchase by its download token.

    Args:
        token: The unique download token UUID.

    Returns:
        A dict of the purchase row, or None if not found.
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM purchases WHERE download_token = ?", (token,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_purchase_by_reference(reference: str) -> Optional[dict[str, Any]]:
    """Look up a purchase by its Paystack transaction reference.

    Args:
        reference: The Paystack transaction reference.

    Returns:
        A dict of the purchase row, or None if not found.
    """
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM purchases WHERE paystack_reference = ?", (reference,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def mark_downloaded(token: str) -> bool:
    """Mark a download token as used (status = 'downloaded').

    Args:
        token: The download token.

    Returns:
        True if updated, False if not found.
    """
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "UPDATE purchases SET status = 'downloaded' WHERE download_token = ? AND status = 'paid'",
            (token,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
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


def count_photos() -> int:
    """Return the total number of photos in the database."""
    conn = _get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM photos").fetchone()
        return row["cnt"] if row else 0
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


def _decode_bytes(value: Any) -> Any:
    """Decode bytes to str, handling both raw bytes and their repr form.

    IPTC fields from Pillow's IptcImagePlugin come back as bytes objects.
    When passed through str() or other operations, they can end up as
    ``b'Charle Lombard'`` instead of ``Charle Lombard``.
    """
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    if isinstance(value, str) and value.startswith("b'") and value.endswith("'"):
        return value[2:-1]
    return value


def _first_str(value: Any) -> Optional[str]:
    """Return the first string from a value that could be str, list, or None."""
    if value is None:
        return None
    # Decode bytes before processing
    value = _decode_bytes(value)
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (list, tuple)) and len(value) > 0:
        v = value[0]
        v = _decode_bytes(v)
        return str(v).strip() if v else None
    return str(value).strip() or None


def _flatten_list(value: Any) -> list[str]:
    """Flatten a value into a list of non-empty strings."""
    if value is None:
        return []
    # Decode bytes before processing
    value = _decode_bytes(value)
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        result = []
        for v in value:
            v = _decode_bytes(v)
            if v and str(v).strip():
                result.append(str(v).strip())
        return result
    return [str(value).strip()] if str(value).strip() else []


# ── Initialise on import ────────────────────────────────────────────────

_init_db()