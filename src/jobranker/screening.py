"""The rule run that the `rules` command and the dashboard share."""

from datetime import datetime

from jobranker.profile import Profile
from jobranker.rules import RULES_VERSION, check
from jobranker.store import Store


def apply_rules(store: Store, profile: Profile, now: datetime) -> int:
    """Check every posting without a current result, save the results, return how many."""
    pending = store.pending_rules(profile.digest, RULES_VERSION)
    results = ((stored, check(stored.posting, profile)) for stored in pending)
    store.save_rule_results(results, profile.digest, RULES_VERSION, now)
    return len(pending)
