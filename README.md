# job-ranker

A command-line program that collects new job postings from public company job feeds and from one job search source, drops the ones that cannot fit a profile, has Claude judge the rest, and sends a short list to Telegram. It measures its own ranking against a set of hand-marked postings, and CI fails when that measurement drops.

## Status

Milestone 1 is done: `jobrank collect` fetches postings from Greenhouse, Lever and Ashby company feeds and from a LinkedIn search, and stores them in a local SQLite file. Milestone 2 is done: `jobrank rules` drops the postings that cannot fit a private profile, and `jobrank list` prints the rest. Milestone 3 is done: `jobrank dashboard` shows the postings that passed as cards in the browser, with a decision per posting. Nothing is ranked yet.

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


## Filter postings

```bash
cp config/profile.example.yaml profile.yaml
uv run jobrank rules
uv run jobrank list
```

Edit `profile.yaml` first. It says which places, level words and languages fit, which words to avoid, and which words a title must hold. The file is not committed.

- `jobrank rules` checks every stored posting against the profile and prints how many postings each rule dropped. A posting is dropped only when the mismatch is certain. A posting is checked again only when it or the profile changed.
- `jobrank list` prints the postings that passed, newest first. `--days 7` limits the list to the last week and `--limit` sets its length.

Neither command sends a request.

## Review postings in the browser

```bash
uv run jobrank dashboard
```

The command applies the rules, starts a small web application on `http://127.0.0.1:8765` and opens it in the browser. Ctrl+C stops it. Postings collected while it runs show up after a reload.

- **To review** shows the postings that passed the rules as cards, newest first. "Applied" and "Not for me" move a posting to its own tab, so the list gets shorter. A switch keeps student and junior titles only, and a search field looks in title, company and place.
- **Applied** and **Not for me** show what was decided, each with "Undo".
- **Runs** shows the last ten collection runs and the sources that the latest one did not collect.

The page has a playful look with motion: cards pop in, a card that is new today has eyes that follow the pointer, and "Applied" slaps a sticker on the card. With reduced motion set in the system, nothing moves.

`--port` picks another port (1024 or higher) and `--no-open` leaves the browser alone.

The application answers on this machine only, sends no request, and loads no file from another machine. A posting is text from a third party, so it is always shown as text. Changing a decision needs a token that is made new at each start.

## Design

- [Technical design](docs/specs/2026-11-18-technical-design.md)
- [Milestone 1: sources and storage](docs/specs/2026-11-19-m1-sources-and-storage.md)
- [Milestone 2: rules](docs/specs/2026-11-19-m2-rules.md)
- [Milestone 3: local dashboard](docs/specs/2026-11-19-m3-dashboard.md)
- [Dashboard: the toy box look](docs/specs/2026-11-20-dashboard-toy-box-look.md)
- Decision records live in `docs/decisions/`.

## How this was built

Built with AI assistance. Specs and tests come before code, and the design decisions are recorded in `docs/decisions/`.

## Licence

MIT. See [LICENSE](LICENSE).
