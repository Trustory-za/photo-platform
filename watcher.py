#!/usr/bin/env python3
"""
watcher.py — File watcher for the Trustory Images photo platform.

Watches uploads/incoming/ for new JPG files. When a new file arrives, it
automatically runs process_image.py and saves the output to uploads/processed/.

Usage:
    python watcher.py

The watcher runs forever. Stop it with Ctrl+C.
"""

import json
import logging
import subprocess
import sys
import time
from pathlib import Path

# Local imports
import database

from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer

# ── Paths ───────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
INCOMING_DIR = BASE_DIR / "uploads" / "incoming"
PROCESSED_DIR = BASE_DIR / "uploads" / "processed"
LOG_DIR = BASE_DIR / "logs"
PROCESS_SCRIPT = BASE_DIR / "process_image.py"
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"

# ── Bootstrap directories ───────────────────────────────────────────────

INCOMING_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging ─────────────────────────────────────────────────────────────

watcher_log = LOG_DIR / "watcher.log"
logger = logging.getLogger("watcher")
logger.setLevel(logging.INFO)

fmt = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)

fh = logging.FileHandler(str(watcher_log))
fh.setFormatter(fmt)
logger.addHandler(fh)

ch = logging.StreamHandler()
ch.setFormatter(fmt)
logger.addHandler(ch)


# ── Helpers ─────────────────────────────────────────────────────────────

