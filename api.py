import json
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
from html import escape
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

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

# The frontend origin that hosts the buyer-facing download handoff page.
FRONTEND_BASE_URL = os.environ.get(
    "FRONTEND_BASE_URL", "https://images.olympusbot.cloud"
)

PHOTO_PRICE_ZAR = 15000  # R150.00 in cents — pilot price, server-side truth

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



@app.get("/events/{slug}")
def get_event_photos(slug: str):
    """Return all photos for a specific event by slug."""
    photos = database.list_all_photos()
    result = []
    for p in photos:
        headline = p.get("headline") or "Unknown Event"
        photo_slug = (
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
        if photo_slug == slug:
            result.append(_sanitise(p))
    return result

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
def list_events():
    """Return all photos grouped by headline into events."""
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
                "date": (lambda d: f"{d[6:8]} {['January','February','March','April','May','June','July','August','September','October','November','December'][int(d[4:6])-1]} {d[0:4]}" if d and len(d)==8 else p.get("processed_at"))((((p.get("full_iptc") if isinstance(p.get("full_iptc"), dict) else __import__('json').loads(p.get("full_iptc") or "{}")) or {}).get("date created") or "").replace("-","")),
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


class BasketPurchaseRequest(BaseModel):
    name: str
    email: str
    photo_ids: list[int]


@app.post("/basket/purchase")
def purchase_basket(
    body: BasketPurchaseRequest,
    x_api_key: str | None = Header(None),
):
    """Initialize a single Paystack checkout covering every photo in a basket."""
    _verify_api_key(x_api_key)

    name = body.name.strip()
    email = body.email.strip()

    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="A valid email address is required")
    if not body.photo_ids:
        raise HTTPException(status_code=400, detail="At least one photo is required")

    # De-duplicate while preserving basket order
    seen: set[int] = set()
    photo_ids: list[int] = []
    for photo_id in body.photo_ids:
        if photo_id not in seen:
            seen.add(photo_id)
            photo_ids.append(photo_id)

    for photo_id in photo_ids:
        if database.get_photo(photo_id) is None:
            raise HTTPException(status_code=404, detail=f"Photo {photo_id} not found")

    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(
            status_code=502,
            detail="Payment gateway is not configured",
        )

    # Amount is calculated server-side only — never trust a client-sent total.
    amount_zar = len(photo_ids) * PHOTO_PRICE_ZAR
    reference = str(uuid.uuid4())

    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "amount": amount_zar,
        "currency": "ZAR",
        "reference": reference,
        "callback_url": PAYSTACK_CALLBACK_URL,
        "metadata": {
            "kind": "basket",
            "photo_ids": photo_ids,
            "buyer_name": name,
        },
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
    except requests.RequestException:
        raise HTTPException(
            status_code=502,
            detail="Payment gateway error",
        )

    if not data.get("status"):
        raise HTTPException(
            status_code=502,
            detail=f"Paystack error: {data.get('message', 'unknown')}",
        )

    authorization_url = data["data"]["authorization_url"]

    # Only persist the pending order once Paystack has confirmed initialize succeeded.
    database.create_basket_order(name, email, reference, amount_zar, photo_ids)

    return {
        "payment_url": authorization_url,
        "authorization_url": authorization_url,
        "reference": reference,
        "amount_zar": amount_zar,
    }


@app.get("/payment/verify")
def verify_payment(reference: str = Query(...)):
    """Callback endpoint called by Paystack after payment."""
    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(
            status_code=502,
            detail="Payment gateway is not configured",
        )

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

    paid_amount = data["data"].get("amount")

    # Multi-photo basket orders take priority — a reference can only ever
    # belong to one order type since it's a freshly generated UUID.
    basket_order = database.get_basket_order_by_reference(reference)
    if basket_order is not None:
        if paid_amount != basket_order["amount_zar"]:
            return {
                "status": "error",
                "message": "Paid amount does not match the order total",
            }

        download_token = str(uuid.uuid4())
        order_id = database.confirm_basket_order(reference, download_token)

        if order_id is None:
            return {
                "status": "error",
                "message": "Order not found or already processed",
            }

        return RedirectResponse(url=f"{FRONTEND_BASE_URL}/download/{download_token}")

    # Legacy single-photo purchase flow — unchanged behaviour.
    purchase = database.get_purchase_by_reference(reference)
    if purchase is not None:
        if paid_amount != purchase["amount_zar"]:
            return {
                "status": "error",
                "message": "Paid amount does not match the purchase total",
            }

        download_token = str(uuid.uuid4())
        purchase_id = database.confirm_purchase(reference, download_token)

        if purchase_id is None:
            return {
                "status": "error",
                "message": "Purchase not found or already processed",
            }

        return RedirectResponse(url=f"/download/{download_token}")

    return {
        "status": "error",
        "message": "Transaction not found",
    }


