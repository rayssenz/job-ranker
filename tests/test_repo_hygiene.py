import subprocess
from fnmatch import fnmatch
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PRIVATE_PATHS = [
    "profile.yaml",
    "config/profile.yaml",
    "config/companies.yaml",
    ".env",
    ".env.local",
    "nested/.env",
    "data/ranker.db",
    "evals/data/full-recording.jsonl",
    "notes.db",
    "data/é.db",
    "client_secret_123.json",
    "keys/client_secret_123.json",
]

PUBLIC_PATHS = [
    "config/profile.example.yaml",
    "config/companies.example.yaml",
    ".env.example",
    "evals/cases.jsonl",
    "src/jobranker/cli.py",
    "docs/database.md",
]


def is_private(path: str) -> bool:
    *folders, name = path.split("/")
    if "data" in folders or name.endswith(".db"):
        return True
    if name in ("profile.yaml", "companies.yaml", ".env"):
        return True
    if name.startswith(".env.") and name != ".env.example":
        return True
    return fnmatch(name, "client_secret*.json")


def tracked_files(root: Path = ROOT) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True
    )
    return [path for path in out.stdout.split("\0") if path]


def is_ignored(path: str) -> bool:
    result = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT, check=False)
    return result.returncode == 0


@pytest.mark.parametrize("path", PRIVATE_PATHS)
def test_private_path_is_recognised(path: str) -> None:
    assert is_private(path)


@pytest.mark.parametrize("path", PUBLIC_PATHS)
def test_public_path_is_not_flagged(path: str) -> None:
    assert not is_private(path)


def test_tracked_files_keep_non_ascii_names(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "é.db").write_text("")
    subprocess.run(["git", "add", "é.db"], cwd=tmp_path, check=True)
    assert tracked_files(tmp_path) == ["é.db"]


def test_no_private_files_are_tracked() -> None:
    assert [f for f in tracked_files() if is_private(f)] == []


@pytest.mark.parametrize("path", PRIVATE_PATHS)
def test_private_path_is_ignored_by_git(path: str) -> None:
    assert is_ignored(path)


@pytest.mark.parametrize("path", PUBLIC_PATHS)
def test_public_path_is_not_ignored_by_git(path: str) -> None:
    assert not is_ignored(path)
