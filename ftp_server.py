#!/usr/bin/env python3
"""
ftp_server.py — FTP receiver for the Trustory Images photo platform.

Photographers upload JPG files to a sandboxed directory. The server runs on
port 2121 (non-root) with a single user 'photographer'. Uploads go to
uploads/incoming/ for the file watcher to pick up.

Usage:
    python ftp_server.py

Environment variables (loaded from .env):
    FTP_PASSWORD   Password for the 'photographer' user
"""

import ftplib
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

# ── Paths ───────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads" / "incoming"
LOG_DIR = BASE_DIR / "logs"

# ── Logging ─────────────────────────────────────────────────────────────
#
# Only the logger object itself (no I/O) is created at import time.
# Directory creation and handler attachment are deferred to
# configure_runtime(), called only from main(), so importing this module
# — e.g. to reach PhotoFTPHandler from tests — never touches the
# filesystem or mutates the production ftp.log.

logger = logging.getLogger("ftp_server")
logger.setLevel(logging.INFO)


def configure_runtime(upload_dir: Path = UPLOAD_DIR, log_dir: Path = LOG_DIR) -> None:
    """Create runtime directories and attach log handlers.

    Idempotent: safe to call more than once. Idempotence is judged by
    checking for the *specific* handlers this function requires — a
    FileHandler already pointed at this exact log_dir's ftp.log, and a
    plain StreamHandler — rather than treating any handler already being
    present on the logger as sufficient. That distinction matters: if
    some unrelated handler (e.g. attached by other code, or a test) were
    already on the logger, treating "any handler" as "already
    configured" would silently skip attaching the real file/stream
    handlers this module depends on. Each missing handler is attached
    independently, so a second call with a different log_dir still
    attaches the file handler for the new path.

    Paths are injectable for tests that want a real (non-production)
    upload/log directory.
    """
    upload_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = str((log_dir / "ftp.log").resolve())
    has_file_handler = any(
        isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == log_file
        for h in logger.handlers
    )
    has_stream_handler = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in logger.handlers
    )

    if has_file_handler and has_stream_handler:
        return

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    if not has_file_handler:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    if not has_stream_handler:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)


# ── Custom handler ──────────────────────────────────────────────────────

class PhotoFTPHandler(FTPHandler):
    """Restrict photographers to upload-only in their sandbox.

    - No overwrite of existing files
    - No delete, rename, or retrieve
    - All uploads go to the sandboxed uploads/incoming/ directory
    """

    def on_connect(self):
        logger.info("CONNECT %s:%s", self.remote_ip, self.remote_port)

    def on_disconnect(self):
        logger.info("DISCONNECT %s:%s", self.remote_ip, self.remote_port)

    def on_file_sent(self, file):
        logger.warning("DOWNLOAD BLOCKED %s  (downloads not allowed)", file)

    def on_file_received(self, file):
        """Log a successfully received upload.

        Reads the size from disk rather than self.fsize (which does not
        exist on FTPHandler and raised AttributeError on every upload).
        Tolerates the watcher having already moved or deleted the file
        before this callback runs.
        """
        try:
            size = Path(file).stat().st_size
        except OSError:
            logger.info("UPLOAD %s  (size: unavailable)", file)
            return
        logger.info("UPLOAD %s  (size: %d bytes)", file, size)

    def on_incomplete_file_received(self, file):
        logger.warning("INCOMPLETE UPLOAD %s", file)

    def on_login(self, username):
        logger.info("LOGIN %s", username)

    def on_login_failed(self, username, password):
        logger.warning("LOGIN FAILED username=%s", username)

    def ftp_STOR(self, filepath):
        """Prevent overwriting existing files."""
        if os.path.exists(filepath):
            logger.warning("OVERWRITE BLOCKED %s  (file already exists)", filepath)
            raise ftplib.error_perm("550 File already exists; overwrite not allowed")
        return super().ftp_STOR(filepath)


# ── Server ──────────────────────────────────────────────────────────────

handler = PhotoFTPHandler

# Recommended permissions so uploaded files are readable by the watcher
handler.umask = 0o022


def main():
    # Directory creation, log handler setup, .env loading, FTP_PASSWORD
    # validation, building the authorizer, and binding the socket all
    # happen here (not at module import time) so the module can be
    # imported — e.g. in tests — without credentials, without touching
    # production directories/logs, and without grabbing a real port.
    configure_runtime()

    load_dotenv(BASE_DIR / ".env")

    ftp_password = os.getenv("FTP_PASSWORD")
    if not ftp_password:
        print("FATAL: FTP_PASSWORD not set in .env", file=sys.stderr)
        sys.exit(1)

    authorizer = DummyAuthorizer()

    # User 'photographer' — upload only, no delete/overwrite/rename/retrieve
    # Overwrite blocking is handled in the custom ftp_STOR method above
    authorizer.add_user(
        "photographer",
        ftp_password,
        str(UPLOAD_DIR),
        perm="elw",  # enter directory, list files, write (upload) — no delete/rename/retrieve
    )
    handler.authorizer = authorizer

    server = FTPServer(("0.0.0.0", 2121), handler)
    server.max_cons = 256
    server.max_cons_per_ip = 50

    logger.info("=" * 50)
    logger.info("FTP server starting on 0.0.0.0:2121")
    logger.info("Upload directory: %s", UPLOAD_DIR)
    logger.info("Photographer user configured: yes")
    logger.info("=" * 50)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down (Ctrl+C received)")
        server.close_all()


if __name__ == "__main__":
    main()