# Store everything in one SQLite file

Status: accepted
Date: 2026-11-19

## Context

The program runs on one machine, for one user, about once a day. It has to remember which postings it has seen, how their text changed and what each run did. Later milestones add rule results and verdicts to the same data.

## Decision

All state is kept in one SQLite file, `data/ranker.db`, through the `sqlite3` module of the standard library, with plain SQL and no object mapper.

The schema version is stored in SQLite's `user_version`. The program creates the schema in an empty file and refuses to open a file with a version it does not know.

## Consequences

* There is no server to run and no extra dependency.
* The file is private data and is not committed.
* There is no migration tool. A schema change needs a new version number and a migration step written by hand.
* One writer at a time. Two runs at once are not supported.
