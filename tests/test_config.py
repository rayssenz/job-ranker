from pathlib import Path

import pytest

from jobranker.config import ConfigError, load_companies, load_searches, read_token

ROOT = Path(__file__).resolve().parents[1]


def write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_loads_example_companies() -> None:
    companies = load_companies(ROOT / "config" / "companies.example.yaml")
    assert sorted(c.feed for c in companies) == ["ashby", "greenhouse", "lever"]
    lever = next(c for c in companies if c.feed == "lever")
    assert lever.region == "eu"
    assert all(c.region == "global" for c in companies if c.feed != "lever")


def test_loads_example_searches() -> None:
    searches = load_searches(ROOT / "config" / "searches.example.yaml")
    assert len(searches) == 2
    assert searches[0].posted_within == "day"
    assert searches[0].limit == 50
    assert searches[1].posted_within == "week"
    assert searches[1].limit == 25


def test_missing_file_gives_empty_list(tmp_path: Path) -> None:
    assert load_companies(tmp_path / "none.yaml") == []
    assert load_searches(tmp_path / "none.yaml") == []


def test_empty_file_gives_empty_list(tmp_path: Path) -> None:
    assert load_companies(write(tmp_path / "c.yaml", "")) == []


def test_numeric_token_is_kept_as_text(tmp_path: Path) -> None:
    path = write(
        tmp_path / "c.yaml", "companies:\n  - name: Acme Test\n    feed: lever\n    token: 123\n"
    )
    assert load_companies(path)[0].token == "123"


def test_unknown_feed_is_rejected_and_names_the_entry(tmp_path: Path) -> None:
    path = write(
        tmp_path / "c.yaml", "companies:\n  - name: Acme Test\n    feed: workday\n    token: acme\n"
    )
    with pytest.raises(ConfigError) as error:
        load_companies(path)
    assert "Acme Test" in str(error.value)
    assert "c.yaml" in str(error.value)


def test_missing_field_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path / "c.yaml", "companies:\n  - name: Acme Test\n    feed: lever\n")
    with pytest.raises(ConfigError) as error:
        load_companies(path)
    assert "Acme Test" in str(error.value)
    assert "token" in str(error.value)


def test_region_only_allowed_for_lever(tmp_path: Path) -> None:
    path = write(
        tmp_path / "c.yaml",
        "companies:\n  - name: Acme Test\n    feed: ashby\n    token: acme\n    region: eu\n",
    )
    with pytest.raises(ConfigError):
        load_companies(path)


def test_duplicate_company_is_rejected(tmp_path: Path) -> None:
    entry = "  - name: Acme Test\n    feed: lever\n    token: acme\n"
    path = write(tmp_path / "c.yaml", "companies:\n" + entry + entry)
    with pytest.raises(ConfigError) as error:
        load_companies(path)
    assert "duplicate" in str(error.value)


def test_duplicate_search_is_rejected(tmp_path: Path) -> None:
    entry = "  - keywords: data engineer\n    location: Lisbon\n"
    path = write(tmp_path / "s.yaml", "searches:\n" + entry + entry)
    with pytest.raises(ConfigError) as error:
        load_searches(path)
    assert "data engineer" in str(error.value)


def test_search_limit_out_of_range_is_rejected(tmp_path: Path) -> None:
    path = write(
        tmp_path / "s.yaml", "searches:\n  - keywords: x\n    location: Lisbon\n    limit: 0\n"
    )
    with pytest.raises(ConfigError):
        load_searches(path)


@pytest.mark.parametrize("text", ["companies: 5\n", "- a\n- b\n", "companies:\n  - just text\n"])
def test_wrong_shape_is_rejected(tmp_path: Path, text: str) -> None:
    with pytest.raises(ConfigError):
        load_companies(write(tmp_path / "c.yaml", text))


def test_invalid_yaml_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_companies(write(tmp_path / "c.yaml", "companies: [unclosed\n"))


def test_token_from_environment_wins_over_file(tmp_path: Path) -> None:
    env_file = write(tmp_path / ".env", "APIFY_TOKEN=from-file\n")
    assert read_token({"APIFY_TOKEN": "from-env"}, env_file) == "from-env"


def test_token_from_env_file(tmp_path: Path) -> None:
    env_file = write(tmp_path / ".env", '# comment\nOTHER=1\nAPIFY_TOKEN="from-file"\n')
    assert read_token({}, env_file) == "from-file"


def test_empty_token_is_absent(tmp_path: Path) -> None:
    env_file = write(tmp_path / ".env", "APIFY_TOKEN=\n")
    assert read_token({"APIFY_TOKEN": ""}, env_file) is None
    assert read_token({}, tmp_path / "missing.env") is None
