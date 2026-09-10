"""Import-time isolation for ftp_server.

Importing ftp_server — e.g. to reach PhotoFTPHandler for the callback tests
in test_ftp_handler.py — must never require FTP_PASSWORD or bind a network
socket. Only main() should touch credentials, the authorizer, or the
listening socket; module import must succeed on a clean checkout with no
.env and no FTP_PASSWORD in the environment.

This is proven via a subprocess: the module is copied into an isolated
temp directory (so dotenv has no .env file to find) and run with
FTP_PASSWORD absent from the environment. This fails against the
pre-refactor module, which validates FTP_PASSWORD and calls sys.exit(1)
at import time, and passes once that validation moves into main().
"""

import logging
import shutil
import subprocess
import sys
from pathlib import Path

import ftp_server

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_import_does_not_require_ftp_password_or_bind_socket(tmp_path):
    isolated_dir = tmp_path / "isolated_module"
    isolated_dir.mkdir()
    shutil.copy(PROJECT_ROOT / "ftp_server.py", isolated_dir / "ftp_server.py")
    # Deliberately no .env copied alongside it — proves dotenv finds
    # nothing to load, matching a clean checkout.

    # Does not bind port 2121 itself — a real production FTP server may
    # already be listening there on this machine. Instead it proves no
    # socket was bound at import time by checking that main() (the only
    # place FTPServer is constructed and the 'photographer' user is
    # registered) never ran.
    probe = (
        "import ftp_server\n"
        "assert ftp_server.PhotoFTPHandler is not None\n"
        "assert callable(ftp_server.main)\n"
        "assert not ftp_server.PhotoFTPHandler.authorizer.has_user('photographer')\n"
        "print('IMPORT_OK')\n"
    )

    env = {"PATH": "/usr/bin:/bin"}
    # FTP_PASSWORD intentionally absent — this is the whole point.

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=isolated_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, (
        "importing ftp_server with FTP_PASSWORD absent and no .env "
        f"reachable must succeed and not bind a socket.\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "IMPORT_OK" in result.stdout


def test_import_does_not_create_directories_or_attach_log_handler(tmp_path):
    """Importing ftp_server must not create uploads/incoming or logs/ nor
    install a FileHandler on logs/ftp.log. Production incident: every
    pytest run that imported this module (directly, e.g. from
    test_ftp_handler.py) created those directories under the real repo
    and attached a FileHandler that later test log calls wrote into,
    mutating the production ftp.log. Only main() (via configure_runtime())
    may do that.

    Proven in an isolated copy of the module so directory
    presence/absence is directly observable, rather than against the
    real repo where uploads/ and logs/ already exist.
    """
    isolated_dir = tmp_path / "isolated_module_no_dirs"
    isolated_dir.mkdir()
    shutil.copy(PROJECT_ROOT / "ftp_server.py", isolated_dir / "ftp_server.py")

    probe = (
        "import logging\n"
        "import ftp_server\n"
        "assert not (ftp_server.BASE_DIR / 'uploads').exists(), 'uploads dir created at import'\n"
        "assert not (ftp_server.BASE_DIR / 'logs').exists(), 'logs dir created at import'\n"
        "assert not any(isinstance(h, logging.FileHandler) for h in ftp_server.logger.handlers), "
        "'FileHandler attached at import'\n"
        "print('NO_IMPORT_SIDE_EFFECTS')\n"
    )
    env = {"PATH": "/usr/bin:/bin"}

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=isolated_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert result.returncode == 0, (
        "importing ftp_server must not create runtime directories or "
        f"attach a log FileHandler.\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "NO_IMPORT_SIDE_EFFECTS" in result.stdout


def test_in_process_import_installs_no_file_handler():
    """The exact in-process import path used by test_ftp_handler.py (and
    this module) — `import ftp_server` at module scope, no subprocess —
    must never have attached a FileHandler to the production
    logs/ftp.log. This is the direct proof that the callback tests in
    test_ftp_handler.py, which call PhotoFTPHandler.on_file_received and
    log through this exact logger, cannot write into the real
    logs/ftp.log."""
    assert not any(
        isinstance(h, logging.FileHandler) for h in ftp_server.logger.handlers
    )
