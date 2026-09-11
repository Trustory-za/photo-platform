"""Regression tests for web-preview dimensions, encoding, and caching."""

from pathlib import Path

from PIL import Image

import api
from process_image import PREVIEW_MAX_EDGE, _apply_watermark


def _jpeg(path: Path, size: tuple[int, int]) -> None:
    Image.new("RGB", size, (20, 120, 80)).save(path, "JPEG", quality=95)


def test_large_preview_is_web_sized_and_progressive(tmp_path):
    source = tmp_path / "camera-original.jpg"
    preview = tmp_path / "preview.jpg"
    _jpeg(source, (4000, 3000))

    _apply_watermark(str(source), str(preview))

    with Image.open(preview) as result:
        assert result.size == (PREVIEW_MAX_EDGE, 1440)
        assert result.info.get("progressive") or result.info.get("progression")


def test_small_preview_is_not_upscaled(tmp_path):
    source = tmp_path / "small-original.jpg"
    preview = tmp_path / "preview.jpg"
    _jpeg(source, (1200, 800))

    _apply_watermark(str(source), str(preview))

    with Image.open(preview) as result:
        assert result.size == (1200, 800)


def test_preview_response_has_browser_cache_policy(client, tmp_path, monkeypatch):
    preview = tmp_path / "preview.jpg"
    _jpeg(preview, (100, 100))
    monkeypatch.setattr(
        api.database,
        "get_photo",
        lambda _photo_id: {"id": 1, "preview_path": str(preview)},
    )

    response = client.get("/photos/1/preview")

    assert response.status_code == 200
    assert response.headers["cache-control"] == (
        "public, max-age=86400, stale-while-revalidate=604800"
    )