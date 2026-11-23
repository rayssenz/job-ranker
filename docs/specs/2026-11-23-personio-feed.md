# Personio feed

Status: approved on 2026-11-23.

## Problem

The company feeds read three hiring systems: Greenhouse, Lever and Ashby. Many small and mid-sized companies in Germany publish their open roles through Personio instead, so their postings never reach the tool. Personio publishes every company's open roles as a public feed, without a login or a key, in the same way as the three systems already supported.

## What is added

- A fourth company feed type, `personio`, next to `greenhouse`, `lever` and `ashby`.
- An entry in the company list with `feed: personio` and, as `token`, the company's Personio name: the first part of its job page address `{token}.jobs.personio.de`.

Nothing else changes. The postings from the new feed go through the same store, rules, judge and dashboard as the others.

## The feed

Checked with live requests on 2026-11-23.

| Item | Value |
| --- | --- |
| Request | `GET https://{token}.jobs.personio.de/xml?language={de or en}` |
| Answer | XML, root element `workzag-jobs`, one `position` element per open role |
| Unknown company | status 404 |
| Login or key | none |

Notes:

- **Language.** Personio holds each role's description in the language the company wrote it in. Asked for the other language, the feed returns the same roles with the description almost empty, while the title and the place stay the same. The adapter therefore makes two requests per company, one for `de` and one for `en`, and keeps for each role the longer description. If one of the two requests fails, the other is used alone. If both fail, the source fails as the other feeds do.
- **Job address.** The feed holds no address for a role. The address is built as `https://{token}.jobs.personio.de/job/{id}`. A live check on 2026-11-23 showed that this address opens the role's page.
- **Remote.** The feed has no field for remote work. Some companies write it into the office name, for example `Remote` or `Remote, Portugal`. A role is marked remote when its office name contains the word "remote", and unknown otherwise.
- **Safe reading.** The answer is read with Python's own XML reader. An answer that declares a document type or entities is refused as a failed source, so a feed cannot make the reader load outside files or expand text without limit. No new package is needed.
- **Description.** Each `jobDescription` has a heading (`name`) and an HTML text (`value`). They are joined in order as heading and text, and the HTML is turned into text by the same code the Greenhouse feed already uses.

### Field mapping

| Record field | Personio |
| --- | --- |
| posting ID | `id` |
| company | from the company list |
| title | `name` |
| location | `office`, then every `additionalOffices/office`, each named once |
| remote | yes when an office name contains "remote", unknown otherwise |
| URL | built from the token and the ID, see above |
| description | every `jobDescription`, heading and text, from the longer language version |

A role with no ID or no title is skipped and counted as skipped, as in the other feeds.

## Decisions by the owner

1. **Two requests per company.** The language check above needs two requests per Personio company per run. Feeds cost nothing. Decided: two requests.
2. **Personio's own level field.** Personio also states a level (`seniority`, for example `student` or `entry-level`) and a contract type (`employmentType`, for example `intern`). The rules read only the title today. Decided: these fields are left out in this step and the rules stay as they are.
3. **Place in the plan.** This step is small and changes no existing behaviour. Decided: it is built now, before milestone 5.

## Non-goals

- Other hiring systems (SmartRecruiters, Workday, JOIN and others).
- Using Personio's level or contract fields in the rules (see question 2).
- Finding a company's Personio name automatically. It is written into the company list by hand.

## Acceptance criteria

1. A company list entry with `feed: personio` is accepted. `region` with a Personio entry is refused, as with Greenhouse and Ashby.
2. With a saved sample feed of made-up roles, `jobrank collect` stores every role with the ID, title, places, remote mark, built address and joined description described above.
3. When the German and the English answer differ, each role keeps the longer description. When one of the two requests fails, the roles still come from the other.
4. A Personio name that does not exist (404) is a failed source with that reason in the run log, and the other companies are still collected.
5. An answer that declares a document type or entities is refused and stores nothing.
6. A role without an ID or title is skipped and counted.
7. Tests use only saved samples with made-up companies and call no live feed.

## Changes to the technical design

- Section 5, Sources: the company feeds list Personio as a fourth type.

## Decision records

- None. The feed follows decision 0003 (public feeds and one search source).
