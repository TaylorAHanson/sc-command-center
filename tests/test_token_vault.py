"""Tests for the token vault (services/token_vault.py) and its routes (routes/oauth.py).

The vault is how scheduled work runs as the person who scheduled it, so what these
pin down are its promises: tokens are stored encrypted and only for the caller they
were issued to, a sign-in can't be finished by anyone else or redirected off the
app, a refresh saves a rotated token under the row lock, and a token that stops
working says so (NeedsReconnect) instead of falling back to anything. No network
and no database: the two tables, the token endpoint, the clock and the caller are
faked where the vault uses them.
"""
import base64
import copy
import json
import logging
import os
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    from cryptography.fernet import Fernet, MultiFernet
    from starlette.requests import Request

    from routes import oauth as oauth_routes
    from services import activity, caller_identity, data_migration, settings_store, token_vault
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_token_vault: {e}")
    sys.exit(0)

ROOT = os.path.join(os.path.dirname(__file__), "..")
NOW = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)
WORKSPACE = "https://dbc-1234abcd-5678.cloud.databricks.com"
APP_HOST = "cc-prod-1234567890123456.aws.databricksapps.com"
CALLBACK = f"https://{APP_HOST}/api/oauth/callback"
CLIENT_ID = "3f2a6c9e-1b7d-4e5a-9c8b-0d1e2f3a4b5c"
ADA = "ada@example.com"
BOB = "bob@example.com"

ENV_KEYS = ("DATABRICKS_HOST", "DATABRICKS_CLIENT_SECRET", "TOKEN_VAULT_KEY", "OAUTH_CLIENT_SECRET",
            "OAUTH_REDIRECT_URI", "OAUTH_CLIENT_ID", "OAUTH_REFRESH_TTL_DAYS", "DATABRICKS_APP_NAME",
            "DATABRICKS_WORKSPACE_ID")


# ------------------------------------------------------------------ fakes

class FakeStore:
    """The two vault tables. Writes are staged per connection and kept only on commit."""

    def __init__(self):
        self.tokens = {}
        self.pending = {}
        self.executed = []  # (connection number, sql)
        self.locked = []
        self.fail_on = set()
        self.connections = 0

    def connect(self):
        self.connections += 1
        return FakeConn(self, self.connections)


class FakeConn:
    def __init__(self, store, number):
        self.store = store
        self.number = number
        self._stage()

    def _stage(self):
        self.tokens = copy.deepcopy(self.store.tokens)
        self.pending = copy.deepcopy(self.store.pending)

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.store.tokens, self.store.pending = self.tokens, self.pending
        self._stage()

    def rollback(self):
        self._stage()

    def close(self):
        pass


LOCK_COLUMNS = ("refresh_token_enc", "access_token_enc", "access_expires_at", "connected_at",
                "refresh_issued_at", "refresh_expires_at", "status")

# Taken once, so a statement the vault stops sending (or changes) is an unexpected
# one here rather than silently matched.
SQL = type("SQL", (), {name: getattr(token_vault, name) for name in dir(token_vault) if name.startswith("SQL_")})


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 0
        self._rows = []

    def execute(self, sql, params=()):
        tv, conn, store = SQL, self.conn, self.conn.store
        store.executed.append((conn.number, sql))
        if sql in store.fail_on:
            raise RuntimeError("database down")
        self.rowcount, self._rows = 0, []
        if sql == tv.SQL_LOCK_TIMEOUT:
            return
        if sql == tv.SQL_LOCK:
            store.locked.append(params[0])
            row = conn.tokens.get(params[0])
            self._rows = [tuple(row[k] for k in LOCK_COLUMNS)] if row else []
        elif sql == tv.SQL_READ:
            row = conn.tokens.get(params[0])
            self._rows = [tuple(row[k] for k in ("connected_at", "refresh_issued_at", "refresh_expires_at",
                                                 "status"))] if row else []
        elif sql == tv.SQL_CONNECTED:
            self._rows = [(u, r["refresh_issued_at"], r["refresh_expires_at"])
                          for u, r in conn.tokens.items() if r["status"] == "connected"]
        elif sql == tv.SQL_SAVE_REFRESH:
            refresh_enc, issued, expires, access_enc, access_until, updated, user = params
            if user in conn.tokens:
                conn.tokens[user].update(refresh_token_enc=refresh_enc, refresh_issued_at=issued,
                                         refresh_expires_at=expires, access_token_enc=access_enc,
                                         access_expires_at=access_until, status="connected", last_error=None,
                                         updated_at=updated)
                self.rowcount = 1
        elif sql == tv.SQL_MARK:
            state, error, updated, user = params
            if user in conn.tokens:
                conn.tokens[user].update(status=state, last_error=error, access_token_enc=None,
                                         access_expires_at=None, updated_at=updated)
                self.rowcount = 1
        elif sql == tv.SQL_STORE:
            user, refresh_enc, access_enc, access_until, scopes, connected, issued, expires, updated = params
            conn.tokens[user] = dict(refresh_token_enc=refresh_enc, access_token_enc=access_enc,
                                     access_expires_at=access_until, scopes=scopes, connected_at=connected,
                                     refresh_issued_at=issued, refresh_expires_at=expires, status="connected",
                                     last_error=None, updated_at=updated)
            self.rowcount = 1
        elif sql == tv.SQL_DELETE:
            self.rowcount = 1 if conn.tokens.pop(params[0], None) else 0
        elif sql == tv.SQL_PENDING_PURGE:
            stale = [s for s, p in conn.pending.items() if p["created_at"] < params[0]]
            for s in stale:
                del conn.pending[s]
            self.rowcount = len(stale)
        elif sql == tv.SQL_PENDING_ADD:
            state, user, verifier_enc, nonce, redirect_uri, return_to, created = params
            conn.pending[state] = dict(username=user, verifier_enc=verifier_enc, nonce=nonce,
                                       redirect_uri=redirect_uri, return_to=return_to, created_at=created)
            self.rowcount = 1
        elif sql == tv.SQL_PENDING_TAKE:
            p = conn.pending.pop(params[0], None)
            self._rows = [tuple(p[k] for k in ("username", "verifier_enc", "nonce", "redirect_uri", "return_to",
                                               "created_at"))] if p else []
            self.rowcount = len(self._rows)
        elif sql == tv.SQL_PENDING_DROP_USER:
            mine = [s for s, p in conn.pending.items() if p["username"] == params[0]]
            for s in mine:
                del conn.pending[s]
            self.rowcount = len(mine)
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeEndpoint:
    def __init__(self):
        self.calls = []
        self.replies = []

    def reply(self, status, body):
        self.replies.append((status, body))

    def __call__(self, url, data, auth=None):
        self.calls.append({"url": url, "data": dict(data), "auth": auth})
        if not self.replies:
            raise AssertionError("the token endpoint was called unexpectedly")
        status, body = self.replies.pop(0)
        if isinstance(body, Exception):
            raise body
        return status, body


