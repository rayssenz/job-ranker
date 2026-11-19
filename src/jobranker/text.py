"""Text helpers: HTML to plain text, and normalised forms for matching."""

import html
import re

_BLOCK_END = re.compile(r"<br\s*/?>|</(?:p|div|li|ul|ol|h[1-6]|tr|section)\s*>", re.IGNORECASE)
_TAG = re.compile(r"<!--.*?-->|</?[a-zA-Z][^>]*>", re.DOTALL)
_NOT_WORD = re.compile(r"[\W_]+")
_LEGAL_FORMS = frozenset({"gmbh", "ag", "se", "inc", "ltd", "llc"})
_MAX_UNESCAPE_PASSES = 3


def html_to_text(raw: str) -> str:
    """Return the readable text of an HTML fragment, one line per block."""
    text = raw
    for _ in range(_MAX_UNESCAPE_PASSES):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    text = _BLOCK_END.sub("\n", text)
    text = _TAG.sub("", text)
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def normalise(value: str) -> str:
    """Lower case, punctuation removed, single spaces."""
    return _NOT_WORD.sub(" ", value.lower()).strip()


def normalise_company(name: str) -> str:
    """Normalised company name without a trailing legal form such as GmbH."""
    words = normalise(name).split()
    if len(words) > 1 and words[-1] in _LEGAL_FORMS:
        words = words[:-1]
    return " ".join(words)
