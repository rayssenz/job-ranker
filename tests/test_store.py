import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobranker.models import Posting
from jobranker.store import Outcome, Store, StoreError

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


def linkedin_posting(posting_id: str, **changes: str) -> Posting:
    return make_posting(source="linkedin", board="", posting_id=posting_id, **changes)


def link_of(store: Store, posting: Posting) -> int | None:
    stored = store.get(posting.source, posting.board, posting.posting_id)
    assert stored is not None
    return stored.duplicate_of


def id_of(store: Store, posting: Posting) -> int:
    stored = store.get(posting.source, posting.board, posting.posting_id)
    assert stored is not None
    return stored.id


def test_second_posting_of_a_source_is_not_linked_through_another_source(store: Store) -> None:
    first, feed, second = linkedin_posting("900"), make_posting(), linkedin_posting("901")
    assert store.save(first, T1) is Outcome.NEW
    assert store.save(feed, T1) is Outcome.DUPLICATE
    assert store.save(second, T1) is Outcome.NEW
    assert link_of(store, feed) == id_of(store, first)
    assert link_of(store, second) is None


def test_retitled_copy_loses_its_link(store: Store) -> None:
    store.save(make_posting(), T1)
    store.save(linkedin_posting("900"), T1)
    retitled = linkedin_posting("900", title="Data Engineer")
    assert store.save(retitled, T2) is Outcome.CHANGED
    assert link_of(store, retitled) is None


def test_feed_posting_retitled_to_match_a_stored_original_gains_a_link(store: Store) -> None:
    original = linkedin_posting("900")
    store.save(original, T1)
    assert store.save(make_posting(title="Data Engineer"), T1) is Outcome.NEW
    assert store.save(make_posting(), T2) is Outcome.CHANGED
    assert link_of(store, make_posting()) == id_of(store, original)


def test_copy_of_a_retitled_original_is_checked_again(store: Store) -> None:
    store.save(make_posting(), T1)
    copy = linkedin_posting("900")
    store.save(copy, T1)
    assert store.save(make_posting(title="Data Engineer"), T2) is Outcome.CHANGED
    assert link_of(store, make_posting()) is None
    assert link_of(store, copy) is None


def test_copies_of_a_retitled_original_are_linked_to_each_other(store: Store) -> None:
    store.save(make_posting(), T1)
    first, second = linkedin_posting("900"), make_posting(source="lever", posting_id="77")
    store.save(first, T1)
    store.save(second, T1)
    store.save(make_posting(title="Data Engineer"), T2)
    assert link_of(store, first) is None
    assert link_of(store, second) == id_of(store, first)


def test_copy_that_still_matches_a_retitled_posting_keeps_its_link(store: Store) -> None:
    store.save(make_posting(), T1)
    copy = linkedin_posting("900")
    store.save(copy, T1)
    assert store.save(make_posting(title="ML engineer!"), T2) is Outcome.CHANGED
    assert link_of(store, copy) == id_of(store, make_posting())


def test_corrected_company_and_url_reach_a_stored_posting(store: Store) -> None:
    store.save(make_posting(company="Northwind Robots"), T1)
    corrected = make_posting(url="https://example.test/jobs/new-1001")
    assert store.save(corrected, T2) is Outcome.SEEN
    stored = store.get("greenhouse", "northwindrobotics", "1001")
    assert stored is not None
    assert stored.posting == corrected
    assert stored.first_seen == T1
    assert stored.last_seen == T2
    assert len(store.versions(stored.id)) == 1
    # The stored match key follows the company name, so a later copy is recognised.
    assert store.save(linkedin_posting("900"), T2) is Outcome.DUPLICATE


def test_corrected_company_name_rechecks_the_link(store: Store) -> None:
    original = linkedin_posting("900")
    store.save(original, T1)
    assert store.save(make_posting(company="Northwind Robots"), T1) is Outcome.NEW
    assert store.save(make_posting(), T2) is Outcome.SEEN
    assert link_of(store, make_posting()) == id_of(store, original)


def test_renamed_company_drops_the_link_of_its_copy(store: Store) -> None:
    store.save(make_posting(), T1)
    copy = linkedin_posting("900")
    store.save(copy, T1)
    assert store.save(make_posting(company="Harborline"), T2) is Outcome.SEEN
    assert link_of(store, copy) is None


def test_punctuation_only_title_is_never_linked(store: Store) -> None:
    assert store.save(make_posting(title="???"), T1) is Outcome.NEW
    assert store.save(linkedin_posting("900", title="---"), T1) is Outcome.NEW
    assert store.save(make_posting(source="lever", posting_id="77", title="!"), T1) is Outcome.NEW
    assert link_of(store, linkedin_posting("900")) is None


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


def assert_refused(path: Path) -> None:
    with pytest.raises(StoreError) as error:
        Store(path)
    assert str(path) in str(error.value)
    assert error.value.__cause__ is None


def test_file_that_is_not_a_database_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "ranker.db"
    path.write_text("This is a text file, not a database. " * 40)
    assert_refused(path)


def test_directory_as_database_is_refused(tmp_path: Path) -> None:
    assert_refused(tmp_path)


def test_database_under_a_file_is_refused(tmp_path: Path) -> None:
    blocker = tmp_path / "data"
    blocker.write_text("not a folder")
    assert_refused(blocker / "ranker.db")


def test_log_run_round_trip(store: Store) -> None:
    store.log_run("run1", T1, "greenhouse", "Northwind Robotics", fetched=3, new=2, changed=1)
    store.log_run("run1", T1, "lever", "Bluefjord Labs", error="HTTP 404")
    rows = store.runs()
    assert [(r["source"], r["fetched"], r["new"], r["changed"], r["error"]) for r in rows] == [
        ("greenhouse", 3, 2, 1, None),
        ("lever", 0, 0, 0, "HTTP 404"),
    ]
    assert rows[0]["run_id"] == "run1"
