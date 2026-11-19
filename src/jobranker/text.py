"""Text helpers: HTML to plain text, and normalised forms for matching."""

import html
import re

_BLOCK_END = re.compile(r"<br\s*/?>|</(?:p|div|li|ul|ol|h[1-6]|tr|section)\s*>", re.IGNORECASE)
_TAG = re.compile(r"<!--.*?-->|</?[a-zA-Z][^>]*>", re.DOTALL)
_NOT_WORD = re.compile(r"[\W_]+")
# A dot that starts a word and is followed by a letter, as in .NET.
_LEADING_DOT = re.compile(r"(?<!\w)\.(?=[^\W\d_])")
_LEGAL_FORMS = frozenset({"gmbh", "ag", "se", "inc", "ltd", "llc"})


def html_to_text(raw: str) -> str:
    """Return the readable text of an HTML fragment, one line per block."""
    text = _BLOCK_END.sub("\n", raw)
    text = _TAG.sub("", text)
    # Unescaped once and after the tags are gone, so text such as List&lt;String&gt; is kept.
    text = html.unescape(text)
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def normalise(value: str) -> str:
    """Lower case, punctuation removed, single spaces."""
    # These marks tell titles such as C++, C# and .NET apart, so they are kept as words.
    text = _LEADING_DOT.sub(" dot ", value.lower())
    text = text.replace("+", " plus ").replace("#", " sharp ")
    return _NOT_WORD.sub(" ", text).strip()


def normalise_company(name: str) -> str:
    """Normalised company name without a trailing legal form such as GmbH."""
    words = normalise(name).split()
    if len(words) > 1 and words[-1] in _LEGAL_FORMS:
        words = words[:-1]
    return " ".join(words)
