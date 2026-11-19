import pytest

from jobranker.text import html_to_text, normalise, normalise_company


def test_html_to_text_strips_tags_and_unescapes_once() -> None:
    raw = "<div><p>Build &amp; run</p><ul><li>Python</li></ul></div>"
    assert html_to_text(raw) == "Build & run\nPython"


def test_html_to_text_keeps_escaped_angle_brackets_as_text() -> None:
    raw = "<li>Generics such as List&lt;String&gt; and a &lt; b</li>"
    assert html_to_text(raw) == "Generics such as List<String> and a < b"


def test_html_to_text_does_not_unescape_twice() -> None:
    assert html_to_text("<p>Write &amp;lt; for a less-than sign</p>") == (
        "Write &lt; for a less-than sign"
    )


def test_html_to_text_handles_plain_html() -> None:
    assert html_to_text("<p>First</p><p>Second<br>line</p>") == "First\nSecond\nline"


def test_html_to_text_of_empty_text_is_empty() -> None:
    assert html_to_text("") == ""


def test_normalise_lowers_and_drops_punctuation() -> None:
    assert normalise("  ML Engineer (m/f/d) ") == "ml engineer m f d"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("C++ Developer", "c plus plus developer"),
        ("C# Developer", "c sharp developer"),
        ("C Developer", "c developer"),
        (".NET Developer", "dot net developer"),
        ("NET Developer", "net developer"),
        ("Senior .NET Developer", "senior dot net developer"),
        ("Node.js Developer", "node js developer"),
        ("Engineer. Remote.", "engineer remote"),
        ("???", ""),
    ],
)
def test_normalise_keeps_plus_sharp_and_leading_dot_as_words(value: str, expected: str) -> None:
    assert normalise(value) == expected


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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<table><tr><td>a</td><td>b</td></tr></table>", "a\nb"),
        ("<dl><dt>Term</dt><dd>Def</dd></dl>", "Term\nDef"),
        ("Intro<p>Body</p>", "Intro\nBody"),
        ("<p>a</p><script>var x=1;</script><style>p{}</style><p>b</p>", "a\nb"),
        ('<a href="x>y">t</a>', "t"),
        ("<p>kept<!-- hidden --></p>", "kept"),
    ],
)
def test_html_to_text_separates_blocks_and_drops_code(raw: str, expected: str) -> None:
    assert html_to_text(raw) == expected


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Café Nord", "Café Nord"),
        ("Café Nord", "CAFE NORD"),
        ("Straße", "STRASSE"),
        ("İstanbul Labs", "istanbul labs"),
        ("ＡＣＭＥ", "acme"),
    ],
)
def test_normalise_ignores_case_accents_and_unicode_form(first: str, second: str) -> None:
    assert normalise(first) == normalise(second) != ""
