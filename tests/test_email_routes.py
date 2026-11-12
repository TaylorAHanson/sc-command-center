"""Tests for POST /api/email/send and /preview (routes/email.py).

Driven through FastAPI's in-process client with the real auth dependency, so a
request without a signed-in user is shown to be refused before anything runs.
The caller's identity is faked at `access.caller`, SES at `_ses_client`, and the
database is a fake connection. Pinned here:

- signed-in users only;
- the sender is the caller's identity, whatever the body claims;
- refusals, the daily cap and "not set up" come back as 400 / 429 / 503 with a
  sentence for the person;
- a view link from another origin never reaches the email;
- a preview writes nothing.
"""
import os
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
sys.path.insert(0, os.path.dirname(__file__))

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import database
    from middleware.auth import get_db_client
    from routes import email as email_routes
    from services import access, email_service
    from test_email_service import FROM, ME, NO_SES_ENV, SES_ENV, FakeConn, FakeSES, configured
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_email_routes: {e}")
    sys.exit(0)

ORIGIN = "https://cc.example.com"
BODY = {"to": ["bob@example.com"], "subject": "Q3", "message": "Numbers are **up**.",
        "view_name": "Sales", "view_link": f"{ORIGIN}/#/app/sales", "request_id": "req-9"}


def make_app(authenticated=True):
    app = FastAPI()
    app.include_router(email_routes.router, prefix="/api/email")
    if authenticated:
        app.dependency_overrides[get_db_client] = lambda: object()
    return app


@contextmanager
def signed_in(who=ME, rows=None, env=None, conn=None, ses=None):
    conn = conn if conn is not None else FakeConn()
    ses = ses if ses is not None else FakeSES()
    originals = (access.caller, database.get_db_connection, email_service._ses_client)
    access.caller = lambda _w: access.Caller(who, (), False)
    database.get_db_connection = lambda *a, **k: conn
    email_service._ses_client = lambda: ses
    try:
        with configured({"email_from_address": FROM} if rows is None else rows, env or SES_ENV):
            yield TestClient(make_app()), conn, ses
    finally:
        access.caller, database.get_db_connection, email_service._ses_client = originals


def test_a_request_without_a_signed_in_user_is_refused():
    saved = {k: os.environ.pop(k, None) for k in ("DEV_MODE",)}
    ses = FakeSES()
    original = email_service._ses_client
    email_service._ses_client = lambda: ses
    try:
        client = TestClient(make_app(authenticated=False))
        with configured({"email_from_address": FROM}, SES_ENV):
            response = client.post("/api/email/send", json=BODY)
    finally:
        email_service._ses_client = original
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
    assert response.status_code == 401
    assert ses.calls == []


def test_the_sender_is_the_caller_whatever_the_body_says():
    with signed_in() as (client, conn, ses):
        response = client.post("/api/email/send", headers={"Origin": ORIGIN},
                               json={**BODY, "sender": "ceo@example.com", "sender_email": "ceo@example.com",
                                     "from": "ceo@example.com"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "sent" and response.json()["message_id"] == "0100-abc"
    call = ses.calls[0]
    assert call["ReplyToAddresses"] == [ME]
    assert call["FromEmailAddress"] == f"Command Center <{FROM}>"
    assert "ceo@" not in repr(call)
    row = conn.of("INSERT INTO email_log")[0]
    assert row[0] == ME and row[1] == ME and row[8] == "req-9"


def test_a_view_link_from_another_origin_is_dropped():
    with signed_in() as (client, _conn, ses):
        client.post("/api/email/send", headers={"Origin": ORIGIN}, json=BODY)
        client.post("/api/email/send", headers={"Origin": ORIGIN},
                    json={**BODY, "view_link": "https://evil.example/#/app/sales"})
        client.post("/api/email/send", json=BODY)
    kept, foreign, no_origin = (c["Content"]["Simple"]["Body"]["Html"]["Data"] for c in ses.calls)
    assert f'href="{ORIGIN}/#/app/sales"' in kept
    assert "evil.example" not in foreign and "Open Sales" not in foreign
    # Without an Origin header the Host must match; the test client's is "testserver".
    assert "Open Sales" not in no_origin


def test_a_refusal_is_a_400_with_the_reason():
    with signed_in() as (client, _conn, ses):
        response = client.post("/api/email/send", json={**BODY, "to": "bob@example.com, eve@other.com"})
    assert response.status_code == 400
    assert "eve@other.com" in response.json()["detail"]
    assert ses.calls == []


def test_the_daily_cap_is_a_429():
    with signed_in(conn=FakeConn(sent_today=50)) as (client, _conn, ses):
        response = client.post("/api/email/send", json=BODY)
    assert response.status_code == 429 and "24 hours" in response.json()["detail"]
    assert ses.calls == []


def test_not_set_up_is_a_503_that_says_so():
    with signed_in(rows={}, env={**NO_SES_ENV, "APP_ENVIRONMENT": "prod"}) as (client, conn, ses):
        response = client.post("/api/email/send", json=BODY)
    assert response.status_code == 503
    assert response.json()["detail"] == "Email isn't set up in this app yet."
    assert ses.calls == [] and conn.statements == []


def test_a_failed_send_is_a_502():
    from test_email_service import ClientError
    ses = FakeSES(error=ClientError("MessageRejected", "Email address is not verified."))
    with signed_in(ses=ses) as (client, conn, _ses):
        response = client.post("/api/email/send", json=BODY)
    assert response.status_code == 502 and "not verified" in response.json()["detail"]
    assert conn.of("UPDATE email_log")[0][0] == "failed"


def test_a_preview_writes_nothing():
    with signed_in(conn=FakeConn(sent_today=3)) as (client, conn, ses):
        response = client.post("/api/email/preview", headers={"Origin": ORIGIN},
                               json={**BODY, "table": {"columns": ["a"], "rows": [[1], [2]]}, "attach_csv": True})
    body = response.json()
    assert response.status_code == 200
    assert body["available"] and body["problem"] is None and body["recipients"] == ["bob@example.com"]
    assert "<strong>up</strong>" in body["html"] and f'href="{ORIGIN}/#/app/sales"' in body["html"]
    assert body["attachment"] == {"filename": "q3.csv", "rows": 2, "bytes": body["attachment"]["bytes"]}
    assert body["sent_today"] == 3 and body["reply_to"] == ME
    assert ses.calls == []
    assert all(text.startswith("SELECT COUNT") for text, _ in conn.statements)


def test_a_preview_when_not_set_up_says_so():
    with signed_in(rows={}, env={**NO_SES_ENV, "APP_ENVIRONMENT": "prod"}) as (client, conn, _ses):
        body = client.post("/api/email/preview", json=BODY).json()
    assert body["available"] is False and body["problem"] == "Email isn't set up in this app yet."
    assert body["reason"] == "not_set_up" and conn.statements == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
