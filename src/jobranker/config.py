"""Loading of the company list, the search list and the Apify token."""

import re
from collections.abc import Hashable, Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

TOKEN_VARIABLE = "APIFY_TOKEN"
# In an unquoted value a comment starts at a # that follows white space or starts the value.
_INLINE_COMMENT = re.compile(r"(?:^|\s)#")

# Text with the spaces around it removed and at least one character left.
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# A board token is one part of an address, so it has no space and no address mark.
BoardToken = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, pattern=r"^[^\s/?#]+$")
]


class ConfigError(Exception):
    """A configuration file that cannot be used. The message names the file and the entry."""


class Company(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Text
    feed: Literal["greenhouse", "lever", "ashby"]
    token: BoardToken
    region: Literal["global", "eu"] = "global"

    @model_validator(mode="after")
    def _region_is_for_lever(self) -> "Company":
        if self.region != "global" and self.feed != "lever":
            raise ValueError("region is only used with the lever feed")
        return self


class Search(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    keywords: Text
    location: Text
    posted_within: Literal["day", "week", "month"] = "day"
    # Strict, so that YAML's true is not read as the number 1.
    limit: int = Field(default=50, ge=1, le=500, strict=True)


def _entries(path: Path, key: str) -> list[Any]:
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"{path}: cannot be read ({type(error).__name__})") from None
    except (yaml.YAMLError, ValueError) as error:
        # The loader raises a plain ValueError for a value such as an impossible date.
        raise ConfigError(f"{path}: not valid YAML ({type(error).__name__})") from None
    if data is None:
        return []
    # Any other top-level key is refused, so a mistyped key is not read as an empty list.
    if not isinstance(data, dict) or set(data) != {key}:
        raise ConfigError(f"{path}: expected a top-level '{key}:' list and nothing else")
    entries = data[key]
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise ConfigError(f"{path}: expected a top-level '{key}:' list")
    return entries


def _problems(error: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in issue['loc']) or 'entry'}: {issue['msg']}"
        for issue in error.errors()
    )


def _reject_duplicate(seen: set[Hashable], identity: Hashable, where: str) -> None:
    if identity in seen:
        raise ConfigError(f"{where}: duplicate entry")
    seen.add(identity)


def load_companies(path: Path) -> list[Company]:
    """Read the company list. A missing file gives an empty list."""
    companies: list[Company] = []
    seen: set[Hashable] = set()
    for index, entry in enumerate(_entries(path, "companies"), start=1):
        label = entry.get("name", "?") if isinstance(entry, dict) else "?"
        where = f"{path}: company {index} ({label})"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where}: expected name, feed and token")
        # YAML reads an unquoted 0123 as the number 83, so a number is never turned into text.
        if entry.get("token") is not None and not isinstance(entry["token"], str):
            raise ConfigError(f'{where}: token must be quoted, for example token: "0123"')
        try:
            company = Company.model_validate(entry)
        except ValidationError as error:
            raise ConfigError(f"{where}: {_problems(error)}") from error
        _reject_duplicate(seen, (company.feed, company.token.lower(), company.region), where)
        companies.append(company)
    return companies


def load_searches(path: Path) -> list[Search]:
    """Read the search list. A missing file gives an empty list."""
    searches: list[Search] = []
    seen: set[Hashable] = set()
    for index, entry in enumerate(_entries(path, "searches"), start=1):
        label = entry.get("keywords", "?") if isinstance(entry, dict) else "?"
        where = f"{path}: search {index} ({label})"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where}: expected keywords and location")
        try:
            search = Search.model_validate(entry)
        except ValidationError as error:
            raise ConfigError(f"{where}: {_problems(error)}") from error
        _reject_duplicate(seen, (search.keywords.lower(), search.location.lower()), where)
        searches.append(search)
    return searches


def read_token(environ: Mapping[str, str], env_file: Path) -> str | None:
    """Return the Apify token from the environment, else from the env file, else None."""
    value = environ.get(TOKEN_VARIABLE, "").strip()
    if value:
        return value
    if not env_file.is_file():
        return None
    # utf-8-sig also reads a file that starts with a byte order mark.
    try:
        lines = env_file.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"{env_file}: cannot be read ({type(error).__name__})") from None
    for line in lines:
        name, separator, raw = line.strip().removeprefix("export ").partition("=")
        if separator and name.strip() == TOKEN_VARIABLE:
            value = _env_value(raw)
            # An empty line, as copied from .env.example, does not hide a later one.
            if value:
                return value
    return None


def _env_value(raw: str) -> str:
    raw = raw.strip()
    if raw[:1] == '"':
        # Inside double quotes a backslash keeps the next character, so \\" is a quote mark.
        value: list[str] = []
        characters = iter(raw[1:])
        for character in characters:
            if character == '"':
                break
            value.append(next(characters, "") if character == "\\" else character)
        return "".join(value).strip()
    if raw[:1] == "'":
        # A quoted value ends at the closing quote, so a # inside the quotes is kept.
        return raw[1:].partition("'")[0].strip()
    return _INLINE_COMMENT.split(raw, maxsplit=1)[0].strip()
