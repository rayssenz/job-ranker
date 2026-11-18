import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def test_no_private_files_are_tracked() -> None:
    private = [
        f
        for f in tracked_files()
        if f in ("profile.yaml", ".env") or f.startswith("data/") or f.endswith(".db")
    ]
    assert private == []


def test_gitignore_lists_private_paths() -> None:
    lines = (ROOT / ".gitignore").read_text().splitlines()
    for path in ("profile.yaml", "data/", ".env", "*.db"):
        assert path in lines
