"""Decisions in the dashboard and the checks that guard them. Every posting here is made up."""

import asyncio
import re
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_web_pages import NOW, PORT, PROFILE, add, counts, decide, posting, site, titles

from jobranker.store import Decision, Store
from jobranker.web.app import create_app

OWN = f"http://127.0.0.1:{PORT}"
SAFETY_HEADERS = {
    "content-security-policy": (
        "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "cache-control": "no-store",
}


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "ranker.db"
    Store(path).close()
    add(path, posting(1, title="Old Role"), seen=NOW - timedelta(days=3))
    add(path, posting(2, title="New Role"), seen=NOW - timedelta(days=1))
    return path


def token_of(client: TestClient, path: str = "/") -> str:
    found: set[str] = set(re.findall(r'name="token" value="([^"]+)"', client.get(path).text))
    assert len(found) == 1
    return found.pop()


def row_id(db: Path, number: int) -> int:
    with Store(db) as store:
        stored = store.get("greenhouse", "northwindrobotics", str(number))
        assert stored is not None
        return stored.id


def decisions(db: Path) -> list[tuple[str, Decision]]:
    with Store(db) as store:
        return [
            (stored.posting.title, decision)
            for decision in Decision
            for stored, _ in store.decided_groups(decision)
        ]


def send(
    client: TestClient, path: str, headers: dict[str, str] | None = None, /, **fields: str
) -> httpx.Response:
    response: httpx.Response = client.post(
        path, data=fields, headers=headers, follow_redirects=False
    )
    return response


def test_each_review_card_has_both_decisions_and_the_token(db: Path) -> None:
    html = site(db).get("/").text
    assert len(re.findall(r'<form class="decision" method="post" action="/decide">', html)) == 2
    assert (
        len(re.findall(r'<button[^>]*name="decision" value="applied"[^>]*>\s*Applied', html)) == 2
    )
    assert (
        len(re.findall(r'<button[^>]*name="decision" value="dismissed"[^>]*>\s*Not for me', html))
        == 2
    )
    assert len(re.findall(r'name="token" value="[^"]{43,}"', html)) == 2
    assert "Undo" not in html


def test_token_is_only_in_form_fields(db: Path) -> None:
    client = site(db)
    token = token_of(client)
    html = client.get("/").text
    assert html.count(token) == html.count(f'name="token" value="{token}"')
    assert token not in client.get("/runs").text


def test_applied_moves_a_group_to_its_tab(db: Path) -> None:
    client = site(db)
    response = send(
        client, "/decide", posting=str(row_id(db, 1)), decision="applied", token=token_of(client)
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert decisions(db) == [("Old Role", Decision.APPLIED)]
    html = client.get("/").text
    assert titles(html) == ["New Role"]
    assert counts(html) == {"/": 1, "/applied": 1, "/dismissed": 0, "/runs": 0}
    assert titles(client.get("/applied").text) == ["Old Role"]


def test_not_for_me_moves_a_group_to_its_tab(db: Path) -> None:
    client = site(db)
    response = send(
        client, "/decide", posting=str(row_id(db, 2)), decision="dismissed", token=token_of(client)
    )
    assert response.status_code == 303
    assert decisions(db) == [("New Role", Decision.DISMISSED)]
    assert counts(client.get("/").text) == {"/": 1, "/applied": 0, "/dismissed": 1, "/runs": 0}
    assert titles(client.get("/dismissed").text) == ["New Role"]


@pytest.mark.parametrize(
    ("decision", "tab"), [(Decision.APPLIED, "applied"), (Decision.DISMISSED, "dismissed")]
)
def test_undo_brings_a_group_back_to_review(db: Path, decision: Decision, tab: str) -> None:
    decide(db, posting(1), decision)
    client = site(db)
    html = client.get(f"/{tab}").text
    assert re.search(r'<form class="decision" method="post" action="/undo">', html)
    assert re.search(r"<button[^>]*>\s*Undo", html)
    assert 'name="decision"' not in html
    response = send(
        client, "/undo", posting=str(row_id(db, 1)), token=token_of(client, f"/{tab}"), tab=tab
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/{tab}"
    assert decisions(db) == []
    assert titles(client.get("/").text) == ["New Role", "Old Role"]


def test_second_decision_replaces_the_first(db: Path) -> None:
    client = site(db)
    token = token_of(client)
    send(client, "/decide", posting=str(row_id(db, 1)), decision="applied", token=token)
    send(client, "/decide", posting=str(row_id(db, 1)), decision="dismissed", token=token)
    assert decisions(db) == [("Old Role", Decision.DISMISSED)]


def test_decision_counts_for_the_linked_group(db: Path) -> None:
    add(db, posting(900, source="linkedin", board="", title="Old Role"))
    client = site(db)
    assert titles(client.get("/").text) == ["New Role", "Old Role"]
    with Store(db) as store:
        copy = store.get("linkedin", "", "900")
    assert copy is not None and copy.duplicate_of == row_id(db, 1)
    send(client, "/decide", posting=str(copy.id), decision="applied", token=token_of(client))
    assert titles(client.get("/").text) == ["New Role"]
    assert titles(client.get("/applied").text) == ["Old Role"]
    send(client, "/undo", posting=str(row_id(db, 1)), token=token_of(client), tab="applied")
    assert decisions(db) == []


@pytest.mark.parametrize(
    ("fields", "status"),
    [
        ({"posting": "999", "decision": "applied"}, 404),
        ({"posting": "abc", "decision": "applied"}, 400),
        ({"posting": "", "decision": "applied"}, 400),
        ({"posting": "1.0", "decision": "applied"}, 400),
        ({"posting": "-1", "decision": "applied"}, 400),
        ({"posting": "9" * 40, "decision": "applied"}, 400),
        ({"posting": "٣", "decision": "applied"}, 400),
        ({"decision": "applied"}, 400),
        ({"posting": "1", "decision": "hired"}, 400),
        ({"posting": "1", "decision": "APPLIED"}, 400),
        ({"posting": "1", "decision": ""}, 400),
        ({"posting": "1"}, 400),
    ],
)
def test_unknown_posting_or_decision_stores_nothing(
    db: Path, fields: dict[str, str], status: int
) -> None:
    client = site(db)
    response = send(client, "/decide", token=token_of(client), **fields)
    assert response.status_code == status
    assert decisions(db) == []
    for name, value in SAFETY_HEADERS.items():
        assert response.headers[name] == value


@pytest.mark.parametrize(
    ("fields", "status"), [({"posting": "999"}, 303), ({"posting": "abc"}, 400), ({}, 400)]
)
def test_undo_of_an_unknown_posting_changes_nothing(
    db: Path, fields: dict[str, str], status: int
) -> None:
    decide(db, posting(1), Decision.APPLIED)
    client = site(db)
    response = send(client, "/undo", token=token_of(client), **fields)
    assert response.status_code == status
    assert decisions(db) == [("Old Role", Decision.APPLIED)]


@pytest.mark.parametrize("path", ["/decide", "/undo"])
@pytest.mark.parametrize("token", [None, "", "wrong", "x" * 43, "tökén", "\x00"])
def test_request_without_the_right_token_is_refused(db: Path, path: str, token: str | None) -> None:
    decide(db, posting(2), Decision.DISMISSED)
    client = site(db)
    real = token_of(client)
    fields = {"posting": str(row_id(db, 1)), "decision": "applied", "tab": "review"}
    if token is not None:
        fields["token"] = token
    response = send(client, path, **fields)
    assert response.status_code == 403
    assert decisions(db) == [("New Role", Decision.DISMISSED)]
    for name, value in SAFETY_HEADERS.items():
        assert response.headers[name] == value
    assert real not in response.text
    # A token almost like the real one is refused as well.
    assert send(client, path, **(fields | {"token": real[:-1]})).status_code == 403
    assert send(client, path, **(fields | {"token": real + "a"})).status_code == 403


def test_token_of_one_start_is_refused_after_a_restart(db: Path) -> None:
    first, second = site(db), site(db)
    old, new = token_of(first), token_of(second)
    assert old != new
    fields = {"posting": str(row_id(db, 1)), "decision": "applied"}
    assert send(second, "/decide", token=old, **fields).status_code == 403
    assert decisions(db) == []
    assert send(second, "/decide", token=new, **fields).status_code == 303


def test_token_in_the_address_does_not_count(db: Path) -> None:
    client = site(db)
    token = token_of(client)
    response = client.post(
        f"/decide?token={token}",
        data={"posting": str(row_id(db, 1)), "decision": "applied"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert decisions(db) == []


@pytest.mark.parametrize(
    "origin",
    [
        "http://evil.test",
        "https://evil.test",
        "null",
        "",
        f"https://127.0.0.1:{PORT}",
        "http://127.0.0.1:9999",
        "http://127.0.0.1",
        f"http://127.0.0.1:{PORT}.evil.test",
        f"http://evil.test:{PORT}",
        f"http://127.0.0.1:{PORT}/",
    ],
)
@pytest.mark.parametrize("path", ["/decide", "/undo"])
def test_request_from_another_origin_is_refused(db: Path, path: str, origin: str) -> None:
    decide(db, posting(2), Decision.DISMISSED)
    client = site(db)
    response = send(
        client,
        path,
        {"Origin": origin},
        posting=str(row_id(db, 2 if path == "/undo" else 1)),
        decision="applied",
        token=token_of(client),
        tab="dismissed",
    )
    assert response.status_code == 403
    assert decisions(db) == [("New Role", Decision.DISMISSED)]
    for name, value in SAFETY_HEADERS.items():
        assert response.headers[name] == value


@pytest.mark.parametrize("origin", [OWN, f"http://localhost:{PORT}", None])
def test_request_from_the_application_itself_is_accepted(db: Path, origin: str | None) -> None:
    client = site(db)
    headers = {} if origin is None else {"Origin": origin}
    response = send(
        client,
        "/decide",
        headers,
        posting=str(row_id(db, 1)),
        decision="applied",
        token=token_of(client),
    )
    assert response.status_code == 303
    assert decisions(db) == [("Old Role", Decision.APPLIED)]


FOREIGN_HOSTS = [
    "evil.test",
    f"evil.test:{PORT}",
    "127.0.0.1",
    "localhost",
    "127.0.0.1:9999",
    f"localhost.evil.test:{PORT}",
    f"127.0.0.1:{PORT}.evil.test",
    f"127.0.0.1.evil.test:{PORT}",
    f"user@127.0.0.1:{PORT}",
    f"0.0.0.0:{PORT}",
    f"[::1]:{PORT}",
    f"127.0.0.1:0{PORT}",
]


@pytest.mark.parametrize("host", FOREIGN_HOSTS)
@pytest.mark.parametrize("path", ["/", "/applied", "/runs", "/static/dashboard.css", "/nothing"])
def test_request_with_a_foreign_host_is_refused(db: Path, path: str, host: str) -> None:
    response = site(db).get(path, headers={"Host": host})
    assert response.status_code == 400
    assert "Role" not in response.text and "token" not in response.text
    for name, value in SAFETY_HEADERS.items():
        assert response.headers[name] == value


@pytest.mark.parametrize("host", FOREIGN_HOSTS)
def test_decision_with_a_foreign_host_stores_nothing(db: Path, host: str) -> None:
    client = site(db)
    response = send(
        client,
        "/decide",
        {"Host": host},
        posting=str(row_id(db, 1)),
        decision="applied",
        token=token_of(client),
    )
    assert response.status_code == 400
    assert decisions(db) == []


@pytest.mark.parametrize(
    "host", [f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"LOCALHOST:{PORT}", f"LocalHost:{PORT}"]
)
def test_own_host_names_are_accepted(db: Path, host: str) -> None:
    assert site(db).get("/", headers={"Host": host}).status_code == 200


def test_host_check_follows_the_port_of_the_application(db: Path) -> None:
    app = create_app(db, PROFILE, port=9001, now=lambda: NOW)
    assert TestClient(app, base_url="http://127.0.0.1:9001").get("/").status_code == 200
    assert TestClient(app, base_url=OWN).get("/").status_code == 400


def test_request_without_a_host_is_refused(db: Path) -> None:
    app = create_app(db, PROFILE, port=PORT, now=lambda: NOW)
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def keep(message: dict[str, object]) -> None:
        sent.append(message)

    def scope(headers: list[tuple[bytes, bytes]]) -> dict[str, object]:
        return {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", PORT),
        }

    own = f"127.0.0.1:{PORT}".encode()
    for headers in ([], [(b"host", own), (b"host", b"evil.test")], [(b"host", b"\xff\xfe")]):
        sent.clear()
        asyncio.run(app(scope(headers), receive, keep))  # type: ignore[arg-type]
        assert sent[0]["status"] == 400


@pytest.mark.parametrize(
    ("fields", "target"),
    [
        ({}, "/"),
        ({"tab": "review"}, "/"),
        ({"tab": "applied"}, "/applied"),
        ({"tab": "dismissed"}, "/dismissed"),
        ({"tab": "runs"}, "/"),
        ({"tab": "https://evil.test/"}, "/"),
        ({"tab": "//evil.test"}, "/"),
        ({"tab": "/\\evil.test"}, "/"),
        (
            {"next": "https://evil.test/", "url": "//evil.test", "redirect": "https://evil.test"},
            "/",
        ),
        (
            {"tab": "review", "entry": "1", "q": "junior role", "page": "2"},
            "/?entry=1&q=junior+role&page=2",
        ),
        ({"tab": "review", "entry": "yes", "q": "  ", "page": "abc"}, "/"),
        ({"tab": "applied", "entry": "1", "q": "x", "page": "3"}, "/applied"),
        (
            {"tab": "review", "q": "https://evil.test/?a=b&c=d#e"},
            "/?q=https%3A%2F%2Fevil.test%2F%3Fa%3Db%26c%3Dd%23e",
        ),
        (
            {"tab": "review", "q": "a\r\nLocation: https://evil.test"},
            "/?q=a+Location%3A+https%3A%2F%2Fevil.test",
        ),
        ({"tab": "review", "page": "-5"}, "/"),
    ],
)
def test_redirect_is_rebuilt_from_checked_values(
    db: Path, fields: dict[str, str], target: str
) -> None:
    client = site(db)
    response = send(
        client,
        "/decide",
        posting=str(row_id(db, 1)),
        decision="applied",
        token=token_of(client),
        **fields,
    )
    assert response.status_code == 303
    assert response.headers["location"] == target


def test_review_forms_carry_the_view_so_a_decision_returns_to_it(db: Path) -> None:
    html = site(db).get("/?entry=1&q=role").text
    assert titles(html) == []
    add(db, posting(3, title="Junior Role"))
    html = site(db).get("/?entry=1&q=role").text
    for field in ('name="tab" value="review"', 'name="entry" value="1"', 'name="q" value="role"'):
        assert field in html
    assert 'name="page" value="1"' in html


def responses(db: Path) -> list[httpx.Response]:
    client = site(db)
    token = token_of(client)
    row = str(row_id(db, 1))
    return [
        client.get("/"),
        client.get("/applied"),
        client.get("/dismissed"),
        client.get("/runs"),
        client.get("/static/dashboard.css"),
        client.get("/static/dashboard.js"),
        client.get("/static/icon.svg"),
        client.get("/static/fonts/instrument-sans.woff2"),
        client.get("/static/missing.css"),
        client.get("/nothing"),
        client.head("/"),
        client.put("/"),
        client.delete("/decide"),
        client.get(f"/decide?posting={row}&decision=applied&token={token}"),
        client.post("/", data={"token": token}),
        send(client, "/decide", posting=row, decision="applied", token=token),
        send(client, "/undo", posting=row, token=token, tab="applied"),
        send(client, "/decide", posting=row, decision="applied"),
        send(client, "/decide", posting="999", decision="applied", token=token),
        client.get("/", headers={"Host": "evil.test"}),
        send(client, "/decide", {"Origin": "http://evil.test"}, token=token),
    ]


def test_every_answer_carries_the_safety_headers(db: Path) -> None:
    answers = responses(db)
    assert {r.status_code for r in answers} == {200, 303, 400, 403, 404, 405}
    for response in answers:
        for name, value in SAFETY_HEADERS.items():
            assert response.headers.get_list(name) == [value], (response.request.url, name)


def test_only_a_post_can_change_a_decision(db: Path) -> None:
    client = site(db)
    token = token_of(client)
    row = row_id(db, 1)
    for method in ("GET", "HEAD", "PUT", "PATCH", "DELETE"):
        for path in ("/decide", "/undo"):
            response = client.request(
                method, f"{path}?posting={row}&decision=applied&token={token}"
            )
            assert response.status_code == 405
    assert decisions(db) == []


def test_failure_inside_the_application_keeps_the_headers_and_shows_no_detail(
    db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: Store, profile_hash: str, rules_version: int) -> list[object]:
        raise RuntimeError("secret detail /private/path")

    monkeypatch.setattr(Store, "review_groups", broken)
    app = create_app(db, PROFILE, port=PORT, now=lambda: NOW)
    client = TestClient(app, base_url=OWN, raise_server_exceptions=False)
    response = client.get("/")
    assert response.status_code == 500
    assert "secret detail" not in response.text and "Traceback" not in response.text
    for name, value in SAFETY_HEADERS.items():
        assert response.headers[name] == value


def test_page_loads_the_script_from_the_package(db: Path) -> None:
    client = site(db)
    assert '<script src="/static/dashboard.js" defer></script>' in client.get("/").text
    response = client.get("/static/dashboard.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    script = response.text
    for forbidden in ("http:", "https:", "//evil", "eval(", "innerHTML", "document.write"):
        assert forbidden not in script


def test_application_has_no_cross_origin_sharing(db: Path) -> None:
    response = site(db).options("/decide", headers={"Origin": "http://evil.test"})
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-origin" not in site(db).get("/", headers={"Origin": OWN}).headers
