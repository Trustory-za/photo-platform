"""Regression test: the test suite must never point at the production
photos.db.

database.py used to call _init_db() at import time against a hardcoded
path, so simply importing database (transitively via api, via conftest)
touched the real production database before any test could redirect it.
conftest.py must set PHOTO_PLATFORM_DB_PATH to a disposable path before
database/api are imported.
"""

from pathlib import Path

import database


def test_db_path_is_not_production_during_tests():
    production_path = (Path(__file__).resolve().parent.parent / "photos.db").resolve()
    assert Path(database.DB_PATH).resolve() != production_path
