# Record design decisions as ADRs

Status: accepted
Date: 2026-11-18

## Context and Problem Statement

I work on this project alone, in milestones, with AI assistance. I make a choice once, such as which job feeds to read or how the model gets called, and a few weeks later I no longer remember why. The code shows what I built. It doesn't show what I turned down. My commit messages are one line each, so the reasons don't fit there.

How should the project keep track of its design decisions?

## Considered Options

* One ADR file per decision in `docs/decisions/`
* A single `DECISIONS.md` that lists every decision
* No records, with the reasoning left to commit messages and memory

## Decision Outcome

Chosen option: "One ADR file per decision", because each decision gets its own file and its own history. If I change my mind later, I write a new record that replaces the old one and leave the others alone. The template also makes me list the options I rejected, and those are what I forget first.

I only write a record when there was a real alternative. A choice with one sensible answer doesn't need one.

### Consequences

* Good, because a reader can see why something was built this way without asking me.
* Good, because I write most of the code with AI assistance. The decisions are mine, and this is where they are written down.
* Bad, because every decision costs a few minutes of writing.
* Bad, because a record goes stale if the code changes and I don't update it.
