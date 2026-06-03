#!/usr/bin/env python3
"""
process_image.py — Core pipeline for the Trustory Images photo platform.

Combines IPTC metadata extraction and watermarking into a single command.
Takes an input JPG and an output directory, produces:
  - preview_[filename] — watermarked version
  - original_[filename] — untouched clean copy

Outputs a single JSON result to stdout.

Usage:
    process_image.py <input_image> <output_directory>
"""

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from iptcinfo3 import IPTCInfo
from PIL import Image, ImageDraw, ImageFont


# ── IPTC logic (self-contained, mirrors iptc_reader.py) ──────────────────────

def _extract_iptc(file_path: str) -> dict:
    """Read IPTC metadata from a JPG and return a dict of field→value(s).

    Returns an empty dict if no IPTC data is found; caller handles errors.
    """
    try:
        info = IPTCInfo(str(file_path), force=True)
    except Exception:
        return {}

    standard_fields = [
        'caption/abstract', 'keywords', 'by-line', 'byline/title',
        'creditline', 'source', 'copyright notice', 'contact',
        'object name', 'edit status', 'urgency', 'category',
        'supplemental category', 'date created', 'time created',
        'digital date created', 'digital time created',
        'originating program', 'program version',
    ]

    cleaned = {}
    for field in standard_fields:
        if field in info:
            value = info[field]
            if value is None or value == '':
                continue
            if isinstance(value, (list, tuple)):
                cleaned[field] = [str(v) for v in value if v]
            else:
                cleaned[field] = str(value)
    return cleaned


# ── Watermark logic (self-contained, mirrors watermark.py) ───────────────────

def _find_best_font(text, target_height, font_path=None):
    """Binary-search a .ttf so text is approximately *target_height* px tall."""
    candidate_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    if font_path is None:
        for fp in candidate_paths:
            if Path(fp).exists():
                font_path = fp
                break

    low, high = 1, int(target_height * 4)
    best_sz = 1
    while low <= high:
        mid = (low + high) // 2
        try:
            fnt = ImageFont.truetype(font_path, mid) if font_path else ImageFont.load_default()
        except (IOError, OSError):
            fnt = ImageFont.load_default()
        bbox = fnt.getbbox(text)
        th = bbox[3] - bbox[1]
        if th <= target_height:
            best_sz = mid
            low = mid + 1
        else:
            high = mid - 1

    if font_path:
        return ImageFont.truetype(font_path, best_sz)
    return ImageFont.load_default()


def _apply_watermark(input_path: str, output_path: str) -> None:
    """Tile '© Trustory Images' at -30° rotation, 50 % opacity."""
    src = Image.open(input_path).convert("RGBA")
    iw, ih = src.size

    text = "© Trustory Images"

    # Font size ~4 % of the shorter edge
    target_h = min(iw, ih) * 0.04
    font = _find_best_font(text, target_h)

    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    # Single tile with padding
    pad = int(th * 0.4)
    tile = Image.new("RGBA", (tw + 2 * pad, th + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(tile).text(
        (pad, pad - bbox[1]),
        text, font=font, fill=(255, 255, 255, 179),
    )

    rot = tile.rotate(-30, expand=True, resample=Image.BICUBIC)
    rw, rh = rot.size

    overlay = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))

    step_x = int(rw * 2.0)
    step_y = int(rh * 2.5)
    stagger = step_x // 2

    row_start = -((ih // step_y) + 2)
    row_end = (ih // step_y) + 2
    col_start = -((iw // step_x) + 2)
    col_end = (iw // step_x) + 2

    for r in range(row_start, row_end):
        shift = stagger if r % 2 else 0
        for c in range(col_start, col_end):
            overlay.paste(rot, (c * step_x + shift, r * step_y), rot)

    result = Image.alpha_composite(src, overlay).convert("RGB")
    result.save(output_path, "JPEG", quality=95)


# ── Pipeline ─────────────────────────────────────────────────────────────────

def process_image(input_path: str, output_dir: str) -> dict:
    """Run the full pipeline and return a JSON-serialisable result dict."""
    now = datetime.now(timezone.utc).isoformat()
    inp = Path(input_path)
    out_dir = Path(output_dir)

    # ── Validate input ────────────────────────────────────────────────────
    if not inp.exists():
        return {
            "success": False,
            "error": f"Input file not found: {input_path}",
            "processed_at": now,
        }

    if inp.suffix.lower() not in (".jpg", ".jpeg"):
        return {
            "success": False,
            "error": f"Invalid file type: {inp.suffix}. Only JPG files are supported.",
            "processed_at": now,
        }

    # ── Ensure output directory exists ─────────────────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)

    base_stem = inp.stem
    # Keep original extension (.jpg or .jpeg) as-is
    ext = inp.suffix

    orig_name = f"original_{inp.name}"
    preview_name = f"preview_{inp.name}"

    orig_path = out_dir / orig_name
    preview_path = out_dir / preview_name

    # ── 1. Copy original ──────────────────────────────────────────────────
    shutil.copy2(str(inp), str(orig_path))

    # ── 2. Read IPTC metadata ─────────────────────────────────────────────
    iptc_data = _extract_iptc(str(inp))

    # ── 3. Create watermarked preview ─────────────────────────────────────
    try:
        _apply_watermark(str(inp), str(preview_path))
    except Exception as e:
        return {
            "success": False,
            "error": f"Watermark failed: {e}",
            "original_path": str(orig_path.resolve()),
            "iptc": iptc_data,
            "processed_at": now,
        }

    # ── File sizes ─────────────────────────────────────────────────────────
    fs_orig = orig_path.stat().st_size
    fs_preview = preview_path.stat().st_size

    return {
        "success": True,
        "original_path": str(orig_path.resolve()),
        "preview_path": str(preview_path.resolve()),
        "iptc": iptc_data,
        "file_size_original": fs_orig,
        "file_size_preview": fs_preview,
        "processed_at": now,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) != 3:
        print(json.dumps({
            "success": False,
            "error": "Usage: process_image.py <input_image> <output_directory>",
        }))
        sys.exit(1)

    result = process_image(sys.argv[1], sys.argv[2])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()
