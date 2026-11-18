# Job Ranker: technical design

Status: approved on 2026-11-18.

## 1. What it does

A command-line program that collects new job postings from public company job feeds, drops the ones that cannot fit a profile, has Claude judge the rest, and sends a short list to Telegram. It measures its ranking against a set of hand-marked postings, and CI fails when that measurement drops.

## 2. Scope

In scope

- Collect postings from public job feeds for a configured list of companies.
- Drop postings that cannot fit, using fixed rules, with a reason for each drop.
- Have Claude judge the rest: yes or no, with reasons.
- Send a short list of new yes postings to Telegram through a Hermes agent.
- Measure agreement with hand-made marks, publish a report, and fail CI when quality drops.

Out of scope

- Writing or tailoring CVs and cover letters.
- Filling in or submitting applications.
- A web interface.
- Learning automatically from the marks. They are used only to measure.

Never

- Logging in to LinkedIn, Indeed, Xing or any personal account, or automating a logged-in browser.
- Committing a profile, a company list, or marks tied to a named employer.

## 3. Constraints

- No API key. Model calls go through Claude Code's non-interactive mode on a logged-in subscription.
- The repository is public, so private data is kept out of it.
- Python 3.12 or newer.

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

Each feed type has its own adapter. All three feeds are public and need no login: Greenhouse (`GET boards-api.greenhouse.io/v1/boards/{token}/jobs`), Lever and Ashby (public posting endpoints). Companies are listed in `config/companies.yaml` with their feed type and token. A failing feed is logged and skipped, and the run continues.

### Posting record

Each posting is stored with its source, company, title, location, remote flag, URL, description as plain text, first-seen time and a content hash. A posting is new when its source ID has not been seen before. A changed hash is recorded, and the posting is not sent again.

### Storage

One SQLite file, `data/ranker.db`, holds postings, rule results, verdicts and run logs. It is not committed.

### Profile

`profile.yaml` is not committed. `config/profile.example.yaml` is a fictional example. The fields are target roles, skills, years of experience, countries and remote preference, languages with levels, seniority range, things to avoid, and free-text notes for the judge.

### Rules

The rules are pure functions over a posting and the profile. They check for a country or remote mismatch, a required language the profile lacks, seniority in the title outside the range, and a match on the avoid list. Each rule returns pass or a reason code. No model is involved, so the same input always gives the same output.

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
config/          companies.example.yaml, profile.example.yaml
integrations/    hermes/, claude-code/
docs/            specs/, decisions/
.github/workflows/ci.yml
```

Stack: Python 3.12 or newer, uv for environments, ruff, a type checker, pytest, httpx, pydantic, typer, and SQLite from the standard library.

## 9. Process

- One short spec per milestone in `docs/specs/`: problem, non-goals, acceptance criteria.
- Decision records in `docs/decisions/`, written as ADRs (architecture decision records) when the choice is made.
- Tests are written first. Each milestone is one pull request with a description.
- CI runs lint, a type check, the tests, and the evaluation replay with its threshold and staleness check.

## 10. Milestones

0. Repository, tooling, CI skeleton, decision record 1.
1. Sources and storage.
2. Rules.
3. Judge with recording.
4. Marking command and the first 30 cases.
5. Evaluation, report, CI gate.
6. Shortlist, Hermes delivery, Claude Code skill.
7. README and demo.

Two things are left for later: marking by Telegram reply, and growing the set to 60 cases.

## 11. Risks

- Non-interactive use of a subscription may change in limits or terms. The judge sits behind an interface, so another backend can be added.
- A small evaluation set gives a noisy number. The held-out split and the stated sample sizes limit over-claiming.
- Feed formats change. The adapters are small and tested against saved samples.
- Replacing a company name can miss a mention inside the text. The local check reduces this and cannot remove it.
- A scheduled run with no interactive session open is untested. The fallback is macOS launchd piping to `hermes send`, or running the daily command by hand.
- The evaluation cases republish job-advert text. Cases keep only the text needed for judging.
