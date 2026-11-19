# Job Ranker: technical design

Status: approved on 2026-11-18.

## 1. What it does

A command-line program that collects new job postings from public company job feeds and from one job search source, drops the ones that cannot fit a profile, has Claude judge the rest, and sends a short list to Telegram. It measures its ranking against a set of hand-marked postings, and CI fails when that measurement drops.

## 2. Scope

In scope

- Collect postings from public job feeds for a configured list of companies, and from one search source for a configured list of searches.
- Drop postings that cannot fit, using fixed rules, with a reason for each drop.
- Have Claude judge the rest: yes or no, with reasons.
- Send a short list of new yes postings to Telegram through a Hermes agent.
- Measure agreement with hand-made marks, publish a report, and fail CI when quality drops.

Out of scope

- Writing or tailoring CVs and cover letters.
- Filling in or submitting applications.
- A hosted web interface. The dashboard of milestone 3 runs on the local machine only.
- Learning automatically from the marks. They are used only to measure.

Never

- Logging in to LinkedIn, Indeed, Xing or any personal account, or automating a logged-in browser.
- Committing a profile, a company list, or marks tied to a named employer.

## 3. Constraints

- No model API key. Model calls go through Claude Code's non-interactive mode on a logged-in subscription.
- The search source runs on the Apify service and needs one Apify token, read from the environment or a local `.env` file that is not committed.
- The repository is public, so private data is kept out of it.
- Python 3.12 or newer.
- The dashboard uses FastAPI, Uvicorn, Jinja2 and python-multipart. It needs no JavaScript build and loads no file from another machine.

## 4. Approach

A Python command-line program does everything, and the model is called from the code. Hermes and Claude Code are thin wrappers around it. The evaluation can run without an agent, so CI can gate on it.

No API key is needed. The program calls Claude Code's non-interactive mode locally, records the answers, and CI replays the recording.

## 5. How it works

```
feeds -> normalise -> store -> rules -> judge -> shortlist -> Hermes -> Telegram
                                  |        |
                                  +--------+--> evaluation against the marks
```

### Sources

Each source has its own adapter. There are two kinds.

Company feeds return every open posting of one company. All three are public and need no login: Greenhouse (`GET boards-api.greenhouse.io/v1/boards/{token}/jobs`), Lever (`GET api.lever.co/v0/postings/{token}`) and Ashby (`GET api.ashbyhq.com/posting-api/job-board/{token}`). Companies are listed in `config/companies.yaml` with their feed type and token.

The search source returns postings that match search words and a place. It is LinkedIn, read through an Apify actor that fetches the public job pages without a login. Searches are listed in `config/searches.yaml`. Each result is billed by Apify, so a run asks for a limited number of results and every request carries a cost cap.

A failing source is logged and skipped, and the run continues. The milestone 1 spec has the exact requests and the field mapping.

### Posting record

Each posting is stored with its source, company, title, location, remote flag, URL, description as plain text, first-seen time and a content hash. A posting is new when its source ID has not been seen before. A changed hash is recorded, and the posting is not sent again.

The same job can arrive from a company feed and from the search source. A new posting with the same company name and title as a stored posting from another source is saved with a link to that posting and is not treated as new.

### Storage

One SQLite file, `data/ranker.db`, holds postings, rule results, verdicts and run logs. It is not committed. Milestone 1 creates the tables for postings, posting versions and the run log. Milestone 2 adds the rule results. Milestone 3 adds the decisions. An older database is upgraded in place when it is opened.

### Profile

`profile.yaml` is not committed. `config/profile.example.yaml` is a fictional example. The rules read the accepted places, the remote preference, the accepted and rejected level words, the languages, the words to avoid and the words a title must hold. The judge reads the target roles, the skills and the free-text notes. Every word list is part of the profile, so the program holds no list that describes one person's search.

### Rules

The rules are pure functions over a posting and the profile. They check for a place or remote mismatch, a rejected level word in the title, a title that asks for a speaker of a language the profile lacks, a match on the avoid list, and a title without any of the wanted words. Each rule returns pass or a reason code, and a rule drops a posting only when the mismatch is certain. The result is stored per posting and computed again when the posting, the profile or the rules change. The milestone 2 spec has the exact conditions. No model is involved, so the same input always gives the same output.

### Dashboard

`jobrank dashboard` applies the rules, starts a web application on `127.0.0.1` and opens it in the browser. Postings collected while it runs get their rule results at the next page request. The milestone 3 spec and decision record 0009 have the details.

Four tabs, the first three with their count. "To review" shows the groups of linked postings that passed the rules and have no decision, newest first, fifty per page, with a switch for student and junior titles and a search over title, company and location. "Applied" and "Not for me" show the decided groups. "Runs" shows the last ten runs and the sources that the latest run did not collect.

A card has two decisions, "Applied" and "Not for me", and the decided tabs have "Undo". A decision is stored with the posting that was shown and counts for its whole group. A decided group stays in its tab when it no longer passes the rules, so a change of the profile removes no application from the list.

The application shows text from third parties and changes stored data. Every text is escaped when the page is built. A posting link is shown only when it is a plain `http` or `https` address. A request is served only when its `Host` names this machine and the port of this start. A request that changes data needs a `POST`, a token that is new at each start, and no foreign `Origin`. Every answer carries a content security policy and the headers that forbid framing and type guessing. The framework's automatic API pages are off.

### Judge

One interface with three implementations.

