# Recognise duplicates across sources by company name and title

Status: accepted
Date: 2026-11-19

## Context

The same job can arrive from a company feed and from the search source. The two copies have different IDs and addresses, and the sources write the location in different ways. Without a rule, the job is judged and sent twice.

## Decision

Each posting gets a match key: the company name and the title, in lower case with punctuation removed, and the company name without a legal-form ending such as GmbH or Inc.

A new posting with the same match key as a stored posting from a different source is saved with a link to that posting and counted as a duplicate. The earlier posting stays the original. Company feeds are collected before the search source, so within one run the feed copy is the original.

Postings from the same source are never linked, and the location is not compared.

## Consequences

* Later stages can skip a posting that has a link.
* A copy is missed when the two sources spell the company name or the title differently.
* A company that offers the same title in two places can have the search copy for one place linked to the feed posting for the other.
* A posting that the search source lists again under a new ID is stored as a new posting.
