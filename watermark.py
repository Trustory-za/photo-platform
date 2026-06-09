#!/usr/bin/env python3
"""
"""Watermark script for The Sport Collective photo platform.
Tiles '© The Sport Collective' across the full image in a diagonal grid
pattern at 50% opacity, rotated -30 degrees.

Usage:
    watermark.py <input_image> <output_image>
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _find_best_font(text, target_height, font_path=None):
    """Find a .ttf font file and size that makes text approx `target_height` px tall."""
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

    # Binary search for best size
    low, high = 1, int(target_height * 4)
    best_sz = 1
    while low <= high:
        mid = (low + high) // 2
        try:
            fnt = ImageFont.truetype(font_path, mid) if font_path else ImageFont.load_default()
        except (IOError, OSError):
            fnt = ImageFont.load_default()
        # Only need height for sizing
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


def watermark_image(input_path: str, output_path: str) -> dict:
    """Tile a -30° rotated '© The Sport Collective' across the image at 50 % opacity."""
    try:
        src = Image.open(input_path).convert("RGBA")
        iw, ih = src.size

        text = "© The Sport Collective"

        # ---------- font sizing ----------
        # Tile text ~4 % of the shorter edge — small enough to tile, big enough to read.
        target_h = min(iw, ih) * 0.04
        font = _find_best_font(text, target_h)

        # Measure the text block
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        # ---------- build one tile ----------
        pad = int(th * 0.4)                     # breathing room around text
        tile = Image.new("RGBA", (tw + 2 * pad, th + 2 * pad), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text(
            (pad, pad - bbox[1]),               # offset by bbox top bearing so text is centered
            text, font=font, fill=(255, 255, 255, 179),
        )

        # Rotate the tile -30° (expand so nothing clips)
        rot = tile.rotate(-30, expand=True, resample=Image.BICUBIC)
        rw, rh = rot.size

        # ---------- tile across a full-size overlay ----------
        overlay = Image.new("RGBA", (iw, ih), (0, 0, 0, 0))

        # Spacing: ~2× tile width apart horizontally, ~2.5× vertically
        # Half-step stagger each row → brick / diagonal grid look
        step_x = int(rw * 2.0)
        step_y = int(rh * 2.5)
        stagger = step_x // 2

        # Cover generously from the negatives so no bare patches at edges
        row_start = -((ih // step_y) + 2)
        row_end = (ih // step_y) + 2
        col_start = -((iw // step_x) + 2)
        col_end = (iw // step_x) + 2

        for r in range(row_start, row_end):
            shift = stagger if r % 2 else 0
            for c in range(col_start, col_end):
                overlay.paste(rot, (c * step_x + shift, r * step_y), rot)

        # ---------- composite ----------
        result = Image.alpha_composite(src, overlay).convert("RGB")
        result.save(output_path, "JPEG", quality=95)

        return {
            "success": True,
            "input_path": str(Path(input_path).resolve()),
            "output_path": str(Path(output_path).resolve()),
            "image_size": f"{iw}x{ih}",
            "watermark_text": text,
        }

    except FileNotFoundError:
        return {
            "success": False,
            "error": f"Input file not found: {input_path}",
            "input_path": str(Path(input_path).resolve()),
            "output_path": str(Path(output_path).resolve()),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "input_path": str(Path(input_path).resolve()),
            "output_path": str(Path(output_path).resolve()),
        }


def main():
    if len(sys.argv) != 3:
        print(json.dumps({"success": False, "error": "Usage: watermark.py <input_image> <output_image>"}, indent=2))
        sys.exit(1)
    result = watermark_image(sys.argv[1], sys.argv[2])
    print(json.dumps(result, indent=2))
    if not result.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()