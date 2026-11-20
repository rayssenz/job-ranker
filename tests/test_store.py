import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from jobranker.models import Posting, Verdict
from jobranker.store import Decision, Outcome, RunSummary, Store, StoreError

T1 = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)
T2 = datetime(2026, 11, 20, 8, 0, tzinfo=UTC)
T3 = datetime(2026, 11, 21, 8, 0, tzinfo=UTC)
T4 = datetime(2026, 11, 22, 8, 0, tzinfo=UTC)


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
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
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


@pytest.mark.parametrize("version", [-1, 5, 99])
def test_version_without_an_upgrade_step_is_refused(tmp_path: Path, version: int) -> None:
    path = tmp_path / "ranker.db"
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version = {version}")
    connection.close()
    assert_refused(path)


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
        assert store.decide(stored.id, Decision.APPLIED, T2)
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
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


# The table milestone 2 added, kept here for the same reason as the schema above.
SCHEMA_V2 = """
CREATE TABLE rule_results (
  posting_id INTEGER PRIMARY KEY REFERENCES postings(id),
  content_hash TEXT NOT NULL,
  profile_hash TEXT NOT NULL,
  rules_version INTEGER NOT NULL,
  passed INTEGER NOT NULL,
  reasons TEXT NOT NULL,
  checked_at TEXT NOT NULL
);
"""


def version_2_database(path: Path) -> None:
    version_1_database(path)
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_V2)
    connection.execute(
        "INSERT INTO rule_results VALUES (1, 'hash-1', 'profile-a', 1, 1, '', ?)",
        (T2.isoformat(),),
    )
    connection.execute("PRAGMA user_version = 2")
    connection.commit()
    connection.close()


def test_version_2_database_is_upgraded_and_keeps_its_rows(tmp_path: Path) -> None:
    path = tmp_path / "ranker.db"
    version_2_database(path)
    with Store(path) as store:
        assert store.count() == 1
        stored = store.get("greenhouse", "northwindrobotics", "1001")
        assert stored is not None
        assert (stored.posting.title, stored.first_seen) == ("ML Engineer", T1)
        assert store.versions(stored.id) == [("hash-1", T1)]
        assert [row["run_id"] for row in store.runs()] == ["run1"]
        # The stored rule result is still the current one.
        assert store.pending_rules("profile-a", 1) == []
        assert store.rule_counts("profile-a", 1) == {"checked": 1, "passed": 1, "groups": 1}
        assert store.review_groups("profile-a", 1) == [stored]
        assert store.decide(stored.id, Decision.DISMISSED, T3)
        assert store.decided_groups(Decision.DISMISSED) == [(stored, T3)]
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
    connection.close()


def review(store: Store) -> list[Posting]:
    return [s.posting for s in store.review_groups("profile-a", 1)]


def decided(store: Store, decision: Decision) -> list[tuple[Posting, datetime]]:
    return [(s.posting, moment) for s, moment in store.decided_groups(decision)]


def decision_rows(store: Store) -> int:
    return store.dump().count('INSERT INTO "decisions"')


def two_passing(store: Store) -> tuple[Posting, Posting]:
    old, new = make_posting(), make_posting(posting_id="1002", title="Data Engineer")
    store.save(old, T1)
    store.save(new, T2)
    checked(store, old, [])
    checked(store, new, [])
    return old, new


def test_review_groups_are_the_passing_groups_newest_first_without_a_limit(store: Store) -> None:
    postings = [make_posting(posting_id=str(n), title=f"Role {n}") for n in range(60)]
    for number, posting in enumerate(postings):
        store.save(posting, T1.replace(minute=number))
        checked(store, posting, [])
    dropped = make_posting(posting_id="900", title="Dropped Role")
    store.save(dropped, T2)
    checked(store, dropped, ["title"])
    assert review(store) == postings[::-1]
    assert store.review_groups("profile-b", 1) == []


def test_decided_posting_leaves_the_review_list_and_enters_its_tab(store: Store) -> None:
    old, new = two_passing(store)
    assert review(store) == [new, old]
    assert store.decide(id_of(store, old), Decision.APPLIED, T3) is True
    assert review(store) == [new]
    assert decided(store, Decision.APPLIED) == [(old, T3)]
    assert decided(store, Decision.DISMISSED) == []


def test_undo_brings_a_posting_back_to_the_review_list(store: Store) -> None:
    old, new = two_passing(store)
    store.decide(id_of(store, old), Decision.DISMISSED, T3)
    store.undo(id_of(store, old))
    assert review(store) == [new, old]
    assert decided(store, Decision.DISMISSED) == []
    assert decision_rows(store) == 0


