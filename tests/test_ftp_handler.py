"""Regression tests for PhotoFTPHandler.on_file_received.

Production incident: self.fsize does not exist on FTPHandler, so every
successful upload raised AttributeError after the file was already
received. on_file_received must derive size from the file on disk (or
degrade gracefully if the watcher already moved/deleted it) without
ever touching self.fsize.
"""

import logging
from types import SimpleNamespace

from ftp_server import PhotoFTPHandler


class NoFsize(SimpleNamespace):
    """A stand-in for the pyftpdlib handler instance that has no fsize
    attribute — accessing self.fsize must raise AttributeError, which
    proves on_file_received no longer depends on it."""

    def __getattr__(self, name):
        if name == "fsize":
            raise AttributeError("fsize")
        raise AttributeError(name)


def test_on_file_received_does_not_touch_fsize(tmp_path, caplog):
    f = tmp_path / "upload.jpg"
    f.write_bytes(b"x" * 42)

    fake_self = NoFsize()
    with caplog.at_level(logging.INFO, logger="ftp_server"):
        PhotoFTPHandler.on_file_received(fake_self, str(f))

    assert "42" in caplog.text
    assert "UPLOAD" in caplog.text


def test_on_file_received_missing_path_does_not_raise(tmp_path, caplog):
    missing = tmp_path / "already-moved-by-watcher.jpg"
    assert not missing.exists()

    fake_self = NoFsize()
    with caplog.at_level(logging.INFO, logger="ftp_server"):
        PhotoFTPHandler.on_file_received(fake_self, str(missing))

    assert "UPLOAD" in caplog.text
    assert "unavailable" in caplog.text.lower()
