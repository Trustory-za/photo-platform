"""Direct tests for ftp_server.configure_runtime().

configure_runtime() must be safe to call directly with injected,
non-production upload/log directories: it creates exactly those
directories and attaches a FileHandler pointed at that log_dir's
ftp.log plus a StreamHandler to the module logger, without ever
touching the real production uploads/ or logs/ directories.

Idempotence must be judged by detecting the *specific* required
handlers (a FileHandler pointed at the expected log file, and a plain
StreamHandler) -- not merely "logger.handlers is non-empty". An
unrelated handler already attached to the logger must not cause
configure_runtime to silently skip attaching the real ones.

Every test saves and restores ftp_server.logger.handlers exactly as
found, so these tests can never leak a handler into other tests running
in the same process (see test_ftp_server_import_isolation.py, which
asserts no FileHandler is present on this exact logger), and never
write into the real production logs/ftp.log.
"""

import logging

import pytest

import ftp_server

PROD_LOG_FILE = ftp_server.LOG_DIR / "ftp.log"


@pytest.fixture
def clean_logger():
    """Snapshot and restore ftp_server.logger's handlers around a test,
    closing any handlers the test attached so no open file descriptor
    or FileHandler leaks into later tests."""
    original_handlers = list(ftp_server.logger.handlers)
    ftp_server.logger.handlers = []
    yield ftp_server.logger
    for h in ftp_server.logger.handlers:
        if h not in original_handlers:
            h.close()
    ftp_server.logger.handlers = original_handlers


def _prod_log_mtime():
    return PROD_LOG_FILE.stat().st_mtime if PROD_LOG_FILE.exists() else None


def test_configure_runtime_creates_injected_directories(tmp_path, clean_logger):
    upload_dir = tmp_path / "incoming"
    log_dir = tmp_path / "logs"
    assert not upload_dir.exists()
    assert not log_dir.exists()

    ftp_server.configure_runtime(upload_dir=upload_dir, log_dir=log_dir)

    assert upload_dir.is_dir()
    assert log_dir.is_dir()


def test_configure_runtime_attaches_file_and_stream_handlers(tmp_path, clean_logger):
    upload_dir = tmp_path / "incoming"
    log_dir = tmp_path / "logs"

    ftp_server.configure_runtime(upload_dir=upload_dir, log_dir=log_dir)

    file_handlers = [h for h in clean_logger.handlers if isinstance(h, logging.FileHandler)]
    stream_only_handlers = [
        h for h in clean_logger.handlers
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
    ]
    assert len(file_handlers) == 1
    assert file_handlers[0].baseFilename == str((log_dir / "ftp.log").resolve())
    assert len(stream_only_handlers) == 1


def test_configure_runtime_never_touches_production_log(tmp_path, clean_logger):
    """Calling configure_runtime with injected paths must never create,
    write to, or modify the real repo's logs/ftp.log."""
    mtime_before = _prod_log_mtime()

    ftp_server.configure_runtime(upload_dir=tmp_path / "incoming", log_dir=tmp_path / "logs")
    logging.getLogger("ftp_server").info("test log line — must land in tmp_path, not prod")

    mtime_after = _prod_log_mtime()
    assert mtime_after == mtime_before


def test_configure_runtime_is_idempotent_for_repeated_same_path_calls(tmp_path, clean_logger):
    upload_dir = tmp_path / "incoming"
    log_dir = tmp_path / "logs"

    ftp_server.configure_runtime(upload_dir=upload_dir, log_dir=log_dir)
    handlers_after_first = list(clean_logger.handlers)

    ftp_server.configure_runtime(upload_dir=upload_dir, log_dir=log_dir)
    handlers_after_second = list(clean_logger.handlers)

    assert handlers_after_second == handlers_after_first


def test_configure_runtime_detects_specific_handlers_not_any_handler(tmp_path, clean_logger):
    """An unrelated handler already on the logger (e.g. a NullHandler)
    must not fool configure_runtime into thinking the real file/stream
    handlers are already attached — it must still attach its own."""
    unrelated = logging.NullHandler()
    clean_logger.addHandler(unrelated)

    ftp_server.configure_runtime(upload_dir=tmp_path / "incoming", log_dir=tmp_path / "logs")

    assert unrelated in clean_logger.handlers  # left untouched
    assert any(isinstance(h, logging.FileHandler) for h in clean_logger.handlers)
    assert any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in clean_logger.handlers
    )


def test_configure_runtime_adds_new_file_handler_for_different_log_dir(tmp_path, clean_logger):
    """A second call with a different log_dir must attach a new
    FileHandler for that path rather than treating the logger as
    already fully configured because a (different-path) FileHandler and
    StreamHandler already exist."""
    first_log_dir = tmp_path / "logs_a"
    second_log_dir = tmp_path / "logs_b"

    ftp_server.configure_runtime(upload_dir=tmp_path / "incoming_a", log_dir=first_log_dir)
    ftp_server.configure_runtime(upload_dir=tmp_path / "incoming_b", log_dir=second_log_dir)

    file_handler_paths = {
        h.baseFilename for h in clean_logger.handlers if isinstance(h, logging.FileHandler)
    }
    assert file_handler_paths == {
        str((first_log_dir / "ftp.log").resolve()),
        str((second_log_dir / "ftp.log").resolve()),
    }
