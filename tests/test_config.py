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


@pytest.mark.parametrize("token", ["123", "0123"])
def test_unquoted_numeric_token_is_rejected(tmp_path: Path, token: str) -> None:
    path = write(
        tmp_path / "c.yaml",
        f"companies:\n  - name: Acme Test\n    feed: lever\n    token: {token}\n",
    )
    with pytest.raises(ConfigError) as error:
        load_companies(path)
    assert "Acme Test" in str(error.value)
    assert "quote" in str(error.value)


def test_quoted_numeric_token_is_kept_as_written(tmp_path: Path) -> None:
    path = write(
        tmp_path / "c.yaml",
        'companies:\n  - name: Acme Test\n    feed: lever\n    token: "0123"\n',
    )
    assert load_companies(path)[0].token == "0123"


def test_mistyped_top_level_key_is_rejected(tmp_path: Path) -> None:
    path = write(
        tmp_path / "c.yaml", "company:\n  - name: Acme Test\n    feed: lever\n    token: acme\n"
    )
    with pytest.raises(ConfigError) as error:
        load_companies(path)
    assert "c.yaml" in str(error.value)
    assert "'companies:'" in str(error.value)


def test_extra_top_level_key_is_rejected(tmp_path: Path) -> None:
    path = write(
        tmp_path / "c.yaml",
        "companies:\n  - name: Acme Test\n    feed: lever\n    token: acme\nsearches: []\n",
    )
    with pytest.raises(ConfigError) as error:
        load_companies(path)
    assert "c.yaml" in str(error.value)
    assert "'companies:'" in str(error.value)


def test_mistyped_top_level_key_is_rejected_for_searches(tmp_path: Path) -> None:
    path = write(tmp_path / "s.yaml", "search:\n  - keywords: x\n    location: Lisbon\n")
    with pytest.raises(ConfigError) as error:
        load_searches(path)
    assert "'searches:'" in str(error.value)


def test_expected_key_without_entries_gives_empty_list(tmp_path: Path) -> None:
    assert load_companies(write(tmp_path / "c.yaml", "companies:\n")) == []
    assert load_searches(write(tmp_path / "s.yaml", "searches:\n")) == []
    assert load_companies(write(tmp_path / "e.yaml", "companies: []\n")) == []


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


def test_empty_token_line_does_not_hide_a_later_one(tmp_path: Path) -> None:
    env_file = write(tmp_path / ".env", "APIFY_TOKEN=\nAPIFY_TOKEN=abc123\n")
    assert read_token({}, env_file) == "abc123"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("APIFY_TOKEN=abc123 # note", "abc123"),
        ("APIFY_TOKEN=abc123\t# note", "abc123"),
        ('APIFY_TOKEN="abc123" # note', "abc123"),
        ("export APIFY_TOKEN='abc123' # note", "abc123"),
        ('APIFY_TOKEN="abc #123"', "abc #123"),
        ("APIFY_TOKEN=abc#123", "abc#123"),
    ],
)
def test_inline_comment_is_not_part_of_the_token(tmp_path: Path, line: str, expected: str) -> None:
    assert read_token({}, write(tmp_path / ".env", line + "\n")) == expected


def test_token_line_with_only_a_comment_is_absent(tmp_path: Path) -> None:
    assert read_token({}, write(tmp_path / ".env", "APIFY_TOKEN= # put it here\n")) is None


def test_env_file_with_byte_order_mark_is_read(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"\xef\xbb\xbfAPIFY_TOKEN=abc123\n")
    assert read_token({}, env_file) == "abc123"


def test_empty_token_is_absent(tmp_path: Path) -> None:
    env_file = write(tmp_path / ".env", "APIFY_TOKEN=\n")
    assert read_token({"APIFY_TOKEN": ""}, env_file) is None
    assert read_token({}, tmp_path / "missing.env") is None


def test_folder_as_config_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as error:
        load_companies(tmp_path)
    assert str(tmp_path) in str(error.value)


def test_config_file_in_another_encoding_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_bytes(b"companies:\n  - name: Caf\xe9\n    feed: lever\n    token: cafe\n")
    with pytest.raises(ConfigError) as error:
        load_companies(path)
    assert "c.yaml" in str(error.value)


def test_config_file_is_read_as_utf8(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_bytes("companies:\n  - name: Café Nord\n    feed: lever\n    token: cafe\n".encode())
    assert load_companies(path)[0].name == "Café Nord"


def test_env_file_in_another_encoding_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_bytes(b"# caf\xe9\nAPIFY_TOKEN=abc\n")
    with pytest.raises(ConfigError) as error:
        read_token({}, path)
    assert ".env" in str(error.value)


@pytest.mark.parametrize(
    "entry",
    [
        'name: "  "\n    feed: lever\n    token: acme',
        'name: Acme Test\n    feed: lever\n    token: "  "',
        'name: Acme Test\n    feed: lever\n    token: "a b"',
        'name: Acme Test\n    feed: lever\n    token: "a/../b"',
    ],
)
def test_blank_name_and_malformed_token_are_rejected(tmp_path: Path, entry: str) -> None:
    path = write(tmp_path / "c.yaml", f"companies:\n  - {entry}\n")
    with pytest.raises(ConfigError):
        load_companies(path)


def test_padded_values_are_trimmed(tmp_path: Path) -> None:
    path = write(
        tmp_path / "c.yaml",
        'companies:\n  - name: " Acme Test "\n    feed: lever\n    token: " acme "\n',
    )
    company = load_companies(path)[0]
    assert (company.name, company.token) == ("Acme Test", "acme")


def test_same_board_in_another_letter_case_is_a_duplicate(tmp_path: Path) -> None:
    path = write(
        tmp_path / "c.yaml",
        "companies:\n"
        "  - name: Acme Test\n    feed: lever\n    token: acme\n"
        "  - name: Acme Again\n    feed: lever\n    token: ACME\n",
    )
    with pytest.raises(ConfigError, match="duplicate"):
        load_companies(path)


def test_search_limit_must_be_a_number(tmp_path: Path) -> None:
    path = write(
        tmp_path / "s.yaml",
        "searches:\n  - keywords: data engineer\n    location: Lisbon\n    limit: true\n",
    )
    with pytest.raises(ConfigError):
        load_searches(path)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('APIFY_TOKEN="a\\"b"', 'a"b'),
        ('APIFY_TOKEN="a\\\\b" # note', "a\\b"),
        ("APIFY_TOKEN='a\\b'", "a\\b"),
    ],
)
def test_escapes_in_a_quoted_token(tmp_path: Path, line: str, expected: str) -> None:
    assert read_token({}, write(tmp_path / ".env", line + "\n")) == expected
