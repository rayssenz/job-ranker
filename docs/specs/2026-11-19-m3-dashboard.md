# Milestone 3: local dashboard

Status: approved on 2026-11-19

## Problem

After milestone 2 the postings that passed the rules can only be read as a text list in a terminal. The list does not get shorter: a posting that was read yesterday is printed again today, and there is no place to note that an application was sent.

## What this milestone adds

- `jobrank dashboard` starts a small web application on the local machine and opens it in the browser.
- The page shows the postings that passed the rules as cards, newest first.
- Each card has two decisions, "Applied" and "Not for me". A decided posting leaves the review list and moves to its own tab.
- A fourth tab shows how the last runs went.

Nothing is hosted. The application answers only on the local machine and makes no request to any other machine.

## What the person sees

Four tabs. The first three show their count. The runs tab shows only the last runs, so it has none:

| Tab | Shows |
|---|---|
| To review | Groups that passed the rules and have no decision, newest first |
| Applied | Groups marked as applied, with the date of the mark, newest mark first |
| Not for me | Groups that were dismissed |
| Runs | The last ten runs, and the sources that were not collected in the latest one |

A card shows:

- the title, the company, the location, the source and how long ago the posting was first seen
- the first 280 characters of the description, cut at a word, with the rest behind "Show full text"
- on the review tab: "Applied", "Not for me" and "Open posting"
- on the other two tabs: "Undo" and "Open posting", and on the applied tab a stamp with the date
- a marked edge when the posting was first seen in the last 24 hours

Above the cards on the review tab:

- a heading with the number of groups to review, and one line on the latest run
- a switch "Student and junior only", which keeps the titles that hold a word from `levels.accept` of the profile
- a search field that keeps the cards whose title, company or location holds the text

The switch and the search are part of the address, so a filtered view can be reloaded. Fifty cards are shown per page, with a link to the next page.

An empty tab says what to do next: collect postings, or that everything is reviewed.

## Look

One column of cards on a cool white page. Ink blue for headings, links and the primary button. Red only for the applied stamp and for a failed source. Two typefaces, Bricolage Grotesque for headings and Instrument Sans for text, stored in the package so the page needs no network. The layout works on a narrow window. Keyboard focus is visible and the buttons work without JavaScript.

## Commands

`jobrank dashboard` loads the profile, applies the rules to every posting without a current result, starts the application and opens the browser. It stops with Ctrl+C. Postings that are collected while it runs get their rule results at the next page request, so a reload shows them.

| Option | Default | Meaning |
|---|---|---|
| `--profile` | `profile.yaml` | the private profile |
| `--db` | `data/ranker.db` | the database |
| `--port` | `8765` | the local port, 1024 or higher |
| `--no-open` | off | do not open the browser |

A missing profile or database stops the command with a short message, as in milestone 2. A port that is in use stops it with a message that names `--port`.

## Decisions

A decision belongs to a group of linked postings. It is stored with the posting that was shown and counts for the whole group, also when another posting of the group is shown later. "Undo" removes the decisions of the whole group. A posting keeps its decision when its text changes.

The applied and dismissed tabs list every group with a decision, whether or not it still passes the rules. A change of the profile must not remove an application from the list.

A decision does not change the rule results, and it is not yet used to measure anything. The marking milestone reads these decisions later.

## Storage

The schema version rises from 2 to 3. A new table `decisions` holds, per posting: the decision (`applied` or `dismissed`) and the time. A version 2 database is upgraded in place, as described in decision record 0008.

## Safety

The application shows text that third parties wrote, and it can change stored data, so:

- It listens on `127.0.0.1` only. A request whose `Host` is not `127.0.0.1` or `localhost` with the right port is refused.
- Every text from a posting is escaped when the page is built. A description is never treated as HTML.
- A posting link is shown as a link only when its address starts with `http://` or `https://`. It opens in a new tab without a referrer.
- A request that changes data must be a `POST` with a token that is made new at each start and placed in every form. A request without it, or from another origin, is refused.
- Every answer carries a content security policy that allows only the application's own files, and headers that forbid framing and type guessing.
- The automatic API pages of the framework are switched off.
- The page loads no file from another machine: no fonts, scripts or images.

## What is private

The page shows the private postings and decisions, and exists only while the command runs. The repository holds the application, its styles and fonts, and tests with made-up postings.

## Non-goals

- Starting a collection run from the page. A run can cost money and stays a command.
- Editing the profile or the search list in the page.
- Showing why the rules dropped a posting.
- Showing which search found a posting. The database does not record it yet.
- A dark colour scheme.
- Use by more than one person, or from another machine.

## Approaches

1. **FastAPI with pages built on the server (chosen).** FastAPI, Jinja2 templates with escaping on by default, Uvicorn as the server. Decisions are plain forms, so the page works without JavaScript, and a short script only spares the reload. The owner chose a web framework over the standard library for a page that will grow with the later milestones.
2. **The standard library server.** No new dependency, but routing, forms, escaping and headers would be written by hand.
3. **A JavaScript application with its own build.** The same result in the browser, with a second toolchain to install, test and keep current.

## Acceptance criteria

1. The review tab lists the groups that passed the rules and have no decision, newest first, fifty per page, and its count matches.
2. "Applied" and "Not for me" move a group to its tab and lower the review count. "Undo" brings it back.
3. A decision on one posting of a linked group counts for the group, which is shown once. A group with a decision stays in its tab when it no longer passes the rules.
4. The switch keeps only titles with a word from `levels.accept`. The search keeps only matching cards. Both survive a reload and can be combined.
5. A description is cut at a word within 280 characters, and the full text is available.
6. A posting whose title, company or description holds HTML or a script is shown as text and runs nothing.
7. A posting link with any scheme other than `http` or `https` is not shown as a link.
8. A `POST` without the token, with a wrong token, or with another origin is refused and changes nothing.
9. A request with a foreign `Host` is refused.
10. Every answer carries the content security policy and the other safety headers, and the pages name no other machine.
11. The runs tab shows the last ten runs with their counts and the sources that were not collected in the latest run.
12. A version 2 database is upgraded to version 3 and keeps every row.
13. `jobrank dashboard` applies the rules before it serves, listens on `127.0.0.1`, and stops with a short message when the profile or the database is missing or the port is taken.
14. An empty tab shows a sentence that says what to do next.
15. The token of one start is not accepted after a restart.

## Changes to the technical design

- Section 3: the dashboard dependencies are listed.
- Section 5: a "Dashboard" part describes the tabs, the decisions and the safety rules.

## Decision records

- 0009: the dashboard is a local web application whose pages are built on the server.

## Dependencies added

`fastapi`, `uvicorn`, `jinja2` and `python-multipart` for form data.
