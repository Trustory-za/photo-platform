#!/usr/bin/env python3
"""
api.py — FastAPI web API for the Trustory Images photo platform.

Exposes the database over HTTP with search, preview serving, and a
purchase placeholder.

Usage:
    uvicorn api:app --host 0.0.0.0 --port 8090
"""

import os
from pathlib import Path

import database
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

# ── Bootstrap ───────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(str(ENV_PATH))

API_KEY = os.environ.get("API_KEY")

app = FastAPI(
    title="Trustory Images API",
    description="Photo licensing platform API",
    version="0.1.0",
)

# ── CORS ────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth helper ─────────────────────────────────────────────────────

def _verify_api_key(x_api_key: str | None = None) -> None:
    """Raise 401 if the API key is missing, wrong, or not configured."""
    if not API_KEY:
        # No API key configured — allow through (dev mode)
        return
    if x_api_key is None:
        raise HTTPException(
            status_code=401,
            detail="Missing X-API-Key header",
        )
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
        )


# ── Response helpers ────────────────────────────────────────────────

# Fields safe for public display — NEVER include original_path
PUBLIC_FIELDS = {
    "id", "filename", "preview_path", "file_size_original",
    "file_size_preview", "processed_at", "caption", "keywords",
    "byline", "copyright", "city", "country", "headline", "source",
    "full_iptc",
}


def _sanitise(photo: dict) -> dict:
    """Strip internal fields (original_path) from a photo dict."""
    return {k: v for k, v in photo.items() if k in PUBLIC_FIELDS}


# ── Endpoints ───────────────────────────────────────────────────────


@app.get("/health")
def health():
    """Health check — no API key required."""
    count = database.count_photos()
    return {"status": "ok", "photos_in_db": count}


@app.get("/photos")
def list_photos(x_api_key: str | None = Header(None)):
    """Return all photos, newest first."""
    _verify_api_key(x_api_key)
    photos = database.list_all_photos()
    return [_sanitise(p) for p in photos]


@app.get("/photos/search")
def search_photos(
    q: str = Query(..., description="Search query"),
    x_api_key: str | None = Header(None),
):
    """Full-text search across caption, keywords, byline, city, etc."""
    _verify_api_key(x_api_key)
    if not q.strip():
        return []
    photos = database.search_photos(q)
    return [_sanitise(p) for p in photos]


@app.get("/photos/{photo_id}")
def get_photo(
    photo_id: int,
    x_api_key: str | None = Header(None),
):
    """Get a single photo by database ID."""
    _verify_api_key(x_api_key)
    photo = database.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")
    return _sanitise(photo)


@app.get("/photos/{photo_id}/preview")
def get_preview(
    photo_id: int,
    x_api_key: str | None = Header(None),
):
    """Serve the watermarked preview image directly."""
    _verify_api_key(x_api_key)
    photo = database.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    preview_path = photo.get("preview_path")
    if not preview_path:
        raise HTTPException(status_code=404, detail="Preview path not set")

    p = Path(preview_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Preview file not found on disk")

    return FileResponse(str(p), media_type="image/jpeg")


@app.post("/photos/{photo_id}/purchase")
def purchase_photo(
    photo_id: int,
    x_api_key: str | None = Header(None),
):
    """Placeholder for Stripe purchase — Week 7."""
    _verify_api_key(x_api_key)
    photo = database.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    return {
        "status": "payment_not_configured",
        "photo_id": photo_id,
        "message": "Stripe integration coming in Week 7",
    }