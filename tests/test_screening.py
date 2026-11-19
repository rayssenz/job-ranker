from datetime import UTC, datetime
from pathlib import Path

from jobranker.models import Posting
from jobranker.profile import Profile
from jobranker.rules import RULES_VERSION
from jobranker.screening import apply_rules
from jobranker.store import Store

T1 = datetime(2026, 11, 19, 8, 0, tzinfo=UTC)
PROFILE = Profile(places=["Lisbon"])


def posting(posting_id: str, location: str) -> Posting:
    return Posting(
        source="greenhouse",
        board="northwindrobotics",
        posting_id=posting_id,
        company="Northwind Robotics",
        title=f"Role {posting_id}",
        location=location,
    )


def test_apply_rules_checks_every_pending_posting_and_saves_the_results(tmp_path: Path) -> None:
    with Store(tmp_path / "ranker.db") as store:
        store.save(posting("1", "Lisbon"), T1)
        store.save(posting("2", "Madrid"), T1)
        assert apply_rules(store, PROFILE, T1) == 2
        assert store.pending_rules(PROFILE.digest, RULES_VERSION) == []
        assert store.rule_counts(PROFILE.digest, RULES_VERSION) == {
            "checked": 2,
            "passed": 1,
            "groups": 1,
            "place": 1,
        }


def test_apply_rules_checks_nothing_twice(tmp_path: Path) -> None:
    with Store(tmp_path / "ranker.db") as store:
        store.save(posting("1", "Lisbon"), T1)
        assert apply_rules(store, PROFILE, T1) == 1
        assert apply_rules(store, PROFILE, T1) == 0
        store.save(posting("2", "Porto"), T1)
        assert apply_rules(store, PROFILE, T1) == 1


def test_apply_rules_on_an_empty_store_checks_nothing(tmp_path: Path) -> None:
    with Store(tmp_path / "ranker.db") as store:
        assert apply_rules(store, PROFILE, T1) == 0