def test_second_decision_replaces_the_first(store: Store) -> None:
    old, _ = two_passing(store)
    store.decide(id_of(store, old), Decision.APPLIED, T3)
    store.decide(id_of(store, old), Decision.DISMISSED, T4)
    assert decided(store, Decision.APPLIED) == []
    assert decided(store, Decision.DISMISSED) == [(old, T4)]
    assert decision_rows(store) == 1


def test_decision_on_an_unknown_posting_stores_nothing(store: Store) -> None:
    two_passing(store)
    assert store.decide(999, Decision.APPLIED, T3) is False
    assert decision_rows(store) == 0
    store.undo(999)


def test_decided_groups_are_newest_decision_first(store: Store) -> None:
    old, new = two_passing(store)
    store.decide(id_of(store, new), Decision.APPLIED, T3)
    store.decide(id_of(store, old), Decision.APPLIED, T4)
    assert decided(store, Decision.APPLIED) == [(old, T4), (new, T3)]


def test_decision_on_a_copy_holds_when_the_original_passes_later(store: Store) -> None:
    feed, copy = make_posting(location="Madrid"), linkedin_posting("900")
    store.save(feed, T1)
    store.save(copy, T2)
    checked(store, feed, ["place"])
    checked(store, copy, [])
    assert review(store) == [copy]
    store.decide(id_of(store, copy), Decision.APPLIED, T3)
    # The original now passes too, and would stand for the group.
    checked(store, feed, [])
    assert review(store) == []
    assert decided(store, Decision.APPLIED) == [(copy, T3)]


def test_decision_on_the_original_covers_its_copy(store: Store) -> None:
    feed, copy = make_posting(), linkedin_posting("900")
    store.save(feed, T1)
    store.save(copy, T2)
    checked(store, feed, [])
    checked(store, copy, [])
    store.decide(id_of(store, feed), Decision.DISMISSED, T3)
    checked(store, feed, ["place"])
    assert review(store) == []
    assert decided(store, Decision.DISMISSED) == [(feed, T3)]


def test_decision_through_another_member_replaces_the_group_decision(store: Store) -> None:
    feed, copy = make_posting(), linkedin_posting("900")
    store.save(feed, T1)
    store.save(copy, T2)
    store.decide(id_of(store, feed), Decision.APPLIED, T3)
    store.decide(id_of(store, copy), Decision.DISMISSED, T4)
    assert decided(store, Decision.APPLIED) == []
    assert decided(store, Decision.DISMISSED) == [(copy, T4)]
    assert decision_rows(store) == 1


def test_undo_through_another_member_clears_the_group(store: Store) -> None:
    feed, copy = make_posting(), linkedin_posting("900")
    store.save(feed, T1)
    store.save(copy, T2)
    checked(store, feed, [])
    store.decide(id_of(store, feed), Decision.APPLIED, T3)
    store.undo(id_of(store, copy))
    assert decision_rows(store) == 0
    assert review(store) == [feed]


def test_decided_group_stays_in_its_tab_when_it_no_longer_passes(store: Store) -> None:
    old, new = two_passing(store)
    store.decide(id_of(store, old), Decision.APPLIED, T3)
    checked(store, old, ["place"])
    assert decided(store, Decision.APPLIED) == [(old, T3)]
    # Another profile has no results at all, and the decision is still listed.
    assert store.review_groups("profile-b", 1) == []
    checked(store, new, ["level"], profile="profile-b")
    assert decided(store, Decision.APPLIED) == [(old, T3)]


def test_decision_survives_a_change_of_the_posting_text(store: Store) -> None:
    old, _ = two_passing(store)
    store.decide(id_of(store, old), Decision.APPLIED, T3)
    changed = make_posting(description="Build better models.")
    assert store.save(changed, T4) is Outcome.CHANGED
    assert decided(store, Decision.APPLIED) == [(changed, T3)]


def test_groups_that_merge_after_two_decisions_show_the_newest_one(store: Store) -> None:
    feed, other = make_posting(), linkedin_posting("900", title="Data Engineer")
    store.save(feed, T1)
    store.save(other, T1)
    store.decide(id_of(store, feed), Decision.APPLIED, T3)
    store.decide(id_of(store, other), Decision.DISMISSED, T4)
    # The second posting is retitled and becomes a copy of the first.
    merged = linkedin_posting("900")
    store.save(merged, T4)
    assert link_of(store, merged) == id_of(store, feed)
    assert decided(store, Decision.APPLIED) == []
    assert decided(store, Decision.DISMISSED) == [(merged, T4)]


