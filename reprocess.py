#!/usr/bin/env python3
"""Reprocess all photos: clear DB, process from originals, insert fresh."""

import json
import os
import shutil
import sys
from pathlib import Path

# ── Set up paths ────────────────────────────────────────────────────────────
BASE = Path("/home/trusty/projects/photo-platform")
sys.path.insert(0, str(BASE))

os.chdir(str(BASE))

INCOMING = BASE / "uploads" / "incoming"
PROCESSED = BASE / "uploads" / "processed"
DB_PATH = BASE / "photos.db"

# ── 1. Clear processed folder ──────────────────────────────────────────────
print("=== Step 1: Clearing processed folder ===")
if PROCESSED.exists():
    shutil.rmtree(str(PROCESSED))
PROCESSED.mkdir(parents=True, exist_ok=True)
print(f"  Cleared: {PROCESSED}")

# ── 2. Delete old DB ───────────────────────────────────────────────────────
print("=== Step 2: Resetting database ===")
if DB_PATH.exists():
    DB_PATH.unlink()
    print(f"  Deleted: {DB_PATH}")
import database
database._init_db()
print(f"  Database initialised (with event column)")
# Verify schema
conn = database._get_connection()
cols = [row[1] for row in conn.execute("PRAGMA table_info(photos)").fetchall()]
conn.close()
print(f"  Columns: {', '.join(cols)}")
assert "event" in cols, "ERROR: event column not in schema!"

# ── 3. Process each file ───────────────────────────────────────────────────
print("\n=== Step 3: Processing files ===")
import process_image

jpg_files = sorted(INCOMING.glob("*.JPG")) + sorted(INCOMING.glob("*.jpg"))
success_count = 0
fail_count = 0

for f in jpg_files:
    if f.name == "test.jpg":
        print(f"  SKIP  {f.name}")
        continue
    print(f"  -> {f.name} ...", end=" ")
    result = process_image.process_image(str(f), str(PROCESSED))
    if result.get("success"):
        try:
            row_id = database.insert_photo(result)
            print(f"OK  row={row_id}")
            # Print some details
            print(f"     photographer={result.get('photographer','?')}  event={result.get('event','?')}")
            print(f"     original={result.get('original_path','?')}")
            print(f"     preview={result.get('preview_path','?')}")
            success_count += 1
        except Exception as e:
            print(f"DB-ERROR {e}")
            fail_count += 1
    else:
        print(f"FAIL {result.get('error','?')}")
        fail_count += 1

print(f"\n=== Done: {success_count} succeeded, {fail_count} failed ===")