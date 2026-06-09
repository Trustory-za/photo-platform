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

# ── Bootstrap ───────────────────────────────────────────────────────────

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Load .env from the project root
load_dotenv(BASE_DIR / ".env")

FTP_PASSWORD = os.getenv("FTP_PASSWORD")
if not FTP_PASSWORD:
    print("FATAL: FTP_PASSWORD not set in .env", file=sys.stderr)
    sys.exit(1)

# ── Logging ─────────────────────────────────────────────────────────────

ftp_log = LOG_DIR / "ftp.log"
logger = logging.getLogger("ftp_server")
logger.setLevel(logging.INFO)

fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

fh = logging.FileHandler(str(ftp_log))
fh.setFormatter(fmt)
logger.addHandler(fh)

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
        logger.info("UPLOAD %s  (size: %d bytes)", file, self.fsize)

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


# ── Authorizer ─────────────────────────────────────────────────────────

authorizer = DummyAuthorizer()

# User 'photographer' — upload only, no delete/overwrite/rename/retrieve
# Overwrite blocking is handled in the custom ftp_STOR method above
authorizer.add_user(
    "photographer",
    FTP_PASSWORD,
    str(UPLOAD_DIR),
    perm="elw",  # enter directory, list files, write (upload) — no delete/rename/retrieve
)


# ── Server ──────────────────────────────────────────────────────────────

handler = PhotoFTPHandler
handler.authorizer = authorizer

# Recommended permissions so uploaded files are readable by the watcher
handler.umask = 0o022

server = FTPServer(("0.0.0.0", 2121), handler)
server.max_cons = 256
server.max_cons_per_ip = 50


def main():
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