def test_run_summaries_are_newest_first_with_counts_per_run(store: Store) -> None:
    store.log_run("run1", T1, "greenhouse", "Northwind Robotics", fetched=3, new=2)
    store.log_run("run1", T1, "lever", "Bluefjord Labs", fetched=4, new=1)
    store.log_run("run2", T2, "greenhouse", "Northwind Robotics", fetched=3, new=5)
    store.log_run("run2", T2, "lever", "Bluefjord Labs", error="HTTP 404")
    store.log_run("run2", T2, "linkedin", "machine learning engineer", error="timeout")
    assert store.run_summaries(10) == [
        RunSummary(run_id="run2", started_at=T2, sources=3, not_collected=2, new=5),
        RunSummary(run_id="run1", started_at=T1, sources=2, not_collected=0, new=3),
    ]
    assert store.run_summaries(1) == [
        RunSummary(run_id="run2", started_at=T2, sources=3, not_collected=2, new=5)
    ]


def test_run_failures_list_the_sources_that_were_not_collected(store: Store) -> None:
    assert store.run_summaries(10) == []
    store.log_run("run1", T1, "lever", "Bluefjord Labs", error="HTTP 500")
    store.log_run("run2", T2, "greenhouse", "Northwind Robotics", fetched=3, new=5)
    store.log_run("run2", T2, "lever", "Bluefjord Labs", error="HTTP 404")
    assert store.run_failures("run2") == [("lever", "Bluefjord Labs", "HTTP 404")]
    assert store.run_failures("missing") == []


def test_review_list_stays_fast_with_many_postings(store: Store) -> None:
    # Descriptions of a real length, so that reading every posting again costs something.
    text = "Build models for harbour cranes. " * 150
    postings = [
        make_posting(posting_id=str(n), title=f"Role {n}", description=text) for n in range(1500)
    ]
    for posting in postings:
        store.save(posting, T1)
    stored = store.pending_rules("profile-a", 1)
    store.save_rule_results([(item, []) for item in stored], "profile-a", 1, T2)
    store.decide(stored[0].id, Decision.APPLIED, T3)
    started = time.perf_counter()
    assert len(store.review_groups("profile-a", 1)) == 1499
    # Looking up the decided groups once takes a few milliseconds. Once per posting takes seconds.
    assert time.perf_counter() - started < 0.3


def test_version_mark_moves_with_new_and_changed_postings_only(store: Store) -> None:
    empty = store.version_mark()
    store.save(make_posting(), T1)
    first = store.version_mark()
    assert first != empty
    store.save(make_posting(), T2)
    assert store.version_mark() == first
    store.save(make_posting(description="Build better models."), T2)
    changed = store.version_mark()
    assert changed != first
    store.save(make_posting(posting_id="1002", title="Data Engineer"), T2)
    assert store.version_mark() != changed


# The table milestone 3 added, kept here for the same reason as the schemas above.
SCHEMA_V3 = """
CREATE TABLE decisions (
  posting_id INTEGER PRIMARY KEY REFERENCES postings(id),
  decision TEXT NOT NULL CHECK (decision IN ('applied','dismissed')),
  decided_at TEXT NOT NULL
);
"""


def version_3_database(path: Path) -> None:
    version_2_database(path)
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA_V3)
    connection.execute("INSERT INTO decisions VALUES (1, 'applied', ?)", (T3.isoformat(),))
    connection.execute("PRAGMA user_version = 3")
    connection.commit()
    connection.close()


def test_version_3_database_is_upgraded_and_keeps_its_rows(tmp_path: Path) -> None:
    path = tmp_path / "ranker.db"
    version_3_database(path)
    with Store(path) as store:
        assert store.count() == 1
        stored = store.get("greenhouse", "northwindrobotics", "1001")
        assert stored is not None
        assert (stored.posting.title, stored.first_seen) == ("ML Engineer", T1)
        assert store.versions(stored.id) == [("hash-1", T1)]
        assert [row["run_id"] for row in store.runs()] == ["run1"]
        assert store.rule_counts("profile-a", 1) == {"checked": 1, "passed": 1, "groups": 1}
        assert store.decided_groups(Decision.APPLIED) == [(stored, T3)]
        store.save_verdict(stored, make_verdict(), "judge-a", 1, T4)
        assert store.current_verdicts([stored.id], "judge-a", 1) == {stored.id: make_verdict()}
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
    connection.close()


