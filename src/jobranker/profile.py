"""The private profile: what a posting has to offer to be worth a closer look."""

import hashlib
import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from jobranker.config import Text

EXAMPLE = "config/profile.example.yaml"
# The fields the rules read. A change in any other field leaves the rule results valid.
_RULE_FIELDS = frozenset({"places", "remote", "levels", "languages", "avoid", "title_words"})


class ProfileError(Exception):
    """A profile that cannot be used. The message names the file and the field, never a value."""


class RemoteRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    accept: StrictBool = True
    places: list[Text] = Field(default_factory=list)


class Levels(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    accept: list[Text] = Field(default_factory=list)
    reject: list[Text] = Field(default_factory=list)


class Profile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    places: list[Text]
    remote: RemoteRule = Field(default_factory=RemoteRule)
    levels: Levels = Field(default_factory=Levels)
    languages: list[Text] = Field(default_factory=list)
    avoid: list[Text] = Field(default_factory=list)
    title_words: list[Text] = Field(default_factory=list)
    # Read by the judge from milestone 4 on.
    roles: list[Text] = Field(default_factory=list)
    skills: list[Text] = Field(default_factory=list)
    notes: str = ""

    @property
    def digest(self) -> str:
        """A hash of the fields the rules read. Stored with each rule result."""
        fields = self.model_dump(include=set(_RULE_FIELDS))
        return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()


def load_profile(path: Path) -> Profile:
    """Read the profile, or raise `ProfileError` with a message that is safe to print."""
    if not path.exists():
        raise ProfileError(f"{path}: not found. Copy {EXAMPLE} to {path} and fill it in.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError) as error:
        raise ProfileError(f"{path}: cannot be read ({type(error).__name__})") from None
    except (yaml.YAMLError, ValueError) as error:
        # The loader raises a plain ValueError for a value such as an impossible date.
        raise ProfileError(f"{path}: not valid YAML ({type(error).__name__})") from None
    if not isinstance(data, dict):
        raise ProfileError(f"{path}: expected fields such as 'places:', as in {EXAMPLE}")
    try:
        return Profile.model_validate(data)
    except ValidationError as error:
        # Only the field name and the kind of problem are kept, so no profile value is printed.
        problems = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc'])}: {issue['type']}"
            for issue in error.errors(include_input=False, include_url=False)
        )
        raise ProfileError(f"{path}: {problems}") from None
