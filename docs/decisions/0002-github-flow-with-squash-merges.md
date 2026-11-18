# Use GitHub Flow with squash merges

Status: accepted
Date: 2026-11-18

## Context and Problem Statement

I'm the only one working on this repository, and I do one milestone at a time. `main` should always pass the checks. Its history should also make sense to someone who wasn't there when the work happened.

Which branching and merging convention should the project use?

## Considered Options

* GitHub Flow with squash merges
* GitHub Flow with rebase and merge
* GitHub Flow with merge commits
* Git Flow

## Decision Outcome

Chosen option: "GitHub Flow with squash merges".

Each milestone gets one short-lived branch and one pull request, and the checks have to pass before I merge it. Git Flow would add a permanent `develop` branch plus release and hotfix branches. I have no scheduled releases and no old versions to maintain, so those branches would have nothing to do.

I chose squash over rebase and merge because work on a branch gets messy: a wrong turn, a fix, a fix for the fix. With squash none of that lands on `main`. `main` gets one commit per milestone, named after the pull request.

The rest of the convention:

* Commit messages are one line with a prefix: `feat:`, `test:`, `ci:`, `docs:`, `chore:`.
* `main` is protected, so nothing merges unless the checks pass.
* Each milestone is tagged when it merges (`m0`, `m1`, and so on).

### Consequences

* Good, because `main` stays short and readable however the branch looked.
* Good, because the step-by-step commits are still on the pull request page for anyone who wants the detail.
* Bad, because the small commits are not on `main`, so `git bisect` there can only point at a whole milestone.
* Bad, because the detailed history depends on GitHub keeping the pull requests.
* Squash does not remove anything that was pushed. A secret pushed to a branch is public, so the ignore list and the private-file test still have to do their job.
