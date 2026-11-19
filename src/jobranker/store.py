"""SQLite storage for postings, their versions and the run log."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import Self

from jobranker.models import Posting, Remote

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE postings (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  board TEXT NOT NULL,
  posting_id TEXT NOT NULL,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  location TEXT NOT NULL,
  remote TEXT NOT NULL,
  url TEXT NOT NULL,
  description TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  match_key TEXT NOT NULL,
  duplicate_of INTEGER REFERENCES postings(id),
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  UNIQUE (source, board, posting_id)
);
CREATE INDEX postings_match_key ON postings (match_key);
CREATE TABLE posting_versions (
  posting_id INTEGER NOT NULL REFERENCES postings(id),
  content_hash TEXT NOT NULL,
  seen_at TEXT NOT NULL
);
CREATE TABLE run_log (
  run_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  source TEXT NOT NULL,
  target TEXT NOT NULL,
  fetched INTEGER NOT NULL,
  new INTEGER NOT NULL,
  changed INTEGER NOT NULL,
  duplicate INTEGER NOT NULL,
  skipped INTEGER NOT NULL,
  error TEXT
);
"""


class StoreError(RuntimeError):
    """A database file this program cannot use."""


class Outcome(StrEnum):
    """What saving a posting did."""

    NEW = "new"
    CHANGED = "changed"
    SEEN = "seen"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class StoredPosting:
    id: int
    posting: Posting
    content_hash: str
    duplicate_of: int | None
    first_seen: datetime
    last_seen: datetime


def _to_text(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


class Store:
    """One SQLite file. Creates the folder and the schema on first use."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self._db.executescript(_SCHEMA)
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._db.commit()
        elif version != SCHEMA_VERSION:
            self._db.close()
            raise StoreError(
                f"{path} has schema version {version}, this program needs {SCHEMA_VERSION}"
            )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._db.close()

    def save(self, posting: Posting, now: datetime) -> Outcome:
        """Insert or update one posting and say what happened."""
        moment = _to_text(now)
        content_hash = posting.content_hash
        with self._db:
            row = self._db.execute(
                "SELECT id, content_hash FROM postings"
                " WHERE source = ? AND board = ? AND posting_id = ?",
                (posting.source, posting.board, posting.posting_id),
            ).fetchone()
            if row is None:
                return self._insert(posting, content_hash, moment)
            if row["content_hash"] == content_hash:
                self._db.execute(
                    "UPDATE postings SET last_seen = ? WHERE id = ?", (moment, row["id"])
                )
                return Outcome.SEEN
            self._db.execute(
                "UPDATE postings SET company = ?, title = ?, location = ?, remote = ?, url = ?,"
                " description = ?, content_hash = ?, match_key = ?, last_seen = ? WHERE id = ?",
                (
                    posting.company,
                    posting.title,
                    posting.location,
                    posting.remote.value,
                    posting.url,
                    posting.description,
                    content_hash,
                    posting.match_key,
                    moment,
                    row["id"],
                ),
            )
            self._add_version(row["id"], content_hash, moment)
            return Outcome.CHANGED

    def _insert(self, posting: Posting, content_hash: str, moment: str) -> Outcome:
        match = self._db.execute(
            "SELECT id, duplicate_of FROM postings WHERE match_key = ? AND source != ?"
            " ORDER BY id LIMIT 1",
            (posting.match_key, posting.source),
        ).fetchone()
        original = None if match is None else (match["duplicate_of"] or match["id"])
        cursor = self._db.execute(
            "INSERT INTO postings (source, board, posting_id, company, title, location, remote,"
            " url, description, content_hash, match_key, duplicate_of, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                posting.source,
                posting.board,
                posting.posting_id,
                posting.company,
                posting.title,
                posting.location,
                posting.remote.value,
                posting.url,
                posting.description,
                content_hash,
                posting.match_key,
                original,
                moment,
                moment,
            ),
        )
        assert cursor.lastrowid is not None
        self._add_version(cursor.lastrowid, content_hash, moment)
        return Outcome.NEW if original is None else Outcome.DUPLICATE

    def _add_version(self, row_id: int, content_hash: str, moment: str) -> None:
        self._db.execute(
            "INSERT INTO posting_versions (posting_id, content_hash, seen_at) VALUES (?, ?, ?)",
            (row_id, content_hash, moment),
        )

    def log_run(
        self,
        run_id: str,
        started_at: datetime,
        source: str,
        target: str,
        *,
        fetched: int = 0,
        new: int = 0,
        changed: int = 0,
        duplicate: int = 0,
        skipped: int = 0,
        error: str | None = None,
    ) -> None:
        with self._db:
            self._db.execute(
                "INSERT INTO run_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    _to_text(started_at),
                    source,
                    target,
                    fetched,
                    new,
                    changed,
                    duplicate,
                    skipped,
                    error,
                ),
            )

    def get(self, source: str, board: str, posting_id: str) -> StoredPosting | None:
        row = self._db.execute(
            "SELECT * FROM postings WHERE source = ? AND board = ? AND posting_id = ?",
            (source, board, posting_id),
        ).fetchone()
        if row is None:
            return None
        return StoredPosting(
            id=row["id"],
            posting=Posting(
                source=row["source"],
                board=row["board"],
                posting_id=row["posting_id"],
                company=row["company"],
                title=row["title"],
                location=row["location"],
                remote=Remote(row["remote"]),
                url=row["url"],
                description=row["description"],
            ),
            content_hash=row["content_hash"],
            duplicate_of=row["duplicate_of"],
            first_seen=datetime.fromisoformat(row["first_seen"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
        )

    def count(self) -> int:
        result: int = self._db.execute("SELECT COUNT(*) FROM postings").fetchone()[0]
        return result

    def versions(self, row_id: int) -> list[tuple[str, datetime]]:
        rows = self._db.execute(
            "SELECT content_hash, seen_at FROM posting_versions WHERE posting_id = ?"
            " ORDER BY rowid",
            (row_id,),
        ).fetchall()
        return [(row["content_hash"], datetime.fromisoformat(row["seen_at"])) for row in rows]

    def runs(self) -> list[sqlite3.Row]:
        return self._db.execute("SELECT * FROM run_log ORDER BY rowid").fetchall()

    def dump(self) -> str:
        """The whole database as SQL text, for checks that nothing private was stored."""
        return "\n".join(self._db.iterdump())
