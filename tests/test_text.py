import pytest

from jobranker.text import html_to_text, normalise, normalise_company


def test_html_to_text_unescapes_and_strips_tags() -> None:
    raw = (
        "&lt;div&gt;&lt;p&gt;Build &amp;amp; run&lt;/p&gt;"
        "&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;&lt;/ul&gt;&lt;/div&gt;"
    )
    assert html_to_text(raw) == "Build & run\nPython"


def test_html_to_text_handles_plain_html() -> None:
    assert html_to_text("<p>First</p><p>Second<br>line</p>") == "First\nSecond\nline"


def test_html_to_text_of_empty_text_is_empty() -> None:
    assert html_to_text("") == ""


def test_normalise_lowers_and_drops_punctuation() -> None:
    assert normalise("  ML Engineer (m/f/d) ") == "ml engineer m f d"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Northwind Robotics GmbH", "northwind robotics"),
        ("northwind robotics", "northwind robotics"),
        ("Northwind-Robotics, Inc.", "northwind robotics"),
        ("AG Insurance", "ag insurance"),
        ("GmbH", "gmbh"),
    ],
)
def test_normalise_company(name: str, expected: str) -> None:
    assert normalise_company(name) == expected