def _process_jpg(file_path: Path) -> None:
    """Run process_image.py on a JPG file and log the result."""
    logger.info("PROCESSING %s", file_path.name)

    try:
        result = subprocess.run(
            [
                str(VENV_PYTHON),
                str(PROCESS_SCRIPT),
                str(file_path),
                str(PROCESSED_DIR),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.error("TIMEOUT %s  (exceeded 120s)", file_path.name)
        return
    except Exception as e:
        logger.error("SUBPROCESS FAILED %s  (%s)", file_path.name, e)
        return

    # Parse JSON output
    try:
        data = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(
            "JSON PARSE ERROR %s  (stdout: %s) (stderr: %s)",
            file_path.name,
            result.stdout.strip(),
            result.stderr.strip(),
        )
        return

    # Log the result
    if data.get("success"):
        iptc_fields = list(data.get("iptc", {}).keys())
        orig_size = data.get("file_size_original", "?")
        prev_size = data.get("file_size_preview", "?")

        logger.info(
            "PROCESSED %s  IPTC fields: %s  original: %s bytes  preview: %s bytes",
            file_path.name,
            iptc_fields if iptc_fields else "(none)",
            orig_size,
            prev_size,
        )

        # Insert into database
        try:
            row_id = database.insert_photo(data)
            logger.info("DB INSERT %s  row_id=%s", file_path.name, row_id)
        except Exception as e:
            logger.error("DB INSERT FAILED %s  (%s)", file_path.name, e)
    else:
        logger.error(
            "PROCESSING FAILED %s  error: %s",
            file_path.name,
            data.get("error", "unknown"),
        )
        if result.stderr.strip():
            logger.error("STDERR %s  %s", file_path.name, result.stderr.strip())


# ── Event handler ──────────────────────────────────────────────────────

class JpgUploadHandler(PatternMatchingEventHandler):
    """Watch for new JPG files in the incoming directory."""

    def __init__(self):
        # Only respond to JPG/JPEG files — skip non-JPG silently
        super().__init__(
            patterns=["*.jpg", "*.jpeg"],
            ignore_directories=True,
            case_sensitive=False,
        )
        # Track recently processed paths to avoid double-processing
        self._recently_processed: dict[str, float] = {}
        # Track files currently being checked for stability
        self._pending_check: set[str] = set()
        # Track files already processed in this session
        self._processed_files: set[str] = set()

    def on_created(self, event):
        logger.debug("EVENT on_created: %s", event.src_path)
        self._handle(event)

    def on_modified(self, event):
        logger.debug("EVENT on_modified: %s", event.src_path)
        self._handle(event)

    def on_moved(self, event):
        logger.debug("EVENT on_moved: %s -> %s", getattr(event, 'src_path', ''), getattr(event, 'dest_path', ''))
        self._handle(event)

    def _wait_until_stable(self, file_path: Path, max_checks: int = 20) -> bool:
        """
        Wait for a file to finish being written.

        Strategy:
          1. Wait 3 seconds for the initial write burst to settle.
          2. Check the file size.
          3. Wait 2 more seconds and check again.
          4. If the size is the same both times, cross-check the modification
             timestamp — if the file was modified within the last 3 seconds
             it may still be receiving data over a slow connection.
          5. If not stable, keep checking (up to *max_checks* pairs).

        Returns True if the file is stable, False if it gave up.
        """
        for attempt in range(1, max_checks + 1):
            # Initial wait is longer; subsequent waits use shorter gaps
            if attempt == 1:
                time.sleep(3.0)
            else:
                time.sleep(2.0)

            if not file_path.exists():
                logger.warning("STABILITY FILE VANISHED %s  (attempt %d/%d)",
                               file_path.name, attempt, max_checks)
                return False

            size_a = file_path.stat().st_size

            if size_a == 0:
                logger.debug("STABILITY EMPTY %s  (attempt %d/%d, still writing…)",
                             file_path.name, attempt, max_checks)
                continue

            time.sleep(2.0)

            if not file_path.exists():
                logger.warning("STABILITY FILE VANISHED %s  (attempt %d/%d, after second wait)",
                               file_path.name, attempt, max_checks)
                return False

            size_b = file_path.stat().st_size

            if size_a != size_b:
                logger.debug("STABILITY GROWING %s  size changed: %d → %d  (attempt %d/%d)",
                             file_path.name, size_a, size_b, attempt, max_checks)
                continue

            # Sizes match — now check the modification time.
            # If the file was modified in the last 3 seconds, the FTP
            # connection may still be open despite a momentary pause.
            age = time.time() - file_path.stat().st_mtime
            if age < 3.0:
                logger.debug("STABILITY YOUNG %s  size=%d bytes  mtime_age=%.1fs (attempt %d/%d)",
                             file_path.name, size_a, age, attempt, max_checks)
                continue

            logger.info("STABLE %s  size=%d bytes  mtime_age=%.1fs  (after %d check pair%s)",
                        file_path.name, size_a, age, attempt,
                        "s" if attempt > 1 else "")
            return True

        # Exhausted all attempts — file is still changing or stuck
        logger.error("STABILITY TIMEOUT %s  (not stable after %d checks)",
                     file_path.name, max_checks)
        return False

    def _handle(self, event):
        """Process the file — wait for it to be fully written first."""
        src = event.src_path
        logger.debug("_handle called: src_path=%s", src)

        file_path = Path(src)

        # Dedup guard — skip files we recently processed
        now = time.time()
        last = self._recently_processed.get(src, 0)
        if now - last < 5.0:
            logger.debug("SKIP (recently processed) %s", file_path.name)
            return

        # Session dedup — skip files already processed in this session lifetime
        if src in self._processed_files:
            logger.debug("SKIP (already processed this session) %s", file_path.name)
            return

        logger.debug("_handle: resolved=%s suffix=%s exists=%s size=%s",
                     file_path, file_path.suffix, file_path.exists(),
                     file_path.stat().st_size if file_path.exists() else 'N/A')

        # Guard: make sure it still exists (could have been moved away)
        if not file_path.exists():
            return

        # Guard: skip non-JPG extensions (case-insensitive)
        if file_path.suffix.lower() not in (".jpg", ".jpeg"):
            return

        # Dedup: skip if another check is already running for this file
        if src in self._pending_check:
            logger.debug("SKIP (already being checked) %s", file_path.name)
            return

        self._pending_check.add(src)

        # Wait until the file is fully written (FTP may still be flushing)
        if not self._wait_until_stable(file_path):
            logger.warning("ABORT %s  (file never stabilised)", file_path.name)
            self._pending_check.discard(src)
            return

        _process_jpg(file_path)

        # Mark as processed so duplicate events are ignored
        self._recently_processed[src] = time.time()
        self._processed_files.add(src)

        # Clear the pending-check lock
        self._pending_check.discard(src)


# ── Main ────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 50)
    logger.info("Watcher starting")
    logger.info("Watching: %s", INCOMING_DIR)
    logger.info("Output:   %s", PROCESSED_DIR)
    logger.info("=" * 50)

    event_handler = JpgUploadHandler()
    observer = Observer()
    observer.schedule(event_handler, str(INCOMING_DIR), recursive=False)
    observer.start()

    try:
        while observer.is_alive():
            observer.join(1)
    except KeyboardInterrupt:
        logger.info("Shutting down (Ctrl+C received)")
        observer.stop()
    observer.join()
    logger.info("Watcher stopped")


if __name__ == "__main__":
    main()