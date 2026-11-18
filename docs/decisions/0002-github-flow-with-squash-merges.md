# Use GitHub Flow with squash merges

Status: accepted
Date: 2026-11-18

## Context

I'm the only one working on this repository, and I do one milestone at a time. `main` should always pass the checks. Its history should also make sense to someone who wasn't there when the work happened.

## Decision

The project uses GitHub Flow with squash merges.

Each milestone gets one short-lived branch and one pull request, and the checks have to pass before I merge it. Work on a branch gets messy: a wrong turn, a fix, a fix for the fix. With squash none of that lands on `main`. `main` gets one commit per milestone, named after the pull request.

The rest of the convention:

* Commit messages are one line with a prefix: `feat:`, `test:`, `ci:`, `docs:`, `chore:`.
* `main` is protected, so nothing merges unless the checks pass.
* Each milestone is tagged when it merges (`m0`, `m1`, and so on).

