# job-ranker

A command-line program that collects new job postings from public company job feeds and from one job search source, drops the ones that cannot fit a profile, has Claude judge the rest, and sends a short list to Telegram. It measures its own ranking against a set of hand-marked postings, and CI fails when that measurement drops.

## Status

Milestone 1 is done: `jobrank collect` fetches postings from Greenhouse, Lever and Ashby company feeds and from a LinkedIn search, and stores them in a local SQLite file. Nothing ranks yet.

## Quick start

```bash
uv sync
uv run pytest
```

## Collect postings

```bash
cp config/companies.example.yaml config/companies.yaml
cp config/searches.example.yaml config/searches.yaml
cp .env.example .env
uv run jobrank collect
```

Edit the two copied files first. The example entries are made up and their feeds do not exist. Either file can be left out.

- `config/companies.yaml` lists companies with their feed type and board name. These feeds are public and need no key.
- `config/searches.yaml` lists LinkedIn searches by words and place. They run through an [Apify](https://apify.com) actor and need an Apify token in `.env` as `APIFY_TOKEN`. Without a token the searches are skipped.

In a terminal the command shows each source as it finishes, a bar with the number of sources done, and the source it is collecting now. `--quiet` prints plain lines only, which is also what a file or a scheduled job gets.

Apify bills each search result. A run asks for at most 200 results in total (`--max-results`), and every request carries a cost cap.

The command prints one line per company and per search: how many postings it fetched and how many of them are new, changed or duplicates. Postings are stored in `data/ranker.db`. The two configuration files, `.env` and `data/` are ignored by git.

## Design

- [Technical design](docs/specs/2026-11-18-technical-design.md)
- [Milestone 1: sources and storage](docs/specs/2026-11-19-m1-sources-and-storage.md)
- Decision records live in `docs/decisions/`.

## How this was built

Built with AI assistance. Specs and tests come before code, and the design decisions are recorded in `docs/decisions/`.

## Licence

MIT. See [LICENSE](LICENSE).
