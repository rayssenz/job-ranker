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
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
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


def test_database_of_another_program_is_refused_and_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "other.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE users (id INTEGER)")
    connection.commit()
    connection.close()
    assert_refused(path)
    connection = sqlite3.connect(path)
    tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master")]
    connection.close()
    assert tables == ["users"]


# The schema of milestone 1, kept here so the upgrade is tested against what was shipped.
SCHEMA_V1 = """
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


def version_1_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_V1)
    connection.execute(
        "INSERT INTO postings VALUES (1, 'greenhouse', 'northwindrobotics', '1001',"
        " 'Northwind Robotics', 'ML Engineer', 'Lisbon', 'unknown', 'https://example.test/1',"
        " 'Build models.', 'hash-1', 'northwind robotics|ml engineer', NULL, ?, ?)",
        (T1.isoformat(), T1.isoformat()),
    )
    connection.execute("INSERT INTO posting_versions VALUES (1, 'hash-1', ?)", (T1.isoformat(),))
    connection.execute(
        "INSERT INTO run_log VALUES ('run1', ?, 'greenhouse', 'Northwind Robotics',"
        " 1, 1, 0, 0, 0, NULL)",
        (T1.isoformat(),),
    )
    connection.execute("PRAGMA user_version = 1")
    connection.commit()
    connection.close()


def test_version_1_database_is_upgraded_and_keeps_its_rows(tmp_path: Path) -> None:
    path = tmp_path / "ranker.db"
    version_1_database(path)
    with Store(path) as store:
        assert store.count() == 1
        stored = store.get("greenhouse", "northwindrobotics", "1001")
        assert stored is not None
        assert (stored.posting.title, stored.first_seen) == ("ML Engineer", T1)
        assert store.versions(stored.id) == [("hash-1", T1)]
        assert [row["run_id"] for row in store.runs()] == ["run1"]
        assert store.pending_rules("profile-a", 1) == [stored]
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    connection.close()


def test_failed_upgrade_leaves_the_version_1_database_as_it_was(tmp_path: Path) -> None:
    path = tmp_path / "ranker.db"
    version_1_database(path)
    connection = sqlite3.connect(path)
    # A table of the same name makes the upgrade fail part-way.
    connection.execute("CREATE TABLE rule_results (other INTEGER)")
    connection.commit()
    connection.close()
    assert_refused(path)
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM postings").fetchone()[0] == 1
    columns = [row[1] for row in connection.execute("PRAGMA table_info(rule_results)")]
    connection.close()
    assert columns == ["other"]


def checked(store: Store, posting: Posting, reasons: list[str], profile: str = "profile-a") -> None:
    stored = store.get(posting.source, posting.board, posting.posting_id)
    assert stored is not None
    store.save_rule_results([(stored, reasons)], profile, 1, T2)


def test_posting_without_a_result_is_pending_until_it_is_checked(store: Store) -> None:
    first, second = make_posting(), make_posting(posting_id="1002", title="Data Engineer")
    store.save(first, T1)
    store.save(second, T1)
    assert [s.posting for s in store.pending_rules("profile-a", 1)] == [first, second]
    checked(store, first, [])
    assert [s.posting for s in store.pending_rules("profile-a", 1)] == [second]
    checked(store, second, ["place", "level"])
    assert store.pending_rules("profile-a", 1) == []


def test_results_go_stale_with_the_profile_the_rules_or_the_posting(store: Store) -> None:
    first, second = make_posting(), make_posting(posting_id="1002", title="Data Engineer")
    store.save(first, T1)
    store.save(second, T1)
    checked(store, first, [])
    checked(store, second, [])
    assert len(store.pending_rules("profile-b", 1)) == 2
    assert len(store.pending_rules("profile-a", 2)) == 2
    changed = make_posting(description="Build better models.")
    store.save(changed, T2)
    assert [s.posting for s in store.pending_rules("profile-a", 1)] == [changed]
    checked(store, changed, ["level"])
    assert store.pending_rules("profile-a", 1) == []


def test_rule_counts_cover_current_results_only(store: Store) -> None:
    postings = [make_posting(posting_id=str(n), title=f"Role {n}") for n in range(1, 5)]
    for posting in postings:
        store.save(posting, T1)
    checked(store, postings[0], [])
    checked(store, postings[1], ["place"])
    checked(store, postings[2], ["place", "level"])
    checked(store, postings[3], [], profile="profile-old")
    assert store.rule_counts("profile-a", 1) == {
        "checked": 3,
        "passed": 1,
        "groups": 1,
        "place": 2,
        "level": 1,
    }


def test_group_passes_when_only_the_linked_copy_passes(store: Store) -> None:
    feed, copy = make_posting(location="Madrid"), linkedin_posting("900")
    store.save(feed, T1)
    assert store.save(copy, T2) is Outcome.DUPLICATE
    checked(store, feed, ["place"])
    checked(store, copy, [])
    groups = store.passed_groups("profile-a", 1, since=None, limit=10)
    assert [g.posting for g in groups] == [copy]
    assert store.rule_counts("profile-a", 1)["groups"] == 1


def test_group_is_listed_once_with_the_original_when_it_passed(store: Store) -> None:
    feed, copy = make_posting(), linkedin_posting("900")
    store.save(feed, T1)
    store.save(copy, T2)
    checked(store, feed, [])
    checked(store, copy, [])
    groups = store.passed_groups("profile-a", 1, since=None, limit=10)
    assert [g.posting for g in groups] == [feed]
    assert store.rule_counts("profile-a", 1) == {"checked": 2, "passed": 2, "groups": 1}


def test_passed_groups_are_newest_first_and_can_be_limited(store: Store) -> None:
    old = make_posting(posting_id="1", title="Old Role")
    new = make_posting(posting_id="2", title="New Role")
    dropped = make_posting(posting_id="3", title="Dropped Role")
    store.save(old, T1)
    store.save(new, T2)
    store.save(dropped, T2)
    checked(store, old, [])
    checked(store, new, [])
    checked(store, dropped, ["title"])
    listed = store.passed_groups("profile-a", 1, since=None, limit=10)
    assert [g.posting for g in listed] == [new, old]
    assert [g.posting for g in store.passed_groups("profile-a", 1, since=T2, limit=10)] == [new]
    assert [g.posting for g in store.passed_groups("profile-a", 1, since=None, limit=1)] == [new]
    assert store.passed_groups("profile-b", 1, since=None, limit=10) == []
