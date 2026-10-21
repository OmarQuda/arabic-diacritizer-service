import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.errors import ServiceError
from app.validation import count_changed, strip_diacritics


class Corrections:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL, request_id TEXT NOT NULL,
                input TEXT NOT NULL, model_output TEXT NOT NULL,
                corrected TEXT NOT NULL, note TEXT NOT NULL,
                diacritics_changed INTEGER NOT NULL CHECK(diacritics_changed >= 0)
            )""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def store(self, *, request_id: str, input: str, model_output: str, corrected: str, note: str) -> dict:
        if strip_diacritics(corrected) != strip_diacritics(input):
            raise ServiceError(422, "invalid_correction", reason="base_text_mismatch")
        created = datetime.now(timezone.utc).isoformat()
        changed = count_changed(model_output, corrected)
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO corrections (created_at, request_id, input, model_output, corrected, note, diacritics_changed) VALUES (?,?,?,?,?,?,?)",
                (created, request_id, input, model_output, corrected, note, changed),
            )
            return {"id": cursor.lastrowid, "created_at": created, "request_id": request_id, "diacritics_changed": changed}

    def list(self, limit: int) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM corrections ORDER BY id DESC LIMIT ?", (limit,))]
