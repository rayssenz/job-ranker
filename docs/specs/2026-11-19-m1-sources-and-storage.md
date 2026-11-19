# Milestone 1: sources and storage

Status: approved on 2026-11-19.

## Problem

The program has a command and no behaviour. Before anything can be filtered or judged, it has to fetch postings, turn each source's format into one posting record, and remember what it has already seen so that a posting is reported as new only once. The same job can arrive from two sources, so the store also has to recognise a second copy.

## What is built

A `jobrank collect` command that reads two configuration files, calls each source, converts every posting to a common record and saves it in a SQLite file.

There are two kinds of source:

- Company feeds return every open posting of one named company. Three feed types are supported: Greenhouse, Lever and Ashby.
- A search source returns the postings that match search words and a place, from any company. One is supported: LinkedIn, through an Apify actor that reads the public job pages without a login.

### Company feeds

The addresses below were checked against each provider's documentation and with one live request each on 2026-11-19. All three answer without a login or a key, and answer 404 for an unknown board.

| Feed | Request | Documentation |
| --- | --- | --- |
| Greenhouse | `GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | developers.greenhouse.io/job-board.html |
| Lever | `GET https://api.lever.co/v0/postings/{token}?mode=json` (EU: `api.eu.lever.co`) | github.com/lever/postings-api |
| Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/{token}` | developers.ashbyhq.com/docs/public-job-posting-api |

Notes:

- Greenhouse returns the description only with `content=true`, as HTML with its characters escaped. The adapter unescapes it and removes the tags.
- Lever's `descriptionPlain` leaves out the requirement lists and the closing text. The adapter joins all three parts.
- Lever's documentation gives `skip` and `limit` and no maximum page size. The adapter asks for pages of 100 until a page comes back with fewer. It stops with an error after 50 pages, so a feed that ignores `skip` cannot be read forever.
- Ashby's `id` is present in the live response and in no documented field table. When it is missing, the adapter uses `jobUrl` as the ID. Ashby postings with `isListed` false are skipped.

### LinkedIn search

| Item | Value |
| --- | --- |
| Request | `POST https://api.apify.com/v2/actors/{actor}/run-sync-get-dataset-items` |
| Documentation | docs.apify.com/api/v2/act-run-sync-get-dataset-items-post |
| Default actor | `valig~linkedin-jobs-scraper` |
| Request body | `keywords`, `location`, `datePosted`, `limit` |
| Cost cap | `maxTotalChargeUsd` in the query string, enforced by Apify |
| Success | status 201 with a JSON list of results |
| Token | `APIFY_TOKEN`, read from the environment or a local `.env` file, sent in the `Authorization` header |

The request address and the actor's input and output fields were read from the Apify documentation and the actor's published schema on 2026-11-19. A live run needs a token, so none has been made yet. The first one is a manual check before the pull request is merged.

Notes:

- The endpoint waits for the actor to finish and answers 408 when a run takes longer than 300 seconds. The adapter treats that as a failed source.
- The actor is published by a third party and can change or disappear. The actor name is a setting, and the mapping from its output to the posting record sits in one function.
- The actor's output includes the recruiter's name and profile address. The adapter drops them.
- Apify answers 401 for a bad token and 402 when the account has no credit left. Both are failed sources with that reason in the run log.
- Apify bills the account for each result, including results the store already holds. A run asks for at most 200 results in total by default (`--max-results`), shared across the searches in order, so a later search can get fewer than its own limit or none. Each request also carries a cost cap worked out from that number.
- A search covers the last day by default. A day without a run leaves a gap unless the next run uses `posted_within: week`.
- Without a token the command skips the LinkedIn source, says so, and still runs the company feeds.
- The token never appears in a log line, an error message or the database.

### Field mapping

| Record field | Greenhouse | Lever | Ashby | LinkedIn actor |
| --- | --- | --- | --- | --- |
| posting ID | `id` (integer) | `id` | `id` | `id` |
| company | from the company list | from the company list | from the company list | `companyName` |
| title | `title` | `text` | `title` | `title` |
| location | `location.name` | `categories.location` | `location` | `location` |
| remote | not provided | `workplaceType` | `workplaceType` | not provided |
| URL | `absolute_url` | `hostedUrl` | `jobUrl` | `url` |
| description | `content` | `descriptionPlain`, `lists`, `additionalPlain` | `descriptionPlain` | `description` |

The remote flag has three values: `yes`, `no`, `unknown`. Hybrid counts as `no`. Greenhouse postings, LinkedIn postings and Lever's `unspecified` are `unknown`. Ashby's `isRemote` is not used because it is also true for hybrid.

### Configuration

Both files are read at run time and are not committed. Each has a committed example with made-up content.

- `config/companies.yaml` (example: `config/companies.example.yaml`). Each entry has a `name` (written as the company writes it, because duplicates are matched on it), a `feed` (`greenhouse`, `lever` or `ashby`), a `token`, and for Lever an optional `region` (`global` or `eu`, default `global`).
- `config/searches.yaml` (example: `config/searches.example.yaml`). Each entry has `keywords`, a `location`, and optionally `posted_within` (`day`, `week` or `month`, default `day`) and a `limit` (default 50).