class Harness:
    def __init__(self):
        self.store = FakeStore()
        self.endpoint = FakeEndpoint()
        self.events = []
        self.now = NOW
        self.caller = ADA

    def advance(self, **delta):
        self.now += timedelta(**delta)

    def seed(self, user=ADA, refresh="rt-1", access=None, access_expires_at=None, issued_at=None,
             expires_at=None, status="connected", cipher=None):
        issued = issued_at or NOW - timedelta(days=1)
        self.store.tokens[user] = dict(
            refresh_token_enc=token_vault.encrypt(refresh, cipher),
            access_token_enc=token_vault.encrypt(access, cipher) if access else None,
            access_expires_at=access_expires_at, scopes=token_vault.SCOPE, connected_at=issued,
            refresh_issued_at=issued, refresh_expires_at=expires_at, status=status, last_error=None,
            updated_at=issued)


@contextmanager
def vault(env=None, settings=None):
    """Run with faked tables, token endpoint, clock, settings, activity log and caller.

    By default this is a ready deployment: a client id in Settings, a workspace, and a
    vault key derived from the app's secret.
    """
    values = {"DATABRICKS_HOST": WORKSPACE, "DATABRICKS_CLIENT_SECRET": "app-secret",
              "DATABRICKS_APP_NAME": "cc-prod", "DATABRICKS_WORKSPACE_ID": "1234567890123456"}
    values.update(env or {})
    rows = {"oauth_client_id": CLIENT_ID}
    rows.update(settings or {})
    rows = {k: v for k, v in rows.items() if v is not None}

    h = Harness()
    saved_env = {k: os.environ.get(k) for k in ENV_KEYS}
    saved = [(token_vault, "_connect"), (token_vault, "_http_post"), (token_vault, "_now"),
             (activity, "record"), (settings_store, "_read_rows"), (caller_identity, "username")]
    originals = [(mod, name, getattr(mod, name)) for mod, name in saved]
    for key in ENV_KEYS:
        value = values.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    token_vault._connect = h.store.connect
    token_vault._http_post = h.endpoint
    token_vault._now = lambda: h.now
    activity.record = lambda *args, **kwargs: h.events.append(args)
    settings_store._read_rows = lambda: dict(rows)
    caller_identity.username = lambda w: h.caller
    settings_store.invalidate()
    try:
        yield h
    finally:
        for mod, name, original in originals:
            setattr(mod, name, original)
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        settings_store.invalidate()


