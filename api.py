#!/usr/bin/env python3
"""
api.py — FastAPI web API for the Trustory Images photo platform.

Exposes the database over HTTP with search, preview serving, and
Paystack payment integration for photo purchases.

Usage:
    uvicorn api:app --host 0.0.0.0 --port 8090
"""

import os
import uuid
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse

import database

# ── Bootstrap ───────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
if ENV_PATH.exists():
    load_dotenv(str(ENV_PATH))

API_KEY = os.environ.get("API_KEY", "")

# Paystack (test mode)
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
PAYSTACK_CALLBACK_URL = os.environ.get(
    "PAYSTACK_CALLBACK_URL",
    "https://photos.olympusbot.cloud/payment/verify",
)

PAYSTACK_INIT_URL = "https://api.paystack.co/transaction/initialize"
PAYSTACK_VERIFY_URL = "https://api.paystack.co/transaction/verify"

PHOTO_PRICE_ZAR = 15000  # R150.00 in cents

app = FastAPI(
    title="Trustory Images API",
    description="Photo licensing platform API",
    version="0.2.0",
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

# Fields safe for public display — NEVER include original_path or preview_path
PUBLIC_FIELDS = {
    "id", "filename", "file_size_original",
    "file_size_preview", "processed_at", "caption", "keywords",
    "byline", "copyright", "city", "country", "headline", "source",
    "event", "full_iptc",
}


def _sanitise(photo: dict) -> dict:
    """Strip internal fields (original_path, preview_path) from a photo dict
    and add a public preview_url instead."""
    sanitised = {k: v for k, v in photo.items() if k in PUBLIC_FIELDS}
    # Add preview_url derived from the database ID
    photo_id = sanitised.get("id")
    if photo_id is not None:
        sanitised["preview_url"] = f"https://photos.olympusbot.cloud/photos/{photo_id}/preview"
    return sanitised


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


@app.get("/events")
def list_events(x_api_key: str | None = Header(None)):
    """Return all photos grouped by headline into events."""
    _verify_api_key(x_api_key)
    photos = database.list_all_photos()

    # Group photos by headline
    events: dict[str, dict] = {}
    for p in photos:
        headline = p.get("headline") or "Unknown Event"
        if headline not in events:
            # Sanitise to get preview_url
            sanitised_p = _sanitise(p)

            # Extract location from caption (text before first colon or comma)
            caption = p.get("caption") or ""
            location = ""
            for sep in [":", ","]:
                parts = caption.split(sep, 1)
                if len(parts) > 1:
                    location = parts[0].strip()
                    break

            # Sanitise headline into a URL slug
            slug = (
                headline.lower()
                .replace(" ", "-")
                .replace(":", "")
                .replace("/", "")
                .replace("\\", "")
                .replace("'", "")
                .replace('"', "")
                .replace("--", "-")
                .strip("-")
            )

            events[headline] = {
                "headline": headline,
                "slug": slug,
                "date": p.get("processed_at"),
                "photo_count": 0,
                "cover_photo_url": sanitised_p.get("preview_url"),
                "location": location,
            }
        events[headline]["photo_count"] += 1

    # Sort by date descending (most recent first)
    result = sorted(
        events.values(),
        key=lambda e: e["date"] or "",
        reverse=True,
    )
    return result


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
):
    """Serve the watermarked preview image directly."""
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
    body: dict,
    x_api_key: str | None = Header(None),
):
    """Initialize a Paystack checkout for the given photo."""
    _verify_api_key(x_api_key)

    # Validate photo exists
    photo = database.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    # Validate email
    email = body.get("email", "").strip()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email address is required")

    # Generate unique reference
    reference = str(uuid.uuid4())

    # Call Paystack initialize
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "amount": PHOTO_PRICE_ZAR,
        "currency": "ZAR",
        "reference": reference,
        "callback_url": PAYSTACK_CALLBACK_URL,
        "metadata": {"photo_id": photo_id},
    }

    try:
        resp = requests.post(
            PAYSTACK_INIT_URL,
            json=payload,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Payment gateway error: {str(e)}",
        )

    if not data.get("status"):
        raise HTTPException(
            status_code=502,
            detail=f"Paystack error: {data.get('message', 'unknown')}",
        )

    # Save pending purchase to database
    database.create_purchase(photo_id, email, reference, PHOTO_PRICE_ZAR)

    return {
        "payment_url": data["data"]["authorization_url"],
        "reference": reference,
    }


@app.get("/payment/verify")
def verify_payment(reference: str = Query(...)):
    """Callback endpoint called by Paystack after payment."""
    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.get(
            f"{PAYSTACK_VERIFY_URL}/{reference}",
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        raise HTTPException(
            status_code=502,
            detail=f"Payment verification error: {str(e)}",
        )

    if not data.get("status") or data["data"].get("status") != "success":
        return {
            "status": "failed",
            "message": "Payment was not successful",
        }

    # Payment was successful — generate download token
    download_token = str(uuid.uuid4())
    purchase_id = database.confirm_purchase(reference, download_token)

    if purchase_id is None:
        return {
            "status": "error",
            "message": "Purchase not found or already processed",
        }

    return RedirectResponse(url=f"/download/{download_token}")


@app.get("/download/{token}")
def download_original(token: str):
    """Download the original photo using a single-use token."""
    purchase = database.get_purchase_by_token(token)
    if purchase is None:
        raise HTTPException(status_code=404, detail="Download token not found")

    if purchase["status"] != "paid":
        raise HTTPException(status_code=403, detail="Payment not confirmed or token already used")

    # Look up the photo
    photo = database.get_photo(purchase["photo_id"])
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    original_path = photo.get("original_path")
    if not original_path:
        raise HTTPException(status_code=404, detail="Original file path not set")

    p = Path(original_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Original file not found on disk")

    # Mark token as used (single-use)
    database.mark_downloaded(token)

    return FileResponse(str(p), media_type="image/jpeg", filename=p.name)