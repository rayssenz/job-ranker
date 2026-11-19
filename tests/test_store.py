import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobranker.models import Posting
from jobranker.store import Outcome, Store

T1 = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)


def make_posting(**changes: str) -> Posting:
    fields = {
        "source": "greenhouse",
        "board": "northwindrobotics",
        "posting_id": "1001",
        "company": "Northwind Robotics",
        "title": "ML Engineer",
        "location": "Lisbon",
        "url": "https://example.test/jobs/1001",
        "description": "Build models.",
    }
    return Posting.model_validate(fields | changes)


@pytest.fixture
def store(tmp_path: Path) -> Store:
    return Store(tmp_path / "ranker.db")


def test_creates_missing_folder_and_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "data" / "ranker.db"
    Store(path).close()
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    connection.close()


def test_first_save_is_new_and_second_is_seen(store: Store) -> None:
    posting = make_posting()
    assert store.save(posting, T1) is Outcome.NEW
    assert store.save(posting, T2) is Outcome.SEEN
    stored = store.get("greenhouse", "northwindrobotics", "1001")
    assert stored is not None
    assert stored.first_seen == T1
    assert stored.last_seen == T2
    assert stored.duplicate_of is None
    assert len(store.versions(stored.id)) == 1


def test_stored_fields_round_trip(store: Store) -> None:
    posting = make_posting(remote="yes")
    store.save(posting, T1)
    stored = store.get("greenhouse", "northwindrobotics", "1001")
    assert stored is not None
    assert stored.posting == posting
    assert stored.content_hash == posting.content_hash


def test_changed_text_keeps_first_seen_and_records_version(store: Store) -> None:
    store.save(make_posting(), T1)
    changed = make_posting(description="Build better models.")
    assert store.save(changed, T2) is Outcome.CHANGED
    stored = store.get("greenhouse", "northwindrobotics", "1001")
    assert stored is not None
    assert stored.first_seen == T1
    assert stored.last_seen == T2
    assert stored.posting.description == "Build better models."
    assert store.versions(stored.id) == [
        (make_posting().content_hash, T1),
        (changed.content_hash, T2),
    ]


def test_same_id_on_other_board_or_source_is_separate(store: Store) -> None:
    assert store.save(make_posting(), T1) is Outcome.NEW
    assert store.save(make_posting(board="other", title="Data Engineer"), T1) is Outcome.NEW
    assert store.save(make_posting(source="lever", title="Platform Engineer"), T1) is Outcome.NEW
    assert store.count() == 3


def test_cross_source_match_is_duplicate_and_links_to_original(store: Store) -> None:
    store.save(make_posting(), T1)
    copy = make_posting(
        source="linkedin", board="", posting_id="900", company="northwind robotics GmbH"
    )
    assert store.save(copy, T1) is Outcome.DUPLICATE
    original = store.get("greenhouse", "northwindrobotics", "1001")
    stored = store.get("linkedin", "", "900")
    assert original is not None and stored is not None
    assert stored.duplicate_of == original.id


def test_same_source_same_title_is_not_linked(store: Store) -> None:
    assert store.save(make_posting(), T1) is Outcome.NEW
    assert store.save(make_posting(posting_id="1002", location="Porto"), T1) is Outcome.NEW


def test_duplicate_of_points_to_root(store: Store) -> None:
    store.save(make_posting(), T1)
    store.save(make_posting(source="linkedin", board="", posting_id="900"), T1)
    assert store.save(make_posting(source="lever", posting_id="77"), T1) is Outcome.DUPLICATE
    root = store.get("greenhouse", "northwindrobotics", "1001")
    third = store.get("lever", "northwindrobotics", "77")
    assert root is not None and third is not None
    assert third.duplicate_of == root.id


def test_duplicate_seen_again_stays_a_duplicate(store: Store) -> None:
    store.save(make_posting(), T1)
    copy = make_posting(source="linkedin", board="", posting_id="900")
    store.save(copy, T1)
    assert store.save(copy, T2) is Outcome.SEEN
    stored = store.get("linkedin", "", "900")
    assert stored is not None and stored.duplicate_of is not None


def test_reopening_keeps_data(tmp_path: Path) -> None:
    path = tmp_path / "ranker.db"
    with Store(path) as first:
        first.save(make_posting(), T1)
    with Store(path) as second:
        assert second.save(make_posting(), T2) is Outcome.SEEN


def test_unknown_schema_version_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "ranker.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version = 99")
    connection.close()
    with pytest.raises(RuntimeError, match="99"):
        Store(path)


def test_log_run_round_trip(store: Store) -> None:
    store.log_run("run1", T1, "greenhouse", "Northwind Robotics", fetched=3, new=2, changed=1)
    store.log_run("run1", T1, "lever", "Bluefjord Labs", error="HTTP 404")
    rows = store.runs()
    assert [(r["source"], r["fetched"], r["new"], r["changed"], r["error"]) for r in rows] == [
        ("greenhouse", 3, 2, 1, None),
        ("lever", 0, 0, 0, "HTTP 404"),
    ]
    assert rows[0]["run_id"] == "run1"