def _b64(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def _jwt(claims):
    return f"{_b64({'alg': 'RS256', 'kid': 'k1'})}.{_b64(claims)}.c2lnbmF0dXJl"


def _claims(**overrides):
    claims = {"iss": WORKSPACE + "/oidc", "aud": CLIENT_ID, "sub": ADA, "email": ADA,
              "iat": int(NOW.timestamp()), "exp": int(NOW.timestamp()) + 3600}
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def _request(headers=None):
    values = {"host": "0.0.0.0:8000", "x-forwarded-host": APP_HOST, "x-forwarded-proto": "https"}
    values.update(headers or {})
    return Request({
        "type": "http", "method": "GET", "path": "/api/oauth/connect", "root_path": "", "query_string": b"",
        "scheme": "http", "server": ("0.0.0.0", 8000),
        "headers": [(k.encode(), v.encode()) for k, v in values.items() if v is not None],
    })


def _start(h, return_to="/#/schedules"):
    """Begin a sign-in through the route; (state, query of the authorize URL)."""
    response = oauth_routes.connect(_request(), return_to=return_to, w=None)
    assert response.status_code == 302, response.status_code
    location = response.headers["location"]
    assert location.startswith(WORKSPACE + token_vault.AUTHORIZE_PATH + "?"), location
    query = dict(parse_qsl(urlsplit(location).query))
    return query["state"], query


def _signed_in(query, **claims):
    return {"access_token": "at-1", "refresh_token": "rt-1", "token_type": "Bearer", "expires_in": 3600,
            "scope": token_vault.SCOPE, "id_token": _jwt(_claims(nonce=query["nonce"], **claims))}


def _raises(fn, kind):
    try:
        fn()
    except kind as e:
        return e
    raise AssertionError(f"expected {kind.__name__}")


# ------------------------------------------------------------------ the key

def test_encrypt_decrypt_round_trip():
    with vault(env={"TOKEN_VAULT_KEY": Fernet.generate_key().decode()}):
        sealed = token_vault.encrypt("rt-secret-value")
        assert "rt-secret-value" not in sealed
        assert token_vault.decrypt(sealed) == "rt-secret-value"
        assert token_vault.encrypt("rt-secret-value") != sealed  # Fernet is randomized


def test_the_derived_key_is_deterministic_and_bound_to_the_app_secret():
    assert token_vault.derive_key("app-secret") == token_vault.derive_key("app-secret")
    assert token_vault.derive_key("app-secret") != token_vault.derive_key("another-secret")
    Fernet(token_vault.derive_key("app-secret"))  # a valid Fernet key
    with vault():
        sealed = token_vault.encrypt("rt-1")
        assert token_vault.key_state().source == "derived"
    with vault(env={"DATABRICKS_CLIENT_SECRET": "app-secret"}):
        assert token_vault.decrypt(sealed) == "rt-1"  # another worker, another restart
    with vault(env={"DATABRICKS_CLIENT_SECRET": "rotated-secret"}):
        _raises(lambda: token_vault.decrypt(sealed), token_vault.Undecryptable)


def test_adding_token_vault_key_later_still_reads_what_the_derived_key_wrote():
    explicit = Fernet.generate_key().decode()
    with vault():
        old = token_vault.encrypt("rt-old")
    with vault(env={"TOKEN_VAULT_KEY": explicit}):
        assert token_vault.key_state().source == "TOKEN_VAULT_KEY"
        assert token_vault.decrypt(old) == "rt-old"
        new = token_vault.encrypt("rt-new")
        assert Fernet(explicit.encode()).decrypt(new.encode()) == b"rt-new"


def test_a_malformed_key_turns_the_vault_off_rather_than_falling_back():
    with vault(env={"TOKEN_VAULT_KEY": "not-a-fernet-key"}):
        state = token_vault.key_state()
        assert state.keys == () and "TOKEN_VAULT_KEY" in state.problem
        _raises(lambda: token_vault.encrypt("x"), token_vault.VaultError)
        assert token_vault.capability()["available"] is False


def test_with_no_key_at_all_nothing_is_stored():
    with vault(env={"DATABRICKS_CLIENT_SECRET": None}):
        assert token_vault.key_state().keys == ()
        assert _raises(lambda: token_vault.encrypt("x"), token_vault.VaultError).reason == "not_set_up"
        assert _raises(lambda: token_vault.access_token_for(ADA), token_vault.VaultError).reason == "not_set_up"


# ------------------------------------------------------------------ PKCE, state, return_to, id_token

def test_pkce_matches_the_rfc_7636_example():
    # RFC 7636 Appendix B.
    assert token_vault.code_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == \
        "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    verifier, challenge = token_vault.new_pkce()
    assert 43 <= len(verifier) <= 128
    assert set(verifier) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
    assert challenge == token_vault.code_challenge(verifier) and "=" not in challenge
    assert token_vault.new_pkce()[0] != verifier


def test_the_authorize_url_asks_for_the_documented_parameters():
    url = token_vault.authorize_url(WORKSPACE, CLIENT_ID, CALLBACK, "st", "ch", "nn")
    assert url.startswith(f"{WORKSPACE}/oidc/v1/authorize?")
    assert "scope=openid%20email%20offline_access%20sql" in url
    assert dict(parse_qsl(urlsplit(url).query)) == {
        "client_id": CLIENT_ID, "response_type": "code", "redirect_uri": CALLBACK,
        "scope": "openid email offline_access sql", "state": "st", "code_challenge": "ch",
        "code_challenge_method": "S256", "nonce": "nn"}


def test_a_sign_in_state_expires_after_ten_minutes_and_belongs_to_its_caller():
    pending = token_vault.Pending(ADA, "enc", "nonce", CALLBACK, "/", NOW)
    assert token_vault.pending_problem(pending, ADA, NOW + timedelta(seconds=599)) is None
    assert token_vault.pending_problem(pending, "Ada@Example.com ", NOW) is None
    assert token_vault.pending_problem(pending, ADA, NOW + timedelta(seconds=601)) == "expired"
    assert token_vault.pending_problem(pending, BOB, NOW) == "started by someone else"
    assert token_vault.pending_problem(None, ADA, NOW) == "unknown or already used"
    naive = pending._replace(created_at=NOW.replace(tzinfo=None))
    assert token_vault.pending_problem(naive, ADA, NOW + timedelta(minutes=1)) is None


def test_return_to_accepts_paths_on_this_app():
    for ok in ("/", "/#/schedules", "/?v.region=EMEA#/app/sales", "/#/app/view-1?tab=2", "/api/x"):
        assert token_vault.safe_return_to(ok) == ok, ok


def test_return_to_refuses_anything_that_could_leave_the_app():
    for bad in (None, 7, "", "https://evil.example", "http://evil.example/#/x", "//evil.example",
                "///evil.example", "/\\evil.example", "\\\\evil.example", "\\/evil.example",
                "javascript:alert(1)", "JaVaScRiPt:alert(1)", "/\t/evil.example", "/\n/evil.example",
                "/ x", "data:text/html,hi", "evil.example", "#/schedules", "/caf\u00e9",
                "/" + "a" * token_vault.MAX_RETURN_TO):
        assert token_vault.safe_return_to(bad) is None, repr(bad)


def test_the_outcome_goes_in_the_query_ahead_of_the_hash_and_replaces_an_old_one():
    assert token_vault.with_outcome("/#/schedules", "oauth", "connected") == "/?oauth=connected#/schedules"
    assert token_vault.with_outcome("/?a=1", "oauth_error", "denied") == "/?a=1&oauth_error=denied"
    assert token_vault.with_outcome("/?oauth_error=denied&a=1#/x", "oauth", "connected") == \
        "/?a=1&oauth=connected#/x"
    assert token_vault.with_outcome("//evil.example", "oauth", "connected") == "/?oauth=connected"


def test_decoding_an_id_token_refuses_what_isnt_one():
    assert token_vault.decode_jwt_payload(_jwt({"sub": ADA})) == {"sub": ADA}
    for bad in ("", "abc", "a.b", "a..c", "a.!!!.c", f"a.{_b64([1, 2])}.c", "a.\u00e9.c"):
        _raises(lambda: token_vault.decode_jwt_payload(bad), ValueError)


def test_id_token_claims_are_checked():
    def check(claims, username=ADA, nonce="n1"):
        return token_vault.check_id_token(claims, issuer=WORKSPACE + "/oidc", client=CLIENT_ID,
                                          username=username, nonce=nonce, now=NOW)

    assert check(_claims(nonce="n1")) is None
    assert check(_claims(iss=WORKSPACE + "/oidc/")) is None
    assert check(_claims(aud=["other", CLIENT_ID], azp=CLIENT_ID)) is None
    assert check(_claims(exp=int(NOW.timestamp()) - 60)) is None  # inside the clock skew
    assert check(_claims()) is None  # a workspace that doesn't echo the nonce

    assert check(_claims(iss="https://evil.example/oidc"))[0] == "invalid_id_token"
    assert check(_claims(iss=None))[0] == "invalid_id_token"
    assert check(_claims(aud="another-client"))[0] == "invalid_id_token"
    assert check(_claims(aud=None))[0] == "invalid_id_token"
    assert check(_claims(azp="another-client"))[0] == "invalid_id_token"
    assert check(_claims(exp=int(NOW.timestamp()) - 600))[0] == "invalid_id_token"
    assert check(_claims(exp=None))[0] == "invalid_id_token"
    assert check(_claims(exp=True))[0] == "invalid_id_token"
    assert check(_claims(nbf=int(NOW.timestamp()) + 600))[0] == "invalid_id_token"
    assert check(_claims(nonce="replayed"))[0] == "invalid_id_token"
    assert check(_claims(nonce="n1"), nonce="")[0] == "invalid_id_token"
    assert check(["not", "claims"])[0] == "invalid_id_token"


def test_the_id_token_must_name_the_signed_in_caller():
    def check(claims, username=ADA):
        return token_vault.check_id_token(claims, issuer=WORKSPACE + "/oidc", client=CLIENT_ID,
                                          username=username, now=NOW)

    assert check(_claims(email=None)) is None  # sub alone, as on Databricks access tokens
    assert check(_claims(email=None, sub="1234", preferred_username=ADA)) is None
    assert check(_claims(email="ADA@example.com", sub="1234")) is None
    assert check(_claims(email=BOB, sub=BOB))[0] == "identity_mismatch"
    assert check(_claims(email=None, sub=None))[0] == "identity_mismatch"
    assert check(_claims(), username=BOB)[0] == "identity_mismatch"


# ------------------------------------------------------------------ redirect URI and the Setup card

def test_the_callback_url_comes_from_the_override_the_proxy_or_the_app_name():
    with vault(env={"OAUTH_REDIRECT_URI": "https://cc.example.com/api/oauth/callback"}):
        assert token_vault.callback_url(forwarded_host=APP_HOST) == "https://cc.example.com/api/oauth/callback"
    with vault():
        assert token_vault.callback_url(forwarded_host=APP_HOST, scheme="http") == CALLBACK
        assert token_vault.callback_url() == CALLBACK  # derived, for the Setup card
        assert token_vault.callback_url(forwarded_host="evil.example/x") == CALLBACK
        assert token_vault.callback_url(forwarded_host="a b") == CALLBACK
        assert token_vault.callback_url(forwarded_host="localhost:5174", scheme="http") == \
            "http://localhost:5174/api/oauth/callback"
        assert token_vault.callback_url(host="127.0.0.1:8001", scheme="http") == \
            "http://127.0.0.1:8001/api/oauth/callback"
    with vault(env={"DATABRICKS_HOST": "https://adb-123.4.azuredatabricks.net"}):
        assert token_vault.callback_url() == ""  # not confirmed off AWS
        assert token_vault.callback_url(host="10.0.0.7:8000") == ""  # the container's own Host
        assert token_vault.callback_url(forwarded_host="cc-1.azure.databricksapps.com") == \
            "https://cc-1.azure.databricksapps.com/api/oauth/callback"


def test_the_capability_spells_out_the_integration_when_no_client_id_is_set():
    with vault(settings={"oauth_client_id": None}):
        result = token_vault.capability()
    assert result["available"] is False
    integration = result["missing"][0]
    for part in ("public client", "openid, email, offline_access, sql", CALLBACK, "30-day"):
        assert part in integration, part
    assert "Admin Panel → Settings → Scheduling" in result["missing"][1]
    assert CALLBACK in result["next_step"] and "43200 minutes" in result["next_step"]


def test_the_capability_reports_each_missing_piece():
    with vault(settings={"oauth_client_id": "has spaces; DROP"}):
        result = token_vault.capability()
        assert result["available"] is False and "client id" in result["missing"][0]
    with vault(env={"DATABRICKS_CLIENT_SECRET": None}):
        result = token_vault.capability()
        assert result["available"] is False and any("TOKEN_VAULT_KEY" in m for m in result["missing"])
    with vault(env={"DATABRICKS_HOST": None}):
        result = token_vault.capability()
        assert result["available"] is False and any("DATABRICKS_HOST" in m for m in result["missing"])
    with vault(settings={"oauth_client_id": None, "oauth_refresh_ttl_days": "14"},
               env={"DATABRICKS_APP_NAME": None}):
        result = token_vault.capability()
        assert "20160 minutes" in result["next_step"] and "<this app's address>" in result["next_step"]


def test_the_capability_is_ready_with_a_client_id_and_a_key():
    with vault():
        result = token_vault.capability()
        assert result["available"] is True and result["missing"] == []
        assert result["next_step"].startswith("Optional: set TOKEN_VAULT_KEY")
    with vault(env={"TOKEN_VAULT_KEY": Fernet.generate_key().decode()}):
        result = token_vault.capability()
        assert result["available"] is True and result["next_step"] == ""


def test_the_client_id_setting_is_one_line_of_text():
    assert settings_store.validate_value("oauth_client_id", f"  {CLIENT_ID} ") == (CLIENT_ID, None)
    assert settings_store.validate_value("oauth_client_id", "abc\ndef")[1]
    assert settings_store.validate_value("oauth_client_id", "x" * 501)[1]
    assert settings_store.validate_value("oauth_client_id", "") == ("", None)
    assert settings_store.validate_value("oauth_refresh_ttl_days", "14") == ("14", None)
    with vault(settings={"oauth_client_id": None}):
        assert token_vault.refresh_ttl_days() == 30
        assert token_vault.client_id() == ("", "")


# ------------------------------------------------------------------ status and expiring

def test_status_without_a_connection():
    with vault():
        assert token_vault.status(ADA) == {"connected": False, "connected_at": None, "expires_at": None,
                                           "needs_reconnect": False, "reason": "not_connected"}
        assert token_vault.status("unknown")["reason"] == "not_connected"


def test_status_counts_the_expiry_from_the_setting_unless_the_workspace_gave_one():
    with vault(settings={"oauth_refresh_ttl_days": "10"}) as h:
        h.seed(issued_at=NOW - timedelta(days=2))
        assert token_vault.status("ADA@example.com") == {
            "connected": True, "connected_at": NOW - timedelta(days=2), "expires_at": NOW + timedelta(days=8),
            "needs_reconnect": False, "reason": None}
        h.seed(user=BOB, expires_at=NOW + timedelta(days=3), status="revoked")
        bob = token_vault.status(BOB)
        assert bob["expires_at"] == NOW + timedelta(days=3)
        assert bob["connected"] is False and bob["needs_reconnect"] is True and bob["reason"] == "revoked"


def test_expiring_lists_connections_ending_soon_soonest_first():
    with vault() as h:
        h.seed(user="soon@example.com", issued_at=NOW - timedelta(days=25))
        h.seed(user="fresh@example.com", issued_at=NOW - timedelta(days=1))
        h.seed(user="told@example.com", expires_at=NOW + timedelta(days=2))
        h.seed(user="lapsed@example.com", issued_at=NOW - timedelta(days=31))
        h.seed(user="gone@example.com", issued_at=NOW - timedelta(days=29), status="revoked")
        assert token_vault.expiring(7) == [
            ("lapsed@example.com", NOW - timedelta(days=1)),
            ("told@example.com", NOW + timedelta(days=2)),
            ("soon@example.com", NOW + timedelta(days=5)),
        ]
        assert token_vault.expiring(0) == [("lapsed@example.com", NOW - timedelta(days=1))]


def test_reconnect_reason_tells_expiry_from_revocation():
    assert token_vault.reconnect_reason(NOW + timedelta(minutes=30), NOW) == "expired"
    assert token_vault.reconnect_reason(NOW + timedelta(days=20), NOW) == "revoked"
    assert token_vault.reconnect_reason(NOW + timedelta(days=20), NOW, "Refresh token expired") == "expired"
    assert token_vault.reconnect_reason(None, NOW) == "revoked"


# ------------------------------------------------------------------ access_token_for

def test_access_token_for_refreshes_under_the_row_lock_and_caches_the_result():
    with vault() as h:
        h.seed()
        h.endpoint.reply(200, {"access_token": "at-2", "expires_in": 3600, "token_type": "Bearer"})
        assert token_vault.access_token_for(ADA) == "at-2"
        call = h.endpoint.calls[0]
        assert call["url"] == WORKSPACE + "/oidc/v1/token" and call["auth"] is None
        assert call["data"] == {"grant_type": "refresh_token", "refresh_token": "rt-1", "client_id": CLIENT_ID}
        assert h.store.locked == [ADA]
        sqls = [sql for _, sql in h.store.executed]
        assert sqls[:2] == [token_vault.SQL_LOCK_TIMEOUT, token_vault.SQL_LOCK]
        row = h.store.tokens[ADA]
        assert token_vault.decrypt(row["access_token_enc"]) == "at-2"
        assert row["access_expires_at"] == NOW + timedelta(hours=1)
        assert token_vault.decrypt(row["refresh_token_enc"]) == "rt-1"  # not rotated
        assert row["refresh_issued_at"] == NOW - timedelta(days=1)

        h.advance(minutes=30)
        assert token_vault.access_token_for(ADA) == "at-2"  # cached
        assert len(h.endpoint.calls) == 1
        h.advance(minutes=26)
        h.endpoint.reply(200, {"access_token": "at-3", "expires_in": 3600})
        assert token_vault.access_token_for(ADA) == "at-3"  # inside the 5-minute margin
        assert len(h.endpoint.calls) == 2


def test_a_rotated_refresh_token_is_saved_in_the_same_locked_transaction():
    with vault() as h:
        h.seed()
        h.endpoint.reply(200, {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600,
                               "refresh_token_expires_in": 86400 * 30})
        assert token_vault.access_token_for(ADA) == "at-2"
        row = h.store.tokens[ADA]
        assert token_vault.decrypt(row["refresh_token_enc"]) == "rt-2"
        assert row["refresh_issued_at"] == NOW and row["refresh_expires_at"] == NOW + timedelta(days=30)
        lock = next(n for n, sql in h.store.executed if sql == token_vault.SQL_LOCK)
        save = next(n for n, sql in h.store.executed if sql == token_vault.SQL_SAVE_REFRESH)
        assert lock == save

        h.store.tokens[ADA]["access_token_enc"] = None
        h.endpoint.reply(200, {"access_token": "at-3", "refresh_token": "rt-3"})
        token_vault.access_token_for(ADA)
        assert h.endpoint.calls[1]["data"]["refresh_token"] == "rt-2"  # the saved rotation is what's used
        assert h.store.tokens[ADA]["refresh_expires_at"] is None  # no lifetime given: counted from issue


def test_invalid_grant_needs_reconnect_and_is_remembered():
    with vault() as h:
        h.seed()
        h.endpoint.reply(400, {"error": "invalid_grant", "error_description": "Refresh token is invalid"})
        e = _raises(lambda: token_vault.access_token_for(ADA), token_vault.NeedsReconnect)
        assert e.reason == "revoked"
        row = h.store.tokens[ADA]
        assert row["status"] == "revoked" and row["access_token_enc"] is None
        assert h.events == [(ADA, "oauth.needs_reconnect", "oauth", None, {"reason": "revoked"})]
        assert _raises(lambda: token_vault.access_token_for(ADA), token_vault.NeedsReconnect).reason == "revoked"
        assert len(h.endpoint.calls) == 1  # the second ask never reached the workspace
        assert token_vault.status(ADA)["needs_reconnect"] is True


def test_invalid_grant_at_the_end_of_the_lifetime_is_an_expiry():
    with vault() as h:
        h.seed(issued_at=NOW - timedelta(days=30))
        h.endpoint.reply(400, {"error": "invalid_grant"})
        assert _raises(lambda: token_vault.access_token_for(ADA), token_vault.NeedsReconnect).reason == "expired"
        assert h.store.tokens[ADA]["status"] == "expired"


def test_a_token_no_key_opens_moves_to_undecryptable():
    with vault() as h:
        h.seed(cipher=MultiFernet([Fernet(token_vault.derive_key("the-old-secret"))]))
        e = _raises(lambda: token_vault.access_token_for(ADA), token_vault.NeedsReconnect)
        assert e.reason == "undecryptable" and h.endpoint.calls == []
        assert h.store.tokens[ADA]["status"] == "undecryptable"
        assert token_vault.status(ADA)["reason"] == "undecryptable"


def test_a_workspace_that_doesnt_answer_is_a_vault_error_and_changes_nothing():
    with vault() as h:
        h.seed()
        before = copy.deepcopy(h.store.tokens)
        h.endpoint.reply(503, {})
        assert _raises(lambda: token_vault.access_token_for(ADA), token_vault.VaultError).reason == "unavailable"
        h.endpoint.reply(0, ConnectionError("no route to host"))
        assert _raises(lambda: token_vault.access_token_for(ADA), token_vault.VaultError).reason == "unavailable"
        h.endpoint.reply(401, {"error": "invalid_client"})
        assert _raises(lambda: token_vault.access_token_for(ADA), token_vault.VaultError).reason == "unavailable"
        assert h.store.tokens == before and h.events == []


def test_access_token_for_has_no_fallback_for_someone_without_a_connection():
    with vault() as h:
        for who in (BOB, "unknown", "", None, "3f2a6c9e-1b7d-4e5a-9c8b-0d1e2f3a4b5c"):
            assert _raises(lambda: token_vault.access_token_for(who), token_vault.NeedsReconnect).reason == \
                "not_connected"
        assert h.endpoint.calls == []
    with vault(settings={"oauth_client_id": None}) as h:
        h.seed()
        assert _raises(lambda: token_vault.access_token_for(ADA), token_vault.VaultError).reason == "not_set_up"
        assert h.endpoint.calls == []


def test_access_token_for_runs_with_no_request_in_scope():
    with vault() as h:
        h.seed()
        h.endpoint.reply(200, {"access_token": "at-2"})
        out = {}
        thread = threading.Thread(target=lambda: out.setdefault("token", token_vault.access_token_for(ADA)))
        thread.start()
        thread.join(5)
        assert out == {"token": "at-2"}


def test_a_confidential_client_authenticates_with_its_secret():
    with vault(env={"OAUTH_CLIENT_SECRET": "client-secret"}) as h:
        h.seed()
        h.endpoint.reply(200, {"access_token": "at-2"})
        token_vault.access_token_for(ADA)
        call = h.endpoint.calls[0]
        assert call["auth"] == (CLIENT_ID, "client-secret") and "client_id" not in call["data"]


def test_needs_reconnect_reasons_are_the_contract():
    assert token_vault.REASONS == ("not_connected", "expired", "revoked", "undecryptable")
    assert token_vault.NeedsReconnect("bogus").reason == "revoked"
    for reason in token_vault.REASONS:
        assert str(token_vault.NeedsReconnect(reason))


# ------------------------------------------------------------------ the routes

def test_connect_then_callback_stores_an_encrypted_token_for_the_caller():
    with vault() as h:
        state, query = _start(h)
        assert query["client_id"] == CLIENT_ID and query["redirect_uri"] == CALLBACK
        assert query["scope"] == "openid email offline_access sql" and query["code_challenge_method"] == "S256"
        pending = h.store.pending[state]
        verifier = token_vault.decrypt(pending["verifier_enc"])
        assert token_vault.code_challenge(verifier) == query["code_challenge"]
        assert verifier not in json.dumps(h.store.pending, default=str)
        assert pending["username"] == ADA and pending["return_to"] == "/#/schedules"

        h.endpoint.reply(200, _signed_in(query))
        response = oauth_routes.callback(code="the-code", state=state, error="", w=None)
        assert response.status_code == 302
        assert response.headers["location"] == "/?oauth=connected#/schedules"
        assert response.headers["cache-control"] == "no-store"
        assert h.endpoint.calls[0]["data"] == {"grant_type": "authorization_code", "code": "the-code",
                                               "redirect_uri": CALLBACK, "code_verifier": verifier,
                                               "client_id": CLIENT_ID}
        row = h.store.tokens[ADA]
        assert token_vault.decrypt(row["refresh_token_enc"]) == "rt-1"
        assert token_vault.decrypt(row["access_token_enc"]) == "at-1"
        stored = json.dumps(h.store.tokens, default=str)
        assert "rt-1" not in stored and "at-1" not in stored
        assert state not in h.store.pending
        assert h.events == [(ADA, "oauth.connect", "oauth", None, {"scopes": token_vault.SCOPE})]

        h.endpoint.reply(200, {"access_token": "at-2"})
        h.advance(minutes=58)
        assert token_vault.access_token_for(ADA) == "at-2"


def test_a_state_is_good_once_and_only_for_the_caller_who_started_it():
    with vault() as h:
        state, query = _start(h)
        h.caller = BOB
        response = oauth_routes.callback(code="the-code", state=state, error="", w=None)
        assert response.headers["location"] == "/?oauth_error=invalid_state"
        assert h.endpoint.calls == [] and h.store.tokens == {}
        h.caller = ADA
        response = oauth_routes.callback(code="the-code", state=state, error="", w=None)
        assert response.headers["location"] == "/?oauth_error=invalid_state"  # burned by the attempt
        response = oauth_routes.callback(code="the-code", state="", error="", w=None)
        assert response.headers["location"] == "/?oauth_error=invalid_state"


def test_an_expired_state_is_refused():
    with vault() as h:
        state, _ = _start(h)
        h.advance(minutes=11)
        response = oauth_routes.callback(code="the-code", state=state, error="", w=None)
        assert response.headers["location"] == "/?oauth_error=invalid_state#/schedules"
        assert h.endpoint.calls == [] and h.store.tokens == {}


def test_an_id_token_naming_someone_else_stores_nothing():
    with vault() as h:
        state, query = _start(h)
        h.endpoint.reply(200, _signed_in(query, email=BOB, sub=BOB))
        response = oauth_routes.callback(code="the-code", state=state, error="", w=None)
        assert response.headers["location"] == "/?oauth_error=identity_mismatch#/schedules"
        assert h.store.tokens == {} and h.events == []


def test_each_failed_sign_in_says_why_and_stores_nothing():
    cases = (
        ({"error": "access_denied"}, None, "denied"),
        ({"error": "server_error"}, None, "idp_error"),
        ({}, (400, {"error": "invalid_grant"}), "exchange_failed"),
        ({}, (200, {"access_token": "at-1", "refresh_token": "rt-1"}), "no_id_token"),
        ({}, (200, {"access_token": "at-1", "refresh_token": "rt-1", "id_token": "garbage"}), "invalid_id_token"),
    )
    for params, reply, reason in cases:
        with vault() as h:
            state, query = _start(h)
            if reply:
                h.endpoint.reply(*reply)
            response = oauth_routes.callback(code="the-code", state=state, error=params.get("error", ""), w=None)
            assert response.headers["location"] == f"/?oauth_error={reason}#/schedules", (reason, response.headers)
            assert h.store.tokens == {} and state not in h.store.pending
    with vault() as h:
        state, query = _start(h)
        body = _signed_in(query)
        del body["refresh_token"]
        h.endpoint.reply(200, body)
        response = oauth_routes.callback(code="the-code", state=state, error="", w=None)
        assert response.headers["location"] == "/?oauth_error=no_refresh_token#/schedules"


def test_connect_goes_back_with_an_error_when_scheduling_isnt_set_up():
    with vault(settings={"oauth_client_id": None}) as h:
        response = oauth_routes.connect(_request(), return_to="/#/schedules", w=None)
        assert response.headers["location"] == "/?oauth_error=not_set_up#/schedules"
        assert h.store.pending == {}
    with vault(env={"DATABRICKS_APP_NAME": None}) as h:
        response = oauth_routes.connect(_request({"x-forwarded-host": None}), return_to="/", w=None)
        assert response.headers["location"] == "/?oauth_error=not_set_up"
    with vault() as h:
        h.caller = "unknown"
        response = oauth_routes.connect(_request(), return_to="/", w=None)
        assert response.headers["location"] == "/?oauth_error=not_signed_in"


def test_connect_never_carries_an_unsafe_return_address():
    with vault() as h:
        state, query = _start(h, return_to="https://evil.example/")
        assert h.store.pending[state]["return_to"] == "/"
        h.endpoint.reply(200, _signed_in(query))
        response = oauth_routes.callback(code="the-code", state=state, error="", w=None)
        assert response.headers["location"] == "/?oauth=connected"


def test_starting_a_sign_in_purges_the_ones_nobody_finished():
    with vault() as h:
        old, _ = _start(h)
        h.advance(minutes=11)
        new, _ = _start(h)
        assert set(h.store.pending) == {new}
        h.advance(minutes=11)
        token_vault.purge_pending()
        assert h.store.pending == {}


def test_status_route_returns_no_token_material():
    with vault() as h:
        state, query = _start(h)
        h.endpoint.reply(200, _signed_in(query))
        oauth_routes.callback(code="the-code", state=state, error="", w=None)
        body = oauth_routes.connection_status(w=None)
        assert set(body) == {"connected", "connected_at", "expires_at", "needs_reconnect", "reason"}
        assert body["connected"] is True and body["connected_at"] == NOW.isoformat()
        assert body["expires_at"] == (NOW + timedelta(days=30)).isoformat()
        text = json.dumps(body)
        assert "rt-1" not in text and "at-1" not in text and "_enc" not in text


def test_disconnect_forgets_the_token_and_records_it():
    with vault() as h:
        h.seed()
        assert oauth_routes.disconnect(w=None) == {"disconnected": True}
        assert ADA not in h.store.tokens
        assert h.events == [(ADA, "oauth.disconnect", "oauth")]
        assert oauth_routes.disconnect(w=None) == {"disconnected": False}
        assert oauth_routes.connection_status(w=None)["reason"] == "not_connected"


def test_status_and_disconnect_fail_as_503_when_the_database_doesnt_answer():
    from fastapi import HTTPException

    with vault() as h:
        h.store.fail_on = {token_vault.SQL_READ, token_vault.SQL_DELETE}
        assert _raises(lambda: oauth_routes.connection_status(w=None), HTTPException).status_code == 503
        assert _raises(lambda: oauth_routes.disconnect(w=None), HTTPException).status_code == 503


def test_no_token_or_verifier_reaches_the_log():
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Capture(level=logging.DEBUG)
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        with vault() as h:
            state, query = _start(h)
            verifier = token_vault.decrypt(h.store.pending[state]["verifier_enc"])
            h.endpoint.reply(200, _signed_in(query))
            oauth_routes.callback(code="the-code", state=state, error="", w=None)
            h.store.tokens[ADA]["access_token_enc"] = None
            h.endpoint.reply(200, {"access_token": "at-2", "refresh_token": "rt-2"})
            token_vault.access_token_for(ADA)
            h.store.tokens[ADA]["access_token_enc"] = None
            h.endpoint.reply(400, {"error": "invalid_grant"})
            _raises(lambda: token_vault.access_token_for(ADA), token_vault.NeedsReconnect)
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)
    assert records, "expected the flow to log something"
    for secret in ("rt-1", "rt-2", "at-1", "at-2", verifier):
        assert not any(secret in message for message in records), secret