def test_version_1_database_is_upgraded_to_the_newest_version(tmp_path: Path) -> None:
    path = tmp_path / "ranker.db"
    version_1_database(path)
    with Store(path) as store:
        assert store.count() == 1
        assert [row["run_id"] for row in store.runs()] == ["run1"]
        assert store.current_verdicts([1], "judge-a", 1) == {}
    connection = sqlite3.connect(path)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
    connection.close()


def make_verdict(**changes: object) -> Verdict:
    fields: dict[str, object] = {
        "decision": "yes",
        "reasons": ("Asks for Python and SQL, both in the profile.",),
        "matched": ("Python", "SQL"),
        "missing": ("Airflow",),
        "cut": False,
        "model": "model-a",
        "input_tokens": 1500,
        "output_tokens": 120,
        "duration_ms": 1900,
        "cost_usd": 0.0004,
    }
    return Verdict.model_validate(fields | changes)


def waiting(
    store: Store, judge: str = "judge-a", prompt: int = 1, model: str = "model-a"
) -> list[Posting]:
    return [s.posting for s in store.pending_judgement("profile-a", 1, judge, prompt, model)]


def judged(
    store: Store, posting: Posting, verdict: Verdict | None = None, judge: str = "judge-a"
) -> None:
    stored = store.get(posting.source, posting.board, posting.posting_id)
    assert stored is not None
    store.save_verdict(stored, verdict or make_verdict(), judge, 1, T3)


def test_verdict_round_trips_with_every_field(store: Store) -> None:
    old, _ = two_passing(store)
    verdict = make_verdict(decision="no", reasons=("Needs five years.", "Asks for Rust."), cut=True)
    judged(store, old, verdict)
    assert store.current_verdicts([id_of(store, old)], "judge-a", 1) == {id_of(store, old): verdict}


def test_second_verdict_replaces_the_first(store: Store) -> None:
    old, _ = two_passing(store)
    judged(store, old)
    judged(store, old, make_verdict(decision="no"))
    found = store.current_verdicts([id_of(store, old)], "judge-a", 1)
    assert found[id_of(store, old)].decision == "no"
    assert store.dump().count('INSERT INTO "verdicts"') == 1


def test_groups_wait_for_a_verdict_newest_first_until_they_are_judged(store: Store) -> None:
    old, new = two_passing(store)
    assert waiting(store) == [new, old]
    judged(store, new)
    assert waiting(store) == [old]
    judged(store, old)
    assert waiting(store) == []


def test_decided_and_dropped_groups_do_not_wait(store: Store) -> None:
    old, new = two_passing(store)
    dropped = make_posting(posting_id="1003", title="Sales Lead")
    store.save(dropped, T2)
    checked(store, dropped, ["title"])
    store.decide(id_of(store, new), Decision.DISMISSED, T3)
    assert waiting(store) == [old]


def test_verdict_goes_stale_with_the_text_the_judge_profile_the_prompt_and_the_model(
    store: Store,
) -> None:
    old, new = two_passing(store)
    judged(store, old)
    judged(store, new)
    assert waiting(store, judge="judge-b") == [new, old]
    assert waiting(store, prompt=2) == [new, old]
    assert waiting(store, model="model-b") == [new, old]
    changed = old.model_copy(update={"description": "Build other models."})
    store.save(changed, T3)
    checked(store, changed, [])
    assert waiting(store) == [changed]


def test_a_change_of_the_rule_profile_alone_leaves_a_verdict_current(store: Store) -> None:
    old, _ = two_passing(store)
    judged(store, old)
    checked(store, old, [], profile="profile-b")
    pending = store.pending_judgement("profile-b", 1, "judge-a", 1, "model-a")
    assert pending == []


def test_group_is_judged_again_when_another_posting_comes_to_stand_for_it(store: Store) -> None:
    feed, copy = make_posting(location="Madrid"), linkedin_posting("900")
    store.save(feed, T1)
    store.save(copy, T2)
    checked(store, feed, ["place"])
    checked(store, copy, [])
    judged(store, copy)
    assert waiting(store) == []
    # The original now passes too and stands for the group.
    checked(store, feed, [])
    assert waiting(store) == [feed]
    assert store.current_verdicts([id_of(store, feed)], "judge-a", 1) == {}


def test_current_verdicts_take_any_model_and_hide_a_stale_one(store: Store) -> None:
    old, new = two_passing(store)
    judged(store, old, make_verdict(model="model-b"))
    judged(store, new, judge="judge-old")
    ids = [id_of(store, old), id_of(store, new)]
    assert set(store.current_verdicts(ids, "judge-a", 1)) == {id_of(store, old)}
    assert store.current_verdicts(ids, "judge-a", 2) == {}
    assert store.current_verdicts([], "judge-a", 1) == {}
