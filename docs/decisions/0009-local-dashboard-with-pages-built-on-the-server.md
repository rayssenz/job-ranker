# The dashboard is a local web application whose pages are built on the server

Status: accepted
Date: 2026-11-19

## Context

The postings that passed the rules could only be read as a text list in a terminal, and there was no place to note that an application was sent. A page in the browser can show them as cards and record a decision per posting. The page shows text that third parties wrote, and it changes stored data, so a page on another site must not be able to read it or to act through it.

## Decision

* `jobrank dashboard` starts a FastAPI application, served by Uvicorn, and opens it in the browser.
* The pages are Jinja2 templates built on the server, with escaping on for every template. A decision is a plain form that posts and is followed by a redirect. A short script spares the reload, and the page works without it.
* The command binds the socket itself, to `127.0.0.1` only, and hands it to the server.
* A request is served only when its `Host` is `127.0.0.1` or `localhost` with the port of this start.
* A request that changes data is a `POST` with a token that is made new at each start, kept in memory and placed in the forms. A request with a foreign `Origin` is refused.
* Every answer carries a content security policy that allows only the application's own files, and headers that forbid framing, type guessing and caching. The referrer is sent inside the application only, because a browser marks a plain form as coming from nowhere when no referrer is allowed at all, and the origin check would then refuse the application's own forms.
* Styles, the script and both typefaces are files of the package. The page loads nothing from another machine.
* A decision is stored per posting and counts for the whole group of linked postings.

## Consequences

* Four dependencies are added: `fastapi`, `uvicorn`, `jinja2` and `python-multipart`.
* The dashboard exists only while the command runs, for one person on one machine. There is no login.
* A page that was open before a restart holds an old token. Its buttons are refused until the page is reloaded.
* No JavaScript build is needed, and the pages are tested as text.
* The typefaces are stored in the repository with their licence texts.
* The later marking milestone can read the stored decisions.
