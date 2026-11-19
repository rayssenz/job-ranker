"""Loading of the company list, the search list and the Apify token."""

from collections.abc import Hashable, Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

TOKEN_VARIABLE = "APIFY_TOKEN"


class ConfigError(Exception):
    """A configuration file that cannot be used. The message names the file and the entry."""


class Company(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    feed: Literal["greenhouse", "lever", "ashby"]
    token: str = Field(min_length=1)
    region: Literal["global", "eu"] = "global"

    @model_validator(mode="after")
    def _region_is_for_lever(self) -> "Company":
        if self.region != "global" and self.feed != "lever":
            raise ValueError("region is only used with the lever feed")
        return self


class Search(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    keywords: str = Field(min_length=1)
    location: str = Field(min_length=1)
    posted_within: Literal["day", "week", "month"] = "day"
    limit: int = Field(default=50, ge=1, le=500)


def _entries(path: Path, key: str) -> list[Any]:
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise ConfigError(f"{path}: not valid YAML ({type(error).__name__})") from error
    if data is None:
        return []
    if not isinstance(data, dict) or not isinstance(data.get(key, []), list):
        raise ConfigError(f"{path}: expected a top-level '{key}:' list")
    entries: list[Any] = data.get(key, [])
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
        if "token" in entry and entry["token"] is not None:
            entry = entry | {"token": str(entry["token"])}
        try:
            company = Company.model_validate(entry)
        except ValidationError as error:
            raise ConfigError(f"{where}: {_problems(error)}") from error
        _reject_duplicate(seen, (company.feed, company.token, company.region), where)
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
    for line in env_file.read_text().splitlines():
        name, separator, raw = line.strip().removeprefix("export ").partition("=")
        if separator and name.strip() == TOKEN_VARIABLE:
            value = raw.strip().strip("\"'")
            return value or None
    return None