Either file may be absent. The command stops only when both are.

`.env.example` is committed and lists `APIFY_TOKEN` with no value.

### Posting record

Source, board token, posting ID (stored as text), company name, title, location, remote flag, URL, description as plain text, first-seen time, last-seen time, a content hash, a match key, and an optional link to the posting it duplicates.

- A posting is identified by source, board token and posting ID. LinkedIn postings have no board token, and the actor name is not part of the identity, so changing the actor does not make stored postings look new.
- The content hash is SHA-256 over the title, location, remote flag and description.
- The match key is the company name and the title, each in lower case with punctuation removed, and the company name without a legal-form ending such as GmbH, AG, SE, Inc, Ltd or LLC.

### Duplicates

When a new posting has the same match key as a stored posting from a different source, the store saves it with a link to that earlier posting and counts it as a duplicate instead of a new posting. The command collects company feeds before the search source, so within one run the feed copy is the original. Two postings from the same source are never linked, because a company can publish the same title for two places. A link always points to a posting that is not itself a duplicate.

The rule ignores the location, because the sources write it differently. A company that offers the same title in two places can therefore have its LinkedIn posting for one place linked to the feed posting for the other.

### Storage

One SQLite file, `data/ranker.db` by default, created on first use with a recorded schema version. Three tables:

- postings: one row per posting.
- posting versions: one row each time a posting's hash changes, with the time.
- run log: one row per company or search per run, with the number of postings fetched, new, changed and duplicate, or the error.

## Non-goals

- Rules, judging, shortlists, delivery and evaluation. No tables for rule results or verdicts yet.
- Other sources. No logged-in source and no scraping done by this program itself.
- Finding out which feed a company uses. The list states it.
- Marking a posting as closed when it stops appearing. Last-seen time is stored so this can be added.
- Retries, parallel requests and scheduling. A failed source is tried again on the next run.
- Parsing a country out of the location text. That belongs to the rules.
- Matching duplicates whose company name or title is written differently in the two sources, or a posting that LinkedIn lists again under a new ID.
- Sending the stored LinkedIn IDs to the actor so that known postings are not billed again.

## Acceptance criteria

1. `jobrank collect` with the example files and sample responses stores one record per posting from all four sources, with every record field filled as in the mapping table.
2. Running it twice on the same responses stores nothing new the second time and reports zero new postings.
3. A posting whose text changed between two runs keeps its first-seen time, gets its new hash recorded with the time, and is counted as changed, not new.
4. Two postings with the same ID on different boards or sources are stored as two postings.
5. A posting from LinkedIn with the same company and title as a stored feed posting is saved with a link to it and counted as a duplicate. Company names that differ only in case, punctuation or legal-form ending still match. Two postings with the same title from the same source are not linked.
6. A source that answers with an error status, times out or returns something that is not the expected JSON is recorded in the run log with the company or search and the reason. The other sources are still collected, and the command exits 0. It exits 1 when every source failed or when no source could be tried, for example with only searches configured and no token. A single posting that lacks an ID or a title is skipped and counted, and the rest of its source is still stored.
7. A configuration file with an unknown feed type, a missing field or a duplicate entry is rejected before any request is made, with a message that names the entry.
8. With neither configuration file present, the command stops with a message that points to the example files.
9. Each feed adapter builds the request shown in the feeds table, including Lever's EU host and Lever's paging.
10. The LinkedIn adapter sends the request shown in the LinkedIn table, with the token in the header and not in the address. With no token it is skipped with a message and the feeds still run.
11. The total number of results asked from the actor in one run never exceeds the run limit, and every request carries the cost cap.
12. The token does not appear in the command's output, the run log or the database, including when the request fails.
13. The recruiter fields of the actor's output are not stored anywhere.
14. A Greenhouse description comes out as plain text with no tags and no escaped characters. A Lever description contains the lists and the closing text.
15. The command prints one summary line per company or search: fetched, new, changed, duplicate, or the error.
16. No test uses the network. The samples under `tests/` are made up in the documented shape and contain no real company, person or advert text.
17. `searches.yaml` is ignored by git and covered by the repository hygiene test, like `companies.yaml`.
18. `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` and `uv run pytest` pass on Python 3.12 and 3.14.

## Changes to the technical design

`docs/specs/2026-11-18-technical-design.md` is updated in the same pull request:

- Constraints: still no model API key. The Apify service needs one token.
- What it does and Scope: postings come from company feeds and from one search source.
- Sources: the search source, the second configuration file and the duplicate rule are added.
- Repository: `config/searches.example.yaml` and `.env.example` are listed.
- Risks: the third-party actor can change or disappear, and reading LinkedIn pages through it is outside LinkedIn's terms of use.

## Decision records

- 0003: collect from public company feeds and from one search source that needs no login.
- 0004: store everything in one SQLite file through the standard library.
- 0005: recognise duplicates across sources by company name and title.

## Dependencies added

httpx for requests, pydantic for the record and the source shapes, pyyaml for the configuration files.
