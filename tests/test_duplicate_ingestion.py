"""Regression tests for camera filename reuse in the FTP ingestion pipeline."""

import sqlite3
import threading
from ftplib import FTP
from io import BytesIO
from pathlib import Path

import database
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.servers import FTPServer
from watchdog.events import FileMovedEvent
from ftp_server import PhotoFTPHandler, _final_upload_path, _staging_upload_path
from process_image import _source_filename
import watcher


def _result(tmp_path: Path, *, source_name: str, content_hash: str, headline: str) -> dict:
    original = tmp_path / f"original_{content_hash[:12]}.jpg"
    preview = tmp_path / f"preview_{content_hash[:12]}.jpg"
    original.write_bytes(content_hash.encode())
    preview.write_bytes(b"preview")
    return {
        "success": True,
        "original_filename": source_name,
        "content_sha256": content_hash,
        "original_path": str(original),
        "preview_path": str(preview),
        "file_size_original": original.stat().st_size,
        "file_size_preview": preview.stat().st_size,
        "processed_at": "2026-09-11T00:00:00+00:00",
        "iptc": {"headline": headline},
    }


def test_ftp_stages_reused_names_without_overwriting(tmp_path):
    requested = tmp_path / "DSC_4997.JPG"

    first = _staging_upload_path(requested)
    second = _staging_upload_path(requested)

    assert first != second
    assert first.suffix == ".part"
    assert second.suffix == ".part"
    assert first.parent == requested.parent


def test_final_path_is_content_addressed_and_preserves_extension(tmp_path):
    staged = tmp_path / ".upload-deadbeef.part"

    final = _final_upload_path(staged, "DSC_4997.JPG", "a" * 64)

    assert final == tmp_path / "DSC_4997__aaaaaaaaaaaa.JPG"


def test_internal_hash_suffix_is_not_exposed_as_camera_filename():
    assert _source_filename("DSC_4997__0123456789ab.JPG") == "DSC_4997.JPG"
    assert _source_filename("ordinary-name.jpg") == "ordinary-name.jpg"


def test_same_filename_different_content_creates_two_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "photos.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database._init_db()

    first_id = database.insert_photo(
        _result(tmp_path, source_name="DSC_4997.JPG", content_hash="a" * 64, headline="Event A")
    )
    second_id = database.insert_photo(
        _result(tmp_path, source_name="DSC_4997.JPG", content_hash="b" * 64, headline="Event B")
    )

    assert first_id != second_id
    rows = database.list_all_photos()
    assert len(rows) == 2
    assert {row["filename"] for row in rows} == {"DSC_4997.JPG"}
    assert {row["headline"] for row in rows} == {"Event A", "Event B"}


def test_identical_content_hash_cannot_create_duplicate_row(tmp_path, monkeypatch):
    db_path = tmp_path / "photos.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    database._init_db()
    result = _result(
        tmp_path, source_name="DSC_4997.JPG", content_hash="c" * 64, headline="Event A"
    )

    database.insert_photo(result)

    try:
        database.insert_photo(result)
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("An identical content hash created a duplicate photo row")

    assert database.count_photos() == 1
    assert database.get_photo_by_content_hash("c" * 64) is not None


def test_real_ftp_accepts_reused_camera_filename_and_deduplicates_bytes(tmp_path):
    """Exercise STOR over a real socket, matching PhotoMechanic's FTP path."""
    authorizer = DummyAuthorizer()
    authorizer.add_user("photographer", "test-only", str(tmp_path), perm="elw")

    class TestHandler(PhotoFTPHandler):
        pass

    TestHandler.authorizer = authorizer
    server = FTPServer(("127.0.0.1", 0), TestHandler)
    assert server.socket is not None
    port = server.socket.getsockname()[1]
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={"timeout": 0.05, "blocking": True, "handle_exit": False},
        daemon=True,
    )
    thread.start()

    try:
        with FTP() as client:
            client.connect("127.0.0.1", port, timeout=5)
            client.login("photographer", "test-only")
            client.storbinary("STOR DSC_0001.JPG", BytesIO(b"event-one"))
            client.storbinary("STOR DSC_0001.JPG", BytesIO(b"event-two"))
            client.storbinary("STOR DSC_0001.JPG", BytesIO(b"event-two"))

        stored = sorted(tmp_path.glob("DSC_0001__*.JPG"))
        assert len(stored) == 2
        assert {path.read_bytes() for path in stored} == {b"event-one", b"event-two"}
        assert not list(tmp_path.glob("*.part"))
    finally:
        server.close_all()
        thread.join(timeout=5)


def test_watcher_processes_destination_of_staging_move(tmp_path, monkeypatch):
    final_path = tmp_path / "DSC_0001__0123456789ab.JPG"
    final_path.write_bytes(b"complete")
    processed = []

    handler = watcher.JpgUploadHandler()
    monkeypatch.setattr(handler, "_wait_until_stable", lambda path: True)
    monkeypatch.setattr(watcher, "_process_jpg", processed.append)

    event = FileMovedEvent(str(tmp_path / ".upload-example.part"), str(final_path))
    handler.on_moved(event)

    assert processed == [final_path]
