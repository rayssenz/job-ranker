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
        db: sqlite3.Connection | None = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(path)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                db.executescript(_SCHEMA)
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                db.commit()
        except (sqlite3.Error, OSError) as error:
            if db is not None:
                db.close()
            # The caller gets one kind of error and a message that names the file.
            raise StoreError(
                f"{path} cannot be used as the database ({type(error).__name__})"
            ) from None
        if version not in (0, SCHEMA_VERSION):
            db.close()
            raise StoreError(
                f"{path} has schema version {version}, this program needs {SCHEMA_VERSION}"
            )
        self._db = db

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
                "SELECT id, content_hash, company, url, match_key FROM postings"
                " WHERE source = ? AND board = ? AND posting_id = ?",
                (posting.source, posting.board, posting.posting_id),
            ).fetchone()
            if row is None:
                return self._insert(posting, content_hash, moment)
            rekeyed = row["match_key"] != posting.match_key
            if row["content_hash"] == content_hash:
                self._db.execute(
                    "UPDATE postings SET last_seen = ? WHERE id = ?", (moment, row["id"])
                )
                # The hash leaves out the company and the URL, so they are compared here.
                if rekeyed or (row["company"], row["url"]) != (posting.company, posting.url):
                    self._db.execute(
                        "UPDATE postings SET company = ?, url = ?, match_key = ? WHERE id = ?",
                        (posting.company, posting.url, posting.match_key, row["id"]),
                    )
                if rekeyed:
                    self._relink(row["id"], posting)
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
            if rekeyed:
                self._relink(row["id"], posting)
            return Outcome.CHANGED

    def _original(self, match_key: str, source: str, exclude: int | None = None) -> int | None:
        """The id of the posting that one with this match key and source duplicates, if any."""
        # An empty key means the company or the title has no word left, so nothing matches it.
        if not match_key:
            return None
        # Only another source's posting that is not itself a duplicate can be an original.
        match = self._db.execute(
            "SELECT id FROM postings WHERE match_key = ? AND source != ?"
            " AND duplicate_of IS NULL AND id IS NOT ? ORDER BY id LIMIT 1",
            (match_key, source, exclude),
        ).fetchone()
        return None if match is None else int(match["id"])

    def _relink(self, row_id: int, posting: Posting) -> None:
        """Recompute the links after the match key of a stored posting changed."""
        self._db.execute(
            "UPDATE postings SET duplicate_of = ? WHERE id = ?",
            (self._original(posting.match_key, posting.source, exclude=row_id), row_id),
        )
        # Copies that no longer match are looked up again, each after the one before it
        # was written, so the first can become the original of the next.
        dependents = self._db.execute(
            "SELECT id, match_key, source FROM postings"
            " WHERE duplicate_of = ? AND match_key != ? ORDER BY id",
            (row_id, posting.match_key),
        ).fetchall()
        for dependent in dependents:
            original = self._original(
                dependent["match_key"], dependent["source"], exclude=dependent["id"]
            )
            self._db.execute(
                "UPDATE postings SET duplicate_of = ? WHERE id = ?", (original, dependent["id"])
            )

    def _insert(self, posting: Posting, content_hash: str, moment: str) -> Outcome:
        original = self._original(posting.match_key, posting.source)
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
