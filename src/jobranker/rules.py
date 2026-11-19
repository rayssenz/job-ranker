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
# Between two language names: a choice of languages, or a need for both.
_CHOICE_WORDS = frozenset({"or", "oder"})
_BOTH_WORDS = frozenset({"and", "und"})
# Before a request: the language is not needed, as in `non-German speaking`.
_NEGATIONS = frozenset({"non", "not", "no", "kein", "keine", "nicht"})
_REMOTE_WORD = "remote"


def _holds_any(words: Sequence[str], phrases: Sequence[str]) -> bool:
    return any(contains_phrase(words, phrase) for phrase in phrases)


def _place(posting: Posting, profile: Profile, location: Sequence[str]) -> bool:
    # An empty location says nothing, so it is not a mismatch.
    if not location or _holds_any(location, profile.places):
        return True
    # The location can say what the remote field of a feed leaves out.
    remote = posting.remote is Remote.YES or _REMOTE_WORD in location
    if not profile.remote.accept or not remote:
        return False
    # A location that names no place, such as a bare `Remote`, is not a certain mismatch.
    named = [word for word in location if word != _REMOTE_WORD]
    return not profile.remote.places or not named or _holds_any(location, profile.remote.places)


def _level(profile: Profile, title: Sequence[str]) -> bool:
    return not _holds_any(title, profile.levels.reject) or _holds_any(title, profile.levels.accept)


def _language_of(word: str) -> tuple[str | None, bool]:
    """The language a word names, and whether the word also says a speaker is wanted."""
    if word in _LANGUAGE_KEY:
        return _LANGUAGE_KEY[word], False
    name, joined, _ = word.partition(_JOINED_FORM)
    if joined and name in _LANGUAGE_KEY:
        return _LANGUAGE_KEY[name], True
    return None, False


def _requests(title: Sequence[str]) -> list[tuple[list[str], bool]]:
    """Each request for a speaker in a title: the languages, and whether all are needed.

    A request is a run of language names, speaker words and joining words, as in
    `Dutch or English speaking`, `English speaker / German speaker` and
    `englisch- oder deutschsprachig`. Several languages are a choice unless `and` joins them.
    A run without a speaker word is no request, and neither is one after a negation.
    """
    found: list[tuple[list[str], bool]] = []
    languages: list[str] = []
    wanted = every = negated = False
    previous = ""
    for word in [*title, ""]:
        language, joined = _language_of(word)
        if language is not None or word in _SPEAKER_WORDS:
            if not languages and not wanted:
                negated = previous in _NEGATIONS
            wanted = wanted or joined or word in _SPEAKER_WORDS
            if language is not None:
                languages.append(language)
        elif languages and word in _BOTH_WORDS:
            every = True
        elif not (languages and word in _CHOICE_WORDS):
            if languages and wanted and not negated:
                found.append((languages, every))
            languages, wanted, every, negated = [], False, False, False
        previous = word
    return found


def _language(profile: Profile, title: Sequence[str]) -> bool:
    # A profile that lists no language switches the rule off, like an empty list elsewhere.
    if not profile.languages:
        return True
    known = {_LANGUAGE_KEY.get(normalise(name), normalise(name)) for name in profile.languages}
    for languages, every in _requests(title):
        fits = all if every else any
        if not fits(language in known for language in languages):
            return False
    return True


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
