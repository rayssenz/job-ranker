# job-ranker

A command-line program that collects new job postings from public company job feeds and from one job search source, drops the ones that cannot fit a profile, has Claude judge the rest, and sends a short list to Telegram. It measures its own ranking against a set of hand-marked postings, and CI fails when that measurement drops.

## Status

Milestone 1 is done: `jobrank collect` fetches postings from Greenhouse, Lever and Ashby company feeds and from a LinkedIn search, and stores them in a local SQLite file. Milestone 2 is done: `jobrank rules` drops the postings that cannot fit a private profile, and `jobrank list` prints the rest. Milestone 3 is done: `jobrank dashboard` shows the postings that passed as cards in the browser, with a decision per posting. Milestone 4 is done: `jobrank judge` has Claude say yes or no to each posting that passed, with reasons. How good the judge is has not been measured yet.

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

## Judge postings

```bash
uv run jobrank judge --dry-run
uv run jobrank judge
```

The command has Claude read each posting that passed the rules and answer yes or no, with one to three short reasons and the requirements the profile covers and lacks. It needs [Claude Code](https://code.claude.com) installed and signed in with a Claude plan. Add `roles`, `skills` and `notes` to `profile.yaml` first, as in the example file.

- `--dry-run` prints how many postings wait and judges nothing.
- One run judges at most 40 postings, newest first (`--limit`). A larger backlog takes several runs.
- A posting is judged once, and again only when its text, the judge's part of the profile, the prompt or the model changes.
- `--model` picks another model than the small default.
- A failed call stores no verdict. The posting is tried again on a later run, behind the postings that have not failed. Three failed calls in a row stop the run.
- The profile needs `roles` or `skills`. Without both the command refuses to start.

The command sends each posting and the roles, skills, notes, languages and level words of the profile to the model provider through Claude Code. It sends nothing else. The verdicts stay in `data/ranker.db`.

### Cost

The judge uses the plan login of Claude Code and no API key, so the calls draw from the usage limits of the plan. Two cases lead to a bill on top of the plan:

- A model API key or token is set in the environment. The command refuses to start and names the variable.
- The account has usage credits turned on. A call after a reached plan limit is then billed and does not fail. The program cannot see this setting, so turn usage credits off in the account settings.

With usage credits off, a reached plan limit stops the run and the next run continues. Judging shares the limits with every other use of the same account. The cost figure stored with each verdict is computed from list prices and is not a charge.

## Review postings in the browser

```bash
uv run jobrank dashboard
```

The command applies the rules, starts a small web application on `http://127.0.0.1:8765` and opens it in the browser. Ctrl+C stops it. Postings collected while it runs show up after a reload.

- **To review** shows the postings that passed the rules as cards, newest first. "Applied" and "Not for me" move a posting to its own tab, so the list gets shorter. A switch keeps student and junior titles only, and a search field looks in title, company and place.
- A card that was judged shows "Fits" or "Does not fit" with the reasons. The switch "Only yes" keeps the yes cards, with the fewest missing requirements first. It is off at the start, so a posting with a no is still shown. The dashboard reads `profile.yaml` once, at its start. After a change of the profile, start it again, or the cards say "Not judged yet".
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
- [Milestone 4: judge](docs/specs/2026-11-20-m4-judge.md)
- Decision records live in `docs/decisions/`.

## How this was built

Built with AI assistance. Specs and tests come before code, and the design decisions are recorded in `docs/decisions/`.

## Licence

MIT. See [LICENSE](LICENSE).
