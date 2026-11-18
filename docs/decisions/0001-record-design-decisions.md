# Record design decisions as ADRs

Status: accepted
Date: 2026-11-18

## Context

I work on this project alone, in milestones, with AI assistance. I make a choice once, such as which job feeds to read or how the model gets called, and a few weeks later I no longer remember why. The code shows what I built. It doesn't show the reason. My commit messages are one line each, so the reasons don't fit there.

## Decision

Each design decision gets its own ADR (architecture decision record), a short file in `docs/decisions/`, with the context and the decision. If I change my mind later, I write a new record that replaces the old one and leave the others alone.

I only write a record for a decision that shapes the project. Small choices don't need one.