# ------------------------------------------------------------------ migration and schema

def test_data_migration_never_copies_the_vault():
    assert {"user_oauth_tokens", "oauth_pending"} <= data_migration.NOT_COPIED
    assert not ({"user_oauth_tokens", "oauth_pending"} & set(data_migration.SPECS))


def test_the_sql_locks_the_row_and_spends_a_state_once():
    assert token_vault.SQL_LOCK.rstrip().endswith("FOR UPDATE")
    assert token_vault.SQL_LOCK_TIMEOUT.startswith("SET LOCAL lock_timeout")
    assert token_vault.SQL_PENDING_TAKE.startswith("DELETE FROM oauth_pending WHERE state = %s RETURNING")
    assert "refresh_token_enc = %s" in token_vault.SQL_SAVE_REFRESH
    for name in dir(token_vault):
        if name.startswith("SQL_"):
            text = getattr(token_vault, name)
            assert "user_oauth_tokens" in text or "oauth_pending" in text or "lock_timeout" in text, name


def test_the_vault_tables_are_created_in_the_settings_schema():
    with open(os.path.join(ROOT, "server", "database.py"), encoding="utf-8") as f:
        source = f.read()
    body = source.split("def _create_vault_tables(conn)", 1)[1].split("\ndef ", 1)[0]
    assert "CREATE TABLE IF NOT EXISTS user_oauth_tokens" in body
    assert "CREATE TABLE IF NOT EXISTS oauth_pending" in body
    settings_block = source.split("if env == settings_env():", 1)[1].split("\n\n", 1)[0]
    assert "_create_vault_tables(conn)" in settings_block


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
