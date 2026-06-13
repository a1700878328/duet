"""Test config: isolate the DB to a temp file before app modules import.

Must set DB_URL before `app.config` / `app.db` are imported anywhere.
"""

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.gettempdir()) / "duet_test.db"
os.environ.setdefault("DB_URL", f"sqlite+aiosqlite:///{_tmp.as_posix()}")
os.environ.setdefault("JWT_SECRET", "test-secret-padding-to-32-bytes-minimum-xx")