def _render_basket_download_page(token: str, photos: list[dict]) -> str:
    """Render a minimal, self-contained HTML page listing paid basket
    photos with per-photo download buttons. Never includes filesystem
    paths — download links only reference the public token and photo ID."""
    items_html = []
    for photo in photos:
        photo_id = photo["id"]
        label = escape(photo.get("headline") or photo.get("filename") or f"Photo {photo_id}")
        preview_url = escape(
            f"https://photos.olympusbot.cloud/photos/{photo_id}/preview"
        )
        items_html.append(f"""
        <div class="item">
          <img src="{preview_url}" alt="{label}" loading="lazy" />
          <div class="item-info">
            <p class="item-title">{label}</p>
            <a class="btn" href="/download/{token}/photos/{photo_id}">Download original</a>
          </div>
        </div>""")

    count = len(photos)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Your downloads — The Sport Collective</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif; background:#1a1a1a; color:#fff; margin:0; padding:48px 20px; }}
  h1 {{ font-size:24px; margin:0 0 8px; text-align:center; }}
  p.sub {{ color:#999; margin:0 0 32px; text-align:center; }}
  .grid {{ display:grid; grid-template-columns: repeat(auto-fill, minmax(220px,1fr)); gap:20px; max-width:960px; margin:0 auto; }}
  .item {{ background:#242424; border-radius:12px; overflow:hidden; }}
  .item img {{ width:100%; height:160px; object-fit:cover; display:block; background:#333; }}
  .item-info {{ padding:14px; }}
  .item-title {{ font-size:13px; margin:0 0 10px; color:#eee; }}
  .btn {{ display:inline-block; background:#007749; color:#fff; text-decoration:none; padding:10px 16px; border-radius:8px; font-size:13px; font-weight:700; }}
</style>
</head>
<body>
  <h1>Your downloads are ready</h1>
  <p class="sub">{count} photo{'s' if count != 1 else ''} paid in full — each button downloads the full-resolution, watermark-free original.</p>
  <div class="grid">{''.join(items_html)}</div>
</body>
</html>"""


@app.get("/download/{token}")
def download_original(token: str):
    """Serve a paid basket order's download listing page, or download a
    single legacy purchase's original photo using a single-use token."""
    basket_order = database.get_basket_order_by_token(token)
    if basket_order is not None:
        if basket_order["status"] not in ("paid", "downloaded"):
            raise HTTPException(status_code=403, detail="Payment not confirmed for this order")

        photos = database.list_basket_order_photos(basket_order["id"])
        return HTMLResponse(_render_basket_download_page(token, photos))

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


@app.get("/download/{token}/photos/{photo_id}")
def download_basket_photo(token: str, photo_id: int):
    """Download one original photo from a paid basket order.

    Unlike the legacy single-photo token, this token is not single-use —
    every paid photo in the order remains individually downloadable.
    """
    basket_order = database.get_basket_order_by_token(token)
    if basket_order is None:
        raise HTTPException(status_code=404, detail="Download token not found")

    if basket_order["status"] not in ("paid", "downloaded"):
        raise HTTPException(status_code=403, detail="Payment not confirmed for this order")

    order_photo_ids = {p["id"] for p in database.list_basket_order_photos(basket_order["id"])}
    if photo_id not in order_photo_ids:
        raise HTTPException(status_code=404, detail="Photo not part of this order")

    photo = database.get_photo(photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    original_path = photo.get("original_path")
    if not original_path:
        raise HTTPException(status_code=404, detail="Original file path not set")

    p = Path(original_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Original file not found on disk")

    database.mark_basket_order_downloaded(token)

    return FileResponse(str(p), media_type="image/jpeg", filename=p.name)