# Progress display for `jobrank collect`

Status: approved on 2026-11-19

## Problem

`jobrank collect` prints nothing until every source is finished. A run with many companies and several searches takes minutes, and one search can be silent for up to five minutes. A person watching the terminal cannot tell a working run from a stuck one.

## Goal

While the command runs, the terminal shows which sources are finished, how many are left, and which one is being collected now.

## What the person sees

In a terminal:

```
greenhouse Northwind Robotics: fetched 3, new 3, changed 0, duplicate 0
lever      Bluefjord Labs: fetched 3, new 3, changed 0, duplicate 0
Collecting ━━━━━━━━━━━━━╸━━━━━━━  2/5  0:00:41
⠹ linkedin   machine learning engineer / Lisbon  0:00:38
```

* The line of a source is printed as soon as that source is finished. Its text is the same as today.
* A bar stays at the bottom with the number of finished sources, the total, and the time since the start.
* Under the bar, a spinner names the source that is being collected and how long it has taken.
* When the run ends, the bar and the spinner disappear and one summary line is printed, for example `Done in 4:12: 5 sources, 1 not collected, 9 new postings.` A source is not collected when it failed or was skipped.

When the output is not a terminal (a file, a pipe, a scheduled job): no bar and no spinner. Each line is still printed as soon as its source is finished, followed by the summary line.

## Rules

* The display shows the same names as the summary lines: the company name, or the search words and place. It never shows the token, an address or posting text.
* A search that is skipped (no token, run limit reached) counts as a finished source.
* The exit codes do not change.
* Stopping the run with Ctrl+C leaves the terminal usable: no leftover bar and the cursor is visible.
* `--quiet` turns the bar and the spinner off in a terminal.

## Non-goals

* Progress inside one source. A feed is one request, and a search does not report how far it is.
* Colours or styles that can be configured.
* Collecting several sources at the same time.

## Approaches

1. **Callbacks from the collection run, display in the command (chosen).** `collect` accepts two optional callbacks, one called when a source starts and one when it finishes. The command builds the display with Rich, which is already installed as part of Typer, and passes the callbacks. The collection code stays free of terminal code and its tests need no terminal.
2. **`collect` yields each report as it is ready.** Smaller change, but the caller only learns about a source after it is finished, so the display cannot name the source that is running now. That is the long silent part the display is for.
3. **A hand-written spinner on a background thread.** No use of Rich, more code to maintain, and the cases Rich already handles (output that is not a terminal, Ctrl+C, narrow windows) have to be solved again.

## Acceptance criteria

1. With output that is not a terminal, the line of each source is written before the next source is started, and the output holds no bar, no spinner and no control characters.
2. With a terminal, the output holds the bar with the finished and total counts and the name of the running source.
3. The lines of the sources have the same text as before this change.
4. The last line is the summary with the number of sources, the number that were not collected and the number of new postings.
5. The token does not appear in any output, with or without a terminal.
6. `--quiet` in a terminal gives the same output as output that is not a terminal.
7. `collect` works unchanged when no callbacks are passed.

## Delivery

Part of milestone 1, in the same branch and pull request, because it changes only the `collect` command that this milestone adds. No new dependency: Rich is declared as a direct dependency because the code now imports it.
