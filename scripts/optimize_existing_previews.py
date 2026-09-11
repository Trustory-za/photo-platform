#!/usr/bin/env python3
"""Safely replace oversized archive previews with web-sized versions.

Dry-run is the default. ``--apply`` creates a database + preview backup before
atomically replacing files and updating ``file_size_preview``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR))

from process_image import PREVIEW_MAX_EDGE, _apply_watermark  # noqa: E402
from PIL import Image  # noqa: E402

DEFAULT_BACKUP_ROOT = Path.home() / ".hermes/backups/photo-platform"
DEFAULT_DB_PATH = PROJECT_DIR / "photos.db"


def _oversized(preview_path: Path) -> tuple[bool, tuple[int, int]]:
    with Image.open(preview_path) as image:
        dimensions = image.size
    return max(dimensions) > PREVIEW_MAX_EDGE, dimensions


def _backup_database(connection: sqlite3.Connection, destination: Path) -> None:
    with sqlite3.connect(destination) as backup:
        connection.backup(backup)


def optimise(*, apply: bool, backup_root: Path) -> dict:
    database_path = Path(
        os.environ.get("PHOTO_PLATFORM_DB_PATH") or DEFAULT_DB_PATH
    ).resolve()
    if apply:
        connection = sqlite3.connect(database_path)
    else:
        # A dry-run must not create a journal, change WAL state, or otherwise
        # alter the production database file.
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        "SELECT id, original_path, preview_path, file_size_preview FROM photos ORDER BY id"
    ).fetchall()

    candidates = []
    skipped_missing = []
    for row in rows:
        original = Path(row["original_path"])
        preview = Path(row["preview_path"])
        if not original.exists() or not preview.exists():
            skipped_missing.append(row["id"])
            continue
        needs_resize, dimensions = _oversized(preview)
        if needs_resize:
            candidates.append((row, original, preview, dimensions))

    result = {
        "mode": "apply" if apply else "dry-run",
        "database": str(database_path),
        "photos_scanned": len(rows),
        "candidates": len(candidates),
        "skipped_missing": skipped_missing,
        "max_edge": PREVIEW_MAX_EDGE,
        "bytes_before": sum(preview.stat().st_size for _, _, preview, _ in candidates),
    }
    if not apply or not candidates:
        connection.close()
        return result

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = backup_root / f"preview-optimization-{timestamp}"
    previews_backup = backup_dir / "previews"
    previews_backup.mkdir(parents=True, exist_ok=False)
    _backup_database(connection, backup_dir / "photos.db")

    manifest = []
    replaced = []
    try:
        for row, original, preview, old_dimensions in candidates:
            backup = previews_backup / f"{row['id']}_{preview.name}"
            temporary = preview.with_name(f".{preview.name}.optimized.tmp")
            shutil.copy2(preview, backup)
            _apply_watermark(str(original), str(temporary))
            with Image.open(temporary) as image:
                new_dimensions = image.size
            old_bytes = preview.stat().st_size
            new_bytes = temporary.stat().st_size
            os.replace(temporary, preview)
            replaced.append((preview, backup))
            manifest.append(
                {
                    "id": row["id"],
                    "preview": str(preview),
                    "backup": str(backup),
                    "old_dimensions": old_dimensions,
                    "new_dimensions": new_dimensions,
                    "old_bytes": old_bytes,
                    "new_bytes": new_bytes,
                }
            )

        connection.executemany(
            "UPDATE photos SET file_size_preview = ? WHERE id = ?",
            [(item["new_bytes"], item["id"]) for item in manifest],
        )
        connection.commit()
    except Exception:
        connection.rollback()
        for preview, backup in reversed(replaced):
            shutil.copy2(backup, preview)
        raise
    finally:
        connection.close()

    manifest_path = backup_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    result.update(
        {
            "backup_dir": str(backup_dir),
            "optimized": len(manifest),
            "bytes_after": sum(item["new_bytes"] for item in manifest),
        }
    )
    result["reduction_percent"] = round(
        (1 - result["bytes_after"] / result["bytes_before"]) * 100, 1
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Back up and replace oversized previews (default: report only)",
    )
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=DEFAULT_BACKUP_ROOT,
        help=f"Backup parent directory (default: {DEFAULT_BACKUP_ROOT})",
    )
    args = parser.parse_args()
    print(json.dumps(optimise(apply=args.apply, backup_root=args.backup_root), indent=2))


if __name__ == "__main__":
    main()
