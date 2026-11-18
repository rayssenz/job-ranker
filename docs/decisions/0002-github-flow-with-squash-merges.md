# Use GitHub Flow with squash merges

Status: accepted
Date: 2026-11-18

## Context

The repository has one maintainer and is built one milestone at a time. `main` must always pass CI. There are no scheduled releases and no older versions to maintain.

## Decision

The project uses GitHub Flow with squash merges.

* Each milestone gets one short-lived branch and one pull request.
* CI must pass before a pull request is merged, and `main` is protected.
* Pull requests are squash-merged, so `main` gets one commit per milestone, named after the pull request.
* Commit messages are one line with a prefix: `feat:`, `test:`, `ci:`, `docs:`, `chore:`.
* Each milestone is tagged when it merges (`m0`, `m1`, and so on).

## Consequences

* `main` has one commit per milestone. The individual commits stay on the pull request.
* Squashing does not remove commits that were already pushed to a branch, so private files must never be pushed. The ignore list and a test guard against that.
