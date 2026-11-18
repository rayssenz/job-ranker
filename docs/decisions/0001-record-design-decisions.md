# Record design decisions as ADRs

Status: accepted
Date: 2026-11-18

## Context

Design choices in this project are made once and are not visible in the code. Commit messages are one line, so they do not hold the reasoning either.

## Decision

Each decision that shapes the project is recorded as an ADR (architecture decision record): a short numbered file in `docs/decisions/` with the context and the decision.

When a decision changes, a new record replaces the old one. Existing records are not edited.

## Consequences

* Each decision has its own file and its own history.
* A record has to be updated or replaced when the code changes, or it goes stale.
