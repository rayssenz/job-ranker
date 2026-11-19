# Collect from public company feeds and one search source

Status: accepted
Date: 2026-11-19

## Context

Company job feeds (Greenhouse, Lever, Ashby) are public, documented and need no login, but they only cover companies that are named in advance. Finding postings from other companies needs a search by words and place. LinkedIn has no public API for that.

## Decision

Postings come from two kinds of source.

* Company feeds are read directly from the three providers' public addresses.
* LinkedIn search results are read through an Apify actor that fetches the public job pages. The program does not scrape pages itself.

No source uses an account login or a logged-in browser. The Apify service needs one token. It is read from the environment or a local `.env` file that is not committed, and it is never stored or logged. The actor name is a setting.

## Consequences

* A search is billed per result. Each run asks for a limited number of results and each request carries a cost cap.
* The actor is published by a third party. It can change its output, change its price or disappear, and then the mapping or the setting has to change.
* Reading LinkedIn pages this way is outside LinkedIn's terms of use.
* Tests never call a source. They run against made-up samples in the documented shape, so a change in a real response is found only by a live run.