`ClaudeCodeJudge` runs `claude -p` as a subprocess with JSON output, a JSON schema for the answer, no tools, no saved session, no user settings loaded, a fixed system prompt and a pinned model. A call with this flag set was tested on 2026-11-18 on a subscription login with no API key set. It returned the structured answer, token counts, duration and a notional cost in about 1.8 seconds. A tiny prompt used about 1,200 input tokens, so each call carries a fixed overhead. `--bare` cannot be used because it requires an API key.

`ReplayJudge` returns recorded answers, keyed by prompt version and posting hash.

`FakeJudge` is for unit tests.

The answer has a `decision` (yes or no), `reasons`, and `matched` and `missing` requirement lists. Pass/fail is used instead of a 1 to 5 score because adjacent scores are subjective and need more data to measure.

### Shortlist

The shortlist holds the new yes postings, ordered by fewest missing requirements and then by newest. By default it keeps the top 5. The output is text, one block per posting with the reason and the link. On a day with nothing new, nothing is sent.

### Delivery

A Hermes scheduled job runs the program. It is created with `hermes cron create --no-agent --script <script> --deliver telegram`. In that mode Hermes uses no model. It runs the script and delivers the output as written, and an empty output sends nothing. A small Claude Code skill wraps the same commands for interactive use.

### Marking postings

A `cases add` command shows a stored posting, takes a yes or no and the slice tags, replaces the company name, and appends the case to the evaluation set. It refuses to write a case that still contains the company name.

### Limits

A run judges at most 40 postings by default. A judge failure is logged and the posting is retried on the next run.

## 6. Evaluation

- `evals/cases.jsonl` holds a posting snapshot, the mark (yes or no), and slice tags such as remote, seniority and language.
- The target is 60 cases, split into 40 for development and 20 held out. The prompt is tuned only on the development split. The set starts at 30 and grows.
- `evaluate --live` judges every case and writes the public recording `evals/recordings/<prompt-version>.jsonl`, a private full recording under `data/`, and `evals/report.md`. It runs locally.
- `evaluate --replay` recomputes the metrics from the recording. It runs in CI.
- Metrics: agreement, precision and recall of yes, a confusion table, per-slice results, cases marked yes that the rules dropped, and tokens, duration and notional cost per case.
- Staleness check: the recording stores a hash of the prompt and of the cases. CI fails if either changed without a new recording.
- CI gates on the development split. The held-out split is reported and looked at only when a milestone closes.
- The threshold is set after the first baseline run and written into a decision record. With 30 cases, one flipped answer moves agreement by about 3 points, so the report states the sample size next to every figure.

## 7. What is public and what is private

- Public: the evaluation cases (real postings with the company name replaced by a neutral ID), the mark on each, and a recording that holds, per case, whether the rules passed it and the judge's yes or no, with the prompt version, tokens, duration and notional cost.
- Private, kept under `data/`: the profile, the judge's written reasons and matched/missing lists, and the rule reason codes. Any of these can reveal profile details.
- CI replays the public recording against the marks. It cannot run the rules or the judge on the cases, because both need the profile. The rules are unit-tested against the fictional example profile.
- A reviewer can check that the score follows from the published answers, and can try live judging with the example profile. They cannot reproduce the original live run.
- CI cannot tell that the private profile changed. After a profile change the recording is redone by hand, and `evaluate --live` prints a reminder when the profile differs from the one last recorded.
- The name replacement is checked locally when a case is added. It cannot be checked in CI because the real company list is private.

## 8. Repository

```
src/jobranker/   cli, sources/, models, store, rules, judge/, shortlist, evaluate
tests/
evals/           cases.jsonl, recordings/, report.md, thresholds.yaml
config/          companies.example.yaml, searches.example.yaml, profile.example.yaml
integrations/    hermes/, claude-code/
docs/            specs/, decisions/
.github/workflows/ci.yml
.env.example
```

Stack: Python 3.12 or newer, uv for environments, ruff, a type checker, pytest, httpx, pydantic, PyYAML, typer, and SQLite from the standard library.

## 9. Process

- One short spec per milestone in `docs/specs/`: problem, non-goals, acceptance criteria.
- Decision records in `docs/decisions/`, written as ADRs (architecture decision records) when the choice is made.
- Tests are written first. Each milestone is one pull request with a description.
- CI runs lint, a type check and the tests. The evaluation replay, with its threshold and staleness check, joins CI in milestone 6.

## 10. Milestones

0. Repository, tooling, CI skeleton, decision record 1.
1. Sources and storage.
2. Rules.
3. Local dashboard: the postings that passed and the state of the last runs.
4. Judge with recording.
5. Marking command and the first 30 cases.
6. Evaluation, report, CI gate.
7. Shortlist, Hermes delivery, Claude Code skill.
8. README and demo.

Two things are left for later: marking by Telegram reply, and growing the set to 60 cases.

## 11. Risks

- Non-interactive use of a subscription may change in limits or terms. The judge sits behind an interface, so another backend can be added.
- A small evaluation set gives a noisy number. The held-out split and the stated sample sizes limit over-claiming.
- Feed formats change. The adapters are small and tested against saved samples.
- The search source depends on an actor published by a third party. It can change its output, change its price or disappear. The actor name is a setting and its output is mapped in one function.
- Reading LinkedIn job pages through a scraping service is outside LinkedIn's terms of use. No account is used, and the source can be left out by not configuring a search.
- Duplicates are matched on company name and title only. A different spelling in the two sources is missed, and the same title in two places can be linked to the wrong copy.
- Replacing a company name can miss a mention inside the text. The local check reduces this and cannot remove it.
- A scheduled run with no interactive session open is untested. The fallback is macOS launchd piping to `hermes send`, or running the daily command by hand.
- The evaluation cases republish job-advert text. Cases keep only the text needed for judging.
