# Recognise duplicates across sources by company name and title

Status: accepted
Date: 2026-11-19

## Context

The same job can arrive from a company feed and from the search source. The two copies have different IDs and addresses, and the sources write the location in different ways. Without a rule, the job is judged and sent twice.

## Decision

Each posting gets a match key: the company name and the title, with case, accents and punctuation removed, and the company name without a legal-form ending such as GmbH or Inc. A `+`, a `#` and a `.` that starts a word are kept as words, so titles such as `C++`, `C#` and `.NET` stay apart. A match key with no company word or no title word is empty and is never matched.

A new posting with the same match key as a stored posting from a different source is saved with a link to that posting and counted as a duplicate. The link is only made to a posting that is not itself a duplicate. The earlier posting stays the original. Company feeds are collected before the search source, so within one run the feed copy is the original.

Postings from the same source are never linked, and the location is not compared.

When the company name or the title of a stored posting changes, its link is looked up again, and so are the links of the postings that pointed to it.

## Consequences

* Later stages can skip a posting that has a link.
* A copy is missed when the two sources spell the company name or the title differently.
* Names that differ only in accents, such as an umlaut written without its dots, get the same match key.
* A company that offers the same title in two places can have the search copy for one place linked to the feed posting for the other.
* A link can be added or removed after a posting was first stored.
* A second posting from one source with the same match key is stored as a new posting, even when a posting from another source is linked to the first.
* A posting that the search source lists again under a new ID is stored as a new posting.
