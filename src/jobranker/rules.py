"""Fixed rules that drop a posting when it certainly cannot fit the profile.

Each rule is a pure function of one posting and the profile. A rule drops a posting only
when the mismatch is certain: what is unknown or unsaid passes and is left to the judge.
Every word list comes from the profile. Only the language names are fixed here.
"""

from collections.abc import Sequence
from enum import StrEnum

from jobranker.models import Posting, Remote
from jobranker.profile import Profile
from jobranker.text import contains_phrase, normalise

# Raised when a rule changes what it drops, so stored results are computed again.
RULES_VERSION = 1


class Reason(StrEnum):
    """Why a posting was dropped. The order is the order in which the rules are reported."""

    PLACE = "place"
    LEVEL = "level"
    LANGUAGE = "language"
    AVOID = "avoid"
    TITLE = "title"


# One key per language, with its English and German names.
_LANGUAGE_NAMES = {
    "arabic": ("Arabic", "Arabisch"),
    "chinese": ("Chinese", "Mandarin", "Chinesisch"),
    "czech": ("Czech", "Tschechisch"),
    "danish": ("Danish", "Dänisch"),
    "dutch": ("Dutch", "Niederländisch", "Holländisch"),
    "english": ("English", "Englisch"),
    "finnish": ("Finnish", "Finnisch"),
    "french": ("French", "Französisch"),
    "german": ("German", "Deutsch"),
    "greek": ("Greek", "Griechisch"),
    "hebrew": ("Hebrew", "Hebräisch"),
    "hindi": ("Hindi",),
    "hungarian": ("Hungarian", "Ungarisch"),
    "italian": ("Italian", "Italienisch"),
    "japanese": ("Japanese", "Japanisch"),
    "korean": ("Korean", "Koreanisch"),
    "norwegian": ("Norwegian", "Norwegisch"),
    "polish": ("Polish", "Polnisch"),
    "portuguese": ("Portuguese", "Portugiesisch"),
    "romanian": ("Romanian", "Rumänisch"),
    "russian": ("Russian", "Russisch"),
    "spanish": ("Spanish", "Spanisch"),
    "swedish": ("Swedish", "Schwedisch"),
    "turkish": ("Turkish", "Türkisch"),
    "ukrainian": ("Ukrainian", "Ukrainisch"),
}
_LANGUAGE_KEY = {normalise(name): key for key, names in _LANGUAGE_NAMES.items() for name in names}
_SPEAKER_WORDS = frozenset({"speaking", "speaker", "speakers", "sprechend", "sprechende"})
# The German joined form, as in `deutschsprachig` and `deutschsprachiger`.
_JOINED_FORM = "sprachig"


def _holds_any(words: Sequence[str], phrases: Sequence[str]) -> bool:
    return any(contains_phrase(words, phrase) for phrase in phrases)


def _place(posting: Posting, profile: Profile, location: Sequence[str]) -> bool:
    # An empty location says nothing, so it is not a mismatch.
    if not location or _holds_any(location, profile.places):
        return True
    if not profile.remote.accept or posting.remote is not Remote.YES:
        return False
    return not profile.remote.places or _holds_any(location, profile.remote.places)


def _level(profile: Profile, title: Sequence[str]) -> bool:
    return not _holds_any(title, profile.levels.reject) or _holds_any(title, profile.levels.accept)


def _asked_languages(title: Sequence[str]) -> set[str]:
    """The languages a title asks a speaker of, as in `Dutch Speaking`."""
    asked: set[str] = set()
    for index, word in enumerate(title):
        following = title[index + 1] if index + 1 < len(title) else ""
        if word in _LANGUAGE_KEY and following in _SPEAKER_WORDS:
            asked.add(_LANGUAGE_KEY[word])
        name, joined, _ = word.partition(_JOINED_FORM)
        if joined and name in _LANGUAGE_KEY:
            asked.add(_LANGUAGE_KEY[name])
    return asked


def _language(profile: Profile, title: Sequence[str]) -> bool:
    known = {_LANGUAGE_KEY.get(normalise(name), normalise(name)) for name in profile.languages}
    return _asked_languages(title) <= known


def check(posting: Posting, profile: Profile) -> tuple[Reason, ...]:
    """The reasons to drop `posting`, in a fixed order. An empty result means it passed."""
    title = normalise(posting.title).split()
    company = normalise(posting.company).split()
    location = normalise(posting.location).split()
    passed = {
        Reason.PLACE: _place(posting, profile, location),
        Reason.LEVEL: _level(profile, title),
        Reason.LANGUAGE: _language(profile, title),
        Reason.AVOID: not (_holds_any(title, profile.avoid) or _holds_any(company, profile.avoid)),
        Reason.TITLE: not profile.title_words or _holds_any(title, profile.title_words),
    }
    return tuple(reason for reason in Reason if not passed[reason])
