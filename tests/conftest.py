"""Shared pytest fixtures for the photo-platform backend test suite.

Tests must never touch the real photos.db — every test that needs photo
data monkeypatches database.list_all_photos() instead. On top of that,
database.py runs _init_db() at import time, so PHOTO_PLATFORM_DB_PATH
must be redirected to a disposable path BEFORE database/api are ever
imported, or import alone would create/touch the production photos.db.
"""

import atexit
import os
import tempfile
from pathlib import Path

# Ensure API key auth is disabled (dev mode) before api.py is imported,
# regardless of what's in the developer's local .env.
os.environ.setdefault("API_KEY", "")

# Redirect the database to a disposable temp file before database.py (via
# api.py) is imported anywhere in the test session, so import-time
# _init_db() never touches the real production photos.db.
_TEST_DB_DIR = tempfile.TemporaryDirectory(prefix="photo-platform-test-db-")
os.environ["PHOTO_PLATFORM_DB_PATH"] = str(Path(_TEST_DB_DIR.name) / "test_photos.db")
atexit.register(_TEST_DB_DIR.cleanup)

import pytest
from fastapi.testclient import TestClient

import api


def make_photo(**overrides) -> dict:
    """Build a minimal photo dict with sane defaults, matching the shape
    database.list_all_photos() returns."""
    photo = {
        "id": 1,
        "filename": "IMG_0001.jpg",
        "file_size_original": 12345,
        "file_size_preview": 6789,
        "processed_at": "2026-01-01T00:00:00",
        "caption": "Cape Town: a sample caption",
        "keywords": "sport",
        "byline": "A Photographer",
        "copyright": "Trustory",
        "city": "Cape Town",
        "country": "South Africa",
        "headline": "Sample Headline",
        "source": "Trustory Images",
        "event": "Sample Event",
        "full_iptc": {},
        "original_path": "/tmp/original.jpg",
        "preview_path": "/tmp/preview.jpg",
    }
    photo.update(overrides)
    return photo


@pytest.fixture
def client():
    return TestClient(api.app)
