from pathlib import Path

import pytest

from jobranker.profile import Profile, ProfileError, load_profile

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "config" / "profile.example.yaml"


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_example_profile_loads() -> None:
    profile = load_profile(EXAMPLE)
    assert profile.places == ["Lisbon", "Porto"]
    assert profile.remote.accept is True
    assert profile.remote.places == ["Portugal", "Europe"]
    assert "working student" in profile.levels.accept
    assert "senior" in profile.levels.reject
    assert profile.languages == ["English", "Portuguese"]


def test_only_places_are_required(tmp_path: Path) -> None:
    profile = load_profile(write(tmp_path / "profile.yaml", "places: [Lisbon]\n"))
    assert profile.remote.accept is True
    assert profile.remote.places == []
    assert profile.levels.accept == [] and profile.levels.reject == []
    assert profile.title_words == [] and profile.avoid == []


def test_missing_profile_points_to_the_example(tmp_path: Path) -> None:
    with pytest.raises(ProfileError) as error:
        load_profile(tmp_path / "profile.yaml")
    assert "config/profile.example.yaml" in str(error.value)


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ("places: [Lisbon]\nsalary: 99999\n", "salary"),
        ("places: Lisbon-secret\n", "places"),
        ("places: [Lisbon]\nremote:\n  accept: perhaps-secret\n", "remote.accept"),
        ("places: [Lisbon]\nlevels:\n  accept: [junior, '  ']\n", "levels.accept"),
        ("avoid: [gambling]\n", "places"),
    ],
)
def test_wrong_profile_names_the_field_and_no_value(tmp_path: Path, text: str, field: str) -> None:
    path = write(tmp_path / "profile.yaml", text)
    with pytest.raises(ProfileError) as error:
        load_profile(path)
    message = str(error.value)
    assert "profile.yaml" in message
    assert field in message
    assert "secret" not in message and "99999" not in message


@pytest.mark.parametrize("text", ["places: [Lisbon\n", "- just\n- a list\n", ""])
def test_profile_that_is_not_a_mapping_is_rejected(tmp_path: Path, text: str) -> None:
    with pytest.raises(ProfileError):
        load_profile(write(tmp_path / "profile.yaml", text))


def test_unreadable_profile_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_bytes(b"places: [Caf\xe9]\n")
    with pytest.raises(ProfileError):
        load_profile(path)
    with pytest.raises(ProfileError):
        load_profile(tmp_path)


def test_digest_follows_the_rule_fields_only() -> None:
    base = Profile.model_validate({"places": ["Lisbon"], "notes": "first"})
    same_rules = Profile.model_validate(
        {"places": ["Lisbon"], "notes": "second", "skills": ["SQL"]}
    )
    other_rules = Profile.model_validate({"places": ["Lisbon"], "title_words": ["engineer"]})
    assert base.digest == same_rules.digest
    assert base.digest != other_rules.digest
    assert len(base.digest) == 64


def test_impossible_date_in_the_profile_is_rejected_without_its_digits(tmp_path: Path) -> None:
    path = write(tmp_path / "profile.yaml", "places: [2026-02-30]\n")
    with pytest.raises(ProfileError) as error:
        load_profile(path)
    assert "profile.yaml" in str(error.value)
    assert "2026" not in str(error.value)
