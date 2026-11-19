"""Text helpers: HTML to plain text, and normalised forms for matching."""

import re
import unicodedata
from collections.abc import Sequence
from html.parser import HTMLParser

# Tags that start or end a line of text.
_BLOCKS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "footer",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "ol", "p", "pre", "section",
        "table", "td", "th", "tr", "ul",
    }
)  # fmt: skip
# Tags whose content is code and never text for a reader.
_HIDDEN = frozenset({"script", "style"})
_NOT_WORD = re.compile(r"[\W_]+")
# A dot that starts a word and is followed by a letter, as in .NET.
_LEADING_DOT = re.compile(r"(?<!\w)\.(?=[^\W\d_])")
_LEGAL_FORMS = frozenset({"gmbh", "ag", "se", "inc", "ltd", "llc"})


class _TextCollector(HTMLParser):
    """Keeps the text between tags. Character references are unescaped once by the parser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HIDDEN:
            self._hidden += 1
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN:
            self._hidden = max(0, self._hidden - 1)
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    """Return the readable text of an HTML fragment, one line per block."""
    collector = _TextCollector()
    collector.feed(raw)
    collector.close()
    lines = (" ".join(line.split()) for line in "".join(collector.parts).splitlines())
    return "\n".join(line for line in lines if line)


def normalise(value: str) -> str:
    """Case, accents and punctuation removed, single spaces."""
    # Decomposed after case folding, so one name gives one form however it was typed.
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    # These marks tell titles such as C++, C# and .NET apart, so they are kept as words.
    text = _LEADING_DOT.sub(" dot ", text)
    text = text.replace("+", " plus ").replace("#", " sharp ")
    return _NOT_WORD.sub(" ", text).strip()


def normalise_company(name: str) -> str:
    """Normalised company name without a trailing legal form such as GmbH."""
    words = normalise(name).split()
    if len(words) > 1 and words[-1] in _LEGAL_FORMS:
        words = words[:-1]
    return " ".join(words)


def contains_phrase(words: Sequence[str], phrase: str) -> bool:
    """Whether the normalised words of `phrase` follow each other in `words`.

    Whole words only, so `intern` is not found in `internal`. An empty phrase is never found.
    """
    wanted = normalise(phrase).split()
    if not wanted:
        return False
    span = len(wanted)
    return any(list(words[i : i + span]) == wanted for i in range(len(words) - span + 1))
