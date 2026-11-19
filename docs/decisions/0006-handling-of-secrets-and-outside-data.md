# Keep the token out of output and treat outside data as untrusted

Status: accepted
Date: 2026-11-19

## Context

The program holds one secret, the Apify token. It reads text written by third parties: job postings from the feeds and from the search source, and the answers of the services it calls. It prints a summary line for each source and stores a reason for each failure in the run log. A token or a piece of outside text can reach the terminal, the database or a request address through any of these paths.

## Decision

* The token is sent in the `Authorization` header and is never part of a request address.
* A failure is reported with a fixed reason: the status code, `timeout`, `connection error`, `not JSON`, `unexpected shape`, or the class name of an unexpected error. The response body, the headers and the text of the exception are never printed or stored.
* Tracebacks do not show local variables.
* Every SQL statement passes its values as parameters. No value from a posting or a configuration file is written into SQL text.
* Redirects are not followed. An answer that is not a success status is reported as an error with its status code.
* A board token from the company list is one part of an address. A token with white space, `/`, `?` or `#` is rejected when the list is loaded.
* Configuration files are read with the safe YAML loader.

## Consequences

* A failure message can be copied into a bug report without a check for secrets.
* A reason is short, so the cause of an unusual failure can need a second look with other tools.
* A board that moved to a new address fails with its redirect status until the company list is corrected.
* Tests assert that the token does not appear in any output, in the run log or in the database.
