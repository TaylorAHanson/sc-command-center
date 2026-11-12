"""The token vault: how unattended work keeps running as the user.

Scheduled work has to run as the person who scheduled it, under their own Unity
Catalog grants, never as the app's service principal. Databricks Apps forward each
request's caller as an access token of about an hour and no refresh token, so
nothing on a timer can act for someone who isn't on the page, and personal access
tokens aren't allowed where this was built. So each person connects the app once
through the workspace's own OAuth (authorization code with PKCE, through a custom
OAuth app integration the account admin creates as a public client), and the vault
keeps the refresh token that comes back. When a run is due the scheduler asks for an
access token, and the run is that user's own identity, exactly as on the page.

What it promises, and why:

  * Secret material is stored only as Fernet ciphertext: refresh tokens, the cached
    access token, and the PKCE verifier while a sign-in is in flight. It is never
    logged, never returned to the browser, and never copied by Data Migration
    (`NOT_COPIED`).
  * A token is stored only for the signed-in caller it was issued to. The sign-in's
    `state` is bound to the caller who started it, and the id_token must name them.
  * No fallback. Without a key, a client id or a connection there is no token, and
    the caller is told which. The scheduler wraps this with a DEV_MODE token source
    for local runs; nothing here knows about it.
  * Refreshes run under a row lock (`SELECT ... FOR UPDATE`). With single-use
    refresh tokens, two workers refreshing one person at once would each spend the
    token the other needs, and a rotated token that isn't saved is a person who has
    to reconnect.

The key is `TOKEN_VAULT_KEY` (a Fernet key, from a secret resource) when set, else
one derived with HKDF-SHA256 from `DATABRICKS_CLIENT_SECRET`, which every Databricks
App receives and the database never sees, using `KEY_SALT` and `KEY_INFO`. With
both, tokens are written under `TOKEN_VAULT_KEY` and the derived key still reads
what was stored before it was set, so adding one later disconnects nobody. A token
no key opens (the secret rotated) moves its row to `undecryptable` and its owner
reconnects; nothing fails silently.

Everything here works with no request in scope, because the scheduler calls it from
a background thread: settings come from `settings_store`, connections from
`database`, and the workspace from `DATABRICKS_HOST`.

The sign-in's failures reach the browser as `oauth_error=<reason>`, one of
`not_signed_in`, `not_set_up`, `storage_failed`, `invalid_state`, `denied`,
`idp_error`, `exchange_failed`, `no_id_token`, `invalid_id_token`,
`identity_mismatch` and `no_refresh_token`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Tuple
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from services import activity, caller_identity, capabilities, settings_store

logger = logging.getLogger(__name__)

SCOPES = ("openid", "email", "offline_access", "sql")
SCOPE = " ".join(SCOPES)
CALLBACK_PATH = "/api/oauth/callback"
AUTHORIZE_PATH = "/oidc/v1/authorize"
TOKEN_PATH = "/oidc/v1/token"
ISSUER_PATH = "/oidc"

# Fixed, because every worker must derive the same key after every restart. Change
# either and every token stored under the derived key becomes unreadable.
KEY_SALT = b"command-center/token-vault"
KEY_INFO = b"cc-token-vault-v1"

PENDING_SECONDS = 600
# An access token this close to its expiry is refreshed rather than handed out: a run
# that starts with it should be able to finish with it.
ACCESS_TOKEN_MARGIN = timedelta(minutes=5)
DEFAULT_ACCESS_SECONDS = 3600
ID_TOKEN_SKEW_SECONDS = 120
HTTP_TIMEOUT_SECONDS = 15.0
MAX_RETURN_TO = 2048
OUTCOME_KEYS = ("oauth", "oauth_error")

REASONS = ("not_connected", "expired", "revoked", "undecryptable")


class NeedsReconnect(Exception):
    """There is no usable token for this person, and only they can fix it, by connecting again."""

    MESSAGES = {
        "not_connected": "Connect your account so scheduled work can run as you.",
        "expired": "Your connection expired. Connect again to keep scheduled work running.",
        "revoked": "Your connection was revoked or replaced. Connect again to keep scheduled work running.",
        "undecryptable": "This app can no longer read your connection because its key changed. Connect again.",
    }

    def __init__(self, reason: str):
        self.reason = reason if reason in REASONS else "revoked"
        super().__init__(self.MESSAGES[self.reason])


class VaultError(Exception):
    """The vault can't answer, for a reason that isn't the person's to fix.

    `reason` is `not_set_up` (no client id, key or workspace) or `unavailable` (the
    workspace or the database didn't answer, or the integration refused the app). A
    run that hits this has failed; its owner doesn't need to reconnect.
    """

    def __init__(self, reason: str, message: str):
        self.reason = reason
        super().__init__(message)


class ConnectError(Exception):
    """A sign-in that didn't end with a stored token.

    `reason` goes back to the browser as `oauth_error`, so it is always one of the
    fixed words listed in the module docstring, never text from the IdP.
    """

    def __init__(self, reason: str, return_to: str = "/"):
        self.reason = reason
        self.return_to = return_to or "/"
        super().__init__(reason)


class TokenEndpointError(Exception):
    def __init__(self, error: str, description: str = "", status: int = 0):
        self.error = error
        self.description = description
        self.status = status
        super().__init__(f"{error}: {description}" if description else error)


class Undecryptable(Exception):
    """No vault key opens this value."""


# ------------------------------------------------------------------ identity and time

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def normalize_username(name: Optional[str]) -> str:
    """How the vault keys a person: case-insensitively, as `creator_stats.same_person`
    compares them, because SCIM isn't consistent about the case of an address."""
    return (name or "").strip().lower()


def _person(name: Optional[str]) -> str:
    """The normalized username, or "" for a caller who can't hold a connection: nobody
    resolved, or a service principal, which has no interactive sign-in to give."""
    user = normalize_username(name)
    if not user or user == "unknown" or caller_identity.is_application_id(user):
        return ""
    return user


def _seconds(value: Any, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default


# ------------------------------------------------------------------ the key

def derive_key(secret: str) -> bytes:
    """The Fernet key HKDF-SHA256 derives from `secret` with the vault's salt and info."""
    material = HKDF(algorithm=hashes.SHA256(), length=32, salt=KEY_SALT, info=KEY_INFO).derive(secret.encode("utf-8"))
    return base64.urlsafe_b64encode(material)


class KeyState(NamedTuple):
    #: The first key encrypts; any of them decrypts.
    keys: Tuple[bytes, ...]
    source: str  # "TOKEN_VAULT_KEY", "derived", or "" with a problem
    problem: str


def key_state() -> KeyState:
    explicit = (os.environ.get("TOKEN_VAULT_KEY") or "").strip()
    secret = (os.environ.get("DATABRICKS_CLIENT_SECRET") or "").strip()
    keys: List[bytes] = []
    if explicit:
        try:
            Fernet(explicit.encode("ascii"))
        except (ValueError, TypeError, UnicodeError):
            # Not quietly replaced by the derived key: tokens written under a key
            # nobody chose would all be lost the day the typo is fixed.
            return KeyState((), "", "TOKEN_VAULT_KEY is set but isn't a Fernet key (32 bytes, url-safe base64)")
        keys.append(explicit.encode("ascii"))
    if secret:
        keys.append(derive_key(secret))
    if not keys:
        return KeyState((), "", "A key for the token vault: set TOKEN_VAULT_KEY, or run where the app's "
                                "DATABRICKS_CLIENT_SECRET is available to derive one from")
    return KeyState(tuple(keys), "TOKEN_VAULT_KEY" if explicit else "derived", "")


def _cipher() -> MultiFernet:
    state = key_state()
    if not state.keys:
        raise VaultError("not_set_up", state.problem)
    return MultiFernet([Fernet(k) for k in state.keys])


def encrypt(text: str, cipher: Optional[MultiFernet] = None) -> str:
    return (cipher or _cipher()).encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token: str, cipher: Optional[MultiFernet] = None) -> str:
    try:
        return (cipher or _cipher()).decrypt((token or "").encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        raise Undecryptable() from None


# ------------------------------------------------------------------ configuration

_CLIENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


def client_id() -> Tuple[str, str]:
    """(client id, problem) from the `oauth_client_id` setting.

    Re-checked here, where it is used, like a `hosts` setting: a row can arrive by
    data migration without passing the form's check.
    """
    raw = settings_store.get_setting("oauth_client_id").strip()
    if not raw:
        return "", ""
    if not _CLIENT_ID.match(raw):
        return "", ("The OAuth client id in Settings isn't one an integration issues: expected letters, "
                    "digits, '.', '_' and '-' only")
    return raw, ""


def refresh_ttl_days() -> int:
    return settings_store.get_int_setting("oauth_refresh_ttl_days")


def workspace_url() -> str:
    """`https://<workspace host>` from DATABRICKS_HOST, which every App receives; "" without one."""
    raw = (os.environ.get("DATABRICKS_HOST") or "").strip().rstrip("/")
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme != "https" or not parts.hostname or "@" in parts.netloc:
        return ""
    return f"https://{parts.netloc}"


class _Config(NamedTuple):
    client_id: str
    client_secret: str
    workspace: str
    cipher: MultiFernet


def _config() -> _Config:
    cid, _ = client_id()
    keys = key_state()
    workspace = workspace_url()
    if not cid or not keys.keys or not workspace:
        raise VaultError("not_set_up", "Scheduling isn't set up in this app yet.")
    return _Config(
        client_id=cid,
        # Only a confidential client has one; the integration the setup guide asks
        # for is public, and PKCE stands in for the secret.
        client_secret=(os.environ.get("OAUTH_CLIENT_SECRET") or "").strip(),
        workspace=workspace,
        cipher=MultiFernet([Fernet(k) for k in keys.keys]),
    )


# ------------------------------------------------------------------ where the sign-in returns

_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}(?::[0-9]{1,5})?$")
_LOCAL = ("localhost", "127.0.0.1")


def _request_origin(forwarded_host: Optional[str], host: Optional[str], scheme: Optional[str]) -> str:
    proxied = (forwarded_host or "").split(",")[0].strip()
    if proxied and _HOST.match(proxied):
        local = proxied.split(":")[0].lower() in _LOCAL
        return f"{scheme if local and scheme in ('http', 'https') else ('http' if local else 'https')}://{proxied}"
    # Behind the Apps proxy the Host header is the container's own, so it only
    # names the app when this is a developer's machine.
    direct = (host or "").strip()
    if direct and _HOST.match(direct) and direct.split(":")[0].lower() in _LOCAL:
        return f"{scheme if scheme in ('http', 'https') else 'http'}://{direct}"
    return ""


def _derived_origin() -> str:
    """This app's address on AWS, from the env every App gets.

    AWS apps live at `https://<DATABRICKS_APP_NAME>-<DATABRICKS_WORKSPACE_ID>.aws.databricksapps.com`.
    Other clouds' addresses aren't confirmed to follow from the env alone, so there
    the request or `OAUTH_REDIRECT_URI` has to say.
    """
    name = (os.environ.get("DATABRICKS_APP_NAME") or "").strip().lower()
    workspace_id = (os.environ.get("DATABRICKS_WORKSPACE_ID") or "").strip()
    host = (urlsplit(workspace_url()).hostname or "").lower()
    if (re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", name) and re.fullmatch(r"[0-9]{6,20}", workspace_id)
            and host.endswith(".cloud.databricks.com")):
        return f"https://{name}-{workspace_id}.aws.databricksapps.com"
    return ""


def callback_url(forwarded_host: Optional[str] = None, host: Optional[str] = None,
                 scheme: Optional[str] = None) -> str:
    """The redirect URI, which must match one registered on the integration exactly.

    `OAUTH_REDIRECT_URI` wins when set. In a request, the proxy's X-Forwarded-Host is
    the address the browser used. Without one (the Setup card's check runs with no
    request) it is derived where that's known to work (`_derived_origin`). "" when
    none of those can say.
    """
    explicit = (os.environ.get("OAUTH_REDIRECT_URI") or "").strip()
    if explicit:
        return explicit
    origin = _request_origin(forwarded_host, host, scheme) or _derived_origin()
    return origin + CALLBACK_PATH if origin else ""


def safe_return_to(value: Any) -> Optional[str]:
    """`value` if it is a path on this app, else None.

    The callback redirects there, so anything that could leave the app would be an
    open redirect: an absolute URL, a scheme such as `javascript:`, a
    protocol-relative `//host`, or a backslash, which browsers read as a slash
    (`/\\host`). Spaces and control characters are refused too, because browsers
    strip some of them before parsing, which can turn `/\\t/host` into `//host`.
    ASCII only, since the browser sends a hash route percent-encoded anyway.
    """
    if not isinstance(value, str) or not value or len(value) > MAX_RETURN_TO:
        return None
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return None
    if any(not 0x21 <= ord(ch) <= 0x7E for ch in value):
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return None
    return value


def with_outcome(return_to: str, key: str, value: str) -> str:
    """`return_to` with `key=value` in its query string, ahead of any hash route.

    An earlier outcome is replaced, so a retry doesn't carry the last attempt's error.
    """
    target = safe_return_to(return_to) or "/"
    base, hashmark, fragment = target.partition("#")
    path, _, query = base.partition("?")
    pairs = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True) if k not in OUTCOME_KEYS]
    pairs.append((key, value))
    return f"{path}?{urlencode(pairs)}" + (f"#{fragment}" if hashmark else "")


# ------------------------------------------------------------------ PKCE, state and the id_token

def code_challenge(verifier: str) -> str:
    """RFC 7636 S256: base64url(SHA-256(verifier)), unpadded."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_pkce() -> Tuple[str, str]:
    """(verifier, challenge). 86 url-safe characters, inside RFC 7636's 43 to 128."""
    verifier = secrets.token_urlsafe(64)
    return verifier, code_challenge(verifier)


def authorize_url(workspace: str, client: str, redirect_uri: str, state: str, challenge: str, nonce: str) -> str:
    query = urlencode({
        "client_id": client,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "nonce": nonce,
    }, quote_via=quote)
    return f"{workspace}{AUTHORIZE_PATH}?{query}"


class Pending(NamedTuple):
    username: str
    verifier_enc: str
    nonce: str
    redirect_uri: str
    return_to: str
    created_at: datetime


def pending_problem(pending: Optional[Pending], username: str, now: datetime) -> Optional[str]:
    """Why a sign-in's state can't complete for `username`, or None when it can."""
    if pending is None:
        return "unknown or already used"
    created = _aware(pending.created_at)
    if created is None or (now - created).total_seconds() > PENDING_SECONDS:
        return "expired"
    if normalize_username(pending.username) != normalize_username(username):
        return "started by someone else"
    return None


def decode_jwt_payload(token: str) -> Dict[str, Any]:
    """The claims of a compact JWT, without checking its signature.

    Only for the id_token from our own token request: it came straight from the
    workspace over TLS, which OIDC Core 3.1.3.7 accepts in place of the signature.
    The claims that matter are checked by `check_id_token`.
    """
    parts = (token or "").split(".")
    if len(parts) != 3 or not parts[1]:
        raise ValueError("not a compact JWT")
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
    if not isinstance(claims, dict):
        raise ValueError("JWT payload isn't an object")
    return claims


IDENTITY_CLAIMS = ("email", "preferred_username", "sub")


def check_id_token(claims: Any, *, issuer: str, client: str, username: str, nonce: str = "",
                   now: Optional[datetime] = None) -> Optional[Tuple[str, str]]:
    """None when the id_token says this sign-in was `username`'s, else (reason, detail).

    `invalid_id_token` is a token not meant for this app or no longer valid;
    `identity_mismatch` a valid one naming someone else. The name is read from
    `email`, `preferred_username` and `sub`: Databricks puts the user name in `sub`
    on its access tokens, and its discovery document lists no `email` claim. A nonce
    in the token must be ours. A missing one is accepted, because the discovery
    document doesn't say the workspace echoes it, and PKCE already binds the code to
    this sign-in.
    """
    if not isinstance(claims, dict):
        return "invalid_id_token", "no claims"
    stamp = (now or _now()).timestamp()
    iss = str(claims.get("iss") or "").rstrip("/").lower()
    if iss != issuer.rstrip("/").lower():
        return "invalid_id_token", f"issued by {iss or 'nobody'}"
    aud = claims.get("aud")
    audiences = [str(a) for a in (aud if isinstance(aud, list) else [aud]) if a is not None]
    if client not in audiences:
        return "invalid_id_token", "issued to another client"
    if claims.get("azp") is not None and str(claims.get("azp")) != client:
        return "invalid_id_token", "authorized for another client"
    exp = claims.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)) or exp + ID_TOKEN_SKEW_SECONDS < stamp:
        return "invalid_id_token", "expired"
    nbf = claims.get("nbf")
    if isinstance(nbf, (int, float)) and not isinstance(nbf, bool) and nbf - ID_TOKEN_SKEW_SECONDS > stamp:
        return "invalid_id_token", "not valid yet"
    if claims.get("nonce") is not None and not (nonce and hmac.compare_digest(str(claims["nonce"]), nonce)):
        return "invalid_id_token", "nonce doesn't match"
    names = [normalize_username(str(claims.get(k) or "")) for k in IDENTITY_CLAIMS]
    if normalize_username(username) not in [n for n in names if n]:
        return "identity_mismatch", f"signed in to the workspace as someone else (claims: {', '.join(k for k, n in zip(IDENTITY_CLAIMS, names) if n)})"
    return None


# ------------------------------------------------------------------ expiry

def refresh_lifetime(body: Dict[str, Any]) -> Optional[int]:
    """Seconds the refresh token lasts, if the token response says; Databricks' doesn't promise to."""
    for key in ("refresh_token_expires_in", "refresh_expires_in"):
        seconds = _seconds(body.get(key), 0)
        if seconds:
            return seconds
    return None


def connection_expiry(issued_at: Any, stored_expiry: Any, ttl_days: int) -> Optional[datetime]:
    """When the stored refresh token stops working.

    What the workspace said when it issued the token, else its issue time plus the
    `oauth_refresh_ttl_days` setting. Counted from the token's own issue, which is
    when the person connected unless single-use rotation has since issued them a new
    one with a fresh lifetime.
    """
    stored = _aware(stored_expiry)
    if stored:
        return stored
    issued = _aware(issued_at)
    return issued + timedelta(days=ttl_days) if issued else None


def select_expiring(rows: Iterable[Tuple[str, Any, Any]], ttl_days: int, within_days: float,
                    now: datetime) -> List[Tuple[str, datetime]]:
    cutoff = now + timedelta(days=within_days)
    out = []
    for username, issued_at, stored_expiry in rows:
        expires = connection_expiry(issued_at, stored_expiry, ttl_days)
        if expires is not None and expires <= cutoff:
            out.append((username, expires))
    out.sort(key=lambda item: (item[1], item[0]))
    return out


def reconnect_reason(expires_at: Optional[datetime], now: datetime, description: str = "") -> str:
    """Whether a refresh the workspace refused (`invalid_grant`) ran out or was taken away.

    The error doesn't say reliably, so the expiry we counted decides, with the
    description as a hint.
    """
    if expires_at is not None and expires_at <= now + timedelta(hours=1):
        return "expired"
    if "expire" in (description or "").lower():
        return "expired"
    return "revoked"


# ------------------------------------------------------------------ storage

SQL_LOCK_TIMEOUT = "SET LOCAL lock_timeout = '20s'"
SQL_LOCK = (
    "SELECT refresh_token_enc, access_token_enc, access_expires_at, connected_at, refresh_issued_at, "
    "refresh_expires_at, status FROM user_oauth_tokens WHERE username = %s FOR UPDATE"
)
SQL_READ = (
    "SELECT connected_at, refresh_issued_at, refresh_expires_at, status "
    "FROM user_oauth_tokens WHERE username = %s"
)
SQL_CONNECTED = (
    "SELECT username, refresh_issued_at, refresh_expires_at FROM user_oauth_tokens WHERE status = 'connected'"
)
SQL_SAVE_REFRESH = (
    "UPDATE user_oauth_tokens SET refresh_token_enc = %s, refresh_issued_at = %s, refresh_expires_at = %s, "
    "access_token_enc = %s, access_expires_at = %s, status = 'connected', last_error = NULL, updated_at = %s "
    "WHERE username = %s"
)
SQL_MARK = (
    "UPDATE user_oauth_tokens SET status = %s, last_error = %s, access_token_enc = NULL, "
    "access_expires_at = NULL, updated_at = %s WHERE username = %s"
)
SQL_STORE = (
    "INSERT INTO user_oauth_tokens (username, refresh_token_enc, access_token_enc, access_expires_at, scopes, "
    "connected_at, refresh_issued_at, refresh_expires_at, status, last_error, updated_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'connected', NULL, %s) "
    "ON CONFLICT (username) DO UPDATE SET refresh_token_enc = EXCLUDED.refresh_token_enc, "
    "access_token_enc = EXCLUDED.access_token_enc, access_expires_at = EXCLUDED.access_expires_at, "
    "scopes = EXCLUDED.scopes, connected_at = EXCLUDED.connected_at, "
    "refresh_issued_at = EXCLUDED.refresh_issued_at, refresh_expires_at = EXCLUDED.refresh_expires_at, "
    "status = 'connected', last_error = NULL, updated_at = EXCLUDED.updated_at"
)
SQL_DELETE = "DELETE FROM user_oauth_tokens WHERE username = %s"
SQL_PENDING_PURGE = "DELETE FROM oauth_pending WHERE created_at < %s"
SQL_PENDING_ADD = (
    "INSERT INTO oauth_pending (state, username, verifier_enc, nonce, redirect_uri, return_to, created_at) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s)"
)
SQL_PENDING_TAKE = (
    "DELETE FROM oauth_pending WHERE state = %s "
    "RETURNING username, verifier_enc, nonce, redirect_uri, return_to, created_at"
)
SQL_PENDING_DROP_USER = "DELETE FROM oauth_pending WHERE username = %s"


def _connect():
    from database import get_db_connection

    return get_db_connection(settings_store.settings_env(), physical=True)


def _quietly(fn) -> None:
    try:
        fn()
    except Exception:  # noqa: BLE001 - a dropped connection rolls back and closes on its own
        pass


def _write(statements: List[Tuple[str, tuple]]) -> int:
    """Run `statements` in one transaction; the first one's row count."""
    conn = _connect()
    try:
        c = conn.cursor()
        counts = []
        for sql, params in statements:
            c.execute(sql, params)
            counts.append(c.rowcount)
        conn.commit()
        return counts[0] if counts else 0
    except Exception:
        _quietly(conn.rollback)
        raise
    finally:
        _quietly(conn.close)


# ------------------------------------------------------------------ the token endpoint

def _http_post(url: str, data: Dict[str, str], auth: Optional[Tuple[str, str]] = None) -> Tuple[int, Dict[str, Any]]:
    """POST a form to the token endpoint. Standalone tests replace this."""
    import httpx

    response = httpx.post(url, data=data, auth=auth, headers={"Accept": "application/json"},
                          timeout=HTTP_TIMEOUT_SECONDS)
    try:
        body = response.json()
    except ValueError:
        body = {}
    return response.status_code, body if isinstance(body, dict) else {}


def _token_request(cfg: _Config, form: Dict[str, str]) -> Dict[str, Any]:
    data = dict(form)
    auth = None
    if cfg.client_secret:
        auth = (cfg.client_id, cfg.client_secret)
    else:
        data["client_id"] = cfg.client_id
    try:
        status, body = _http_post(cfg.workspace + TOKEN_PATH, data, auth)
    except Exception as e:  # noqa: BLE001 - the workspace not answering is transient, never the person's to fix
        raise TokenEndpointError("unreachable", type(e).__name__) from None
    if status >= 400 or body.get("error"):
        raise TokenEndpointError(str(body.get("error") or f"http_{status}")[:64],
                                 str(body.get("error_description") or "")[:300], status)
    return body


# ------------------------------------------------------------------ what the scheduler calls

def access_token_for(username: str) -> str:
    """A current access token for `username`, refreshed (and a rotated refresh token
    saved) when needed.

    Raises NeedsReconnect when there's no usable token for them, and VaultError when
    the vault can't answer for a reason that isn't theirs. The person's row is held
    locked for the whole refresh, so two workers never spend one single-use token.
    """
    user = _person(username)
    if not user:
        raise NeedsReconnect("not_connected")
    cfg = _config()
    try:
        conn = _connect()
    except Exception as e:  # noqa: BLE001
        raise VaultError("unavailable", f"The token vault's database didn't answer ({type(e).__name__})") from None
    try:
        return _refresh_locked(conn, cfg, user)
    finally:
        _quietly(conn.close)


def _refresh_locked(conn, cfg: _Config, user: str) -> str:
    c = conn.cursor()
    try:
        # Bounded, so a refresh stuck behind another worker's fails as a run rather
        # than holding this thread.
        c.execute(SQL_LOCK_TIMEOUT)
        c.execute(SQL_LOCK, (user,))
        row = c.fetchone()
    except Exception as e:  # noqa: BLE001
        _quietly(conn.rollback)
        raise VaultError("unavailable", f"Couldn't read the stored token ({type(e).__name__})") from None
    if not row:
        _quietly(conn.rollback)
        raise NeedsReconnect("not_connected")
    refresh_enc, access_enc, access_expires_at, _connected_at, issued_at, stored_expiry, state = row
    if state != "connected":
        _quietly(conn.rollback)
        raise NeedsReconnect(state)

    now = _now()
    access_until = _aware(access_expires_at)
    if access_enc and access_until and access_until - now > ACCESS_TOKEN_MARGIN:
        try:
            token = decrypt(access_enc, cfg.cipher)
        except Undecryptable:
            token = ""  # the refresh token decides below
        if token:
            _quietly(conn.rollback)
            return token

    try:
        refresh = decrypt(refresh_enc, cfg.cipher)
    except Undecryptable:
        raise _give_up(conn, c, user, "undecryptable", "No vault key opens the stored token", now) from None
    try:
        body = _token_request(cfg, {"grant_type": "refresh_token", "refresh_token": refresh})
    except TokenEndpointError as e:
        if e.error == "invalid_grant":
            expires = connection_expiry(issued_at, stored_expiry, refresh_ttl_days())
            reason = reconnect_reason(expires, now, e.description)
            raise _give_up(conn, c, user, reason, e.description or e.error, now) from None
        _quietly(conn.rollback)
        raise VaultError("unavailable", f"The workspace didn't refresh the token ({e.error})") from None

    access = str(body.get("access_token") or "")
    if not access:
        _quietly(conn.rollback)
        raise VaultError("unavailable", "The workspace's refresh answer had no access token")
    access_until = now + timedelta(seconds=_seconds(body.get("expires_in"), DEFAULT_ACCESS_SECONDS))
    rotated = str(body.get("refresh_token") or "")
    if rotated and rotated != refresh:
        lifetime = refresh_lifetime(body)
        saved = (encrypt(rotated, cfg.cipher), now, now + timedelta(seconds=lifetime) if lifetime else None)
    else:
        saved = (refresh_enc, issued_at, stored_expiry)
    try:
        c.execute(SQL_SAVE_REFRESH, (*saved, encrypt(access, cfg.cipher), access_until, now, user))
        conn.commit()
    except Exception as e:  # noqa: BLE001
        _quietly(conn.rollback)
        # The access token is good for its hour whatever happened here, so this run
        # goes ahead. If the workspace rotated, the token it replaced is spent and the
        # next refresh will ask this person to reconnect.
        logger.error("Couldn't save %s's refreshed token (rotated: %s): %s", user, bool(rotated and rotated != refresh),
                     type(e).__name__)
    return access


def _give_up(conn, c, user: str, reason: str, detail: str, now: datetime) -> NeedsReconnect:
    """Mark the row as needing a reconnect; the NeedsReconnect for the caller to raise."""
    try:
        c.execute(SQL_MARK, (reason, (detail or "")[:500], now, user))
        conn.commit()
    except Exception as e:  # noqa: BLE001 - the next attempt reaches the same verdict
        _quietly(conn.rollback)
        logger.warning("Couldn't mark %s's connection as %s: %s", user, reason, type(e).__name__)
    else:
        activity.record(user, "oauth.needs_reconnect", "oauth", None, {"reason": reason})
    logger.info("%s's connection needs reconnecting: %s", user, reason)
    return NeedsReconnect(reason)


def _describe(row: Optional[tuple], ttl_days: int) -> Dict[str, Any]:
    if not row:
        return {"connected": False, "connected_at": None, "expires_at": None, "needs_reconnect": False,
                "reason": "not_connected"}
    connected_at, issued_at, stored_expiry, state = row
    ok = state == "connected"
    return {
        "connected": ok,
        "connected_at": _aware(connected_at),
        "expires_at": connection_expiry(issued_at, stored_expiry, ttl_days),
        "needs_reconnect": not ok,
        "reason": None if ok else (state if state in REASONS else "revoked"),
    }


def status(username: str) -> Dict[str, Any]:
    """`{connected, connected_at, expires_at, needs_reconnect, reason}` for `username`.

    `GET /api/oauth/status` returns the same. Reads only: nothing is decrypted or
    refreshed. `needs_reconnect` means a connection existed and stopped working;
    someone who never connected has `reason: not_connected` and nothing to reconnect.
    """
    user = _person(username)
    if not user:
        return _describe(None, 0)
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(SQL_READ, (user,))
        row = c.fetchone()
    finally:
        _quietly(conn.close)
    return _describe(row, refresh_ttl_days())


def expiring(within_days: float) -> List[Tuple[str, datetime]]:
    """`[(username, expires_at)]` for connected people whose connection ends within
    `within_days`, soonest first.

    One already past its expiry is included, so a reminder the scheduler missed isn't
    lost; the scheduler decides which reminders it has already sent.
    """
    conn = _connect()
    try:
        c = conn.cursor()
        c.execute(SQL_CONNECTED)
        rows = c.fetchall()
    finally:
        _quietly(conn.close)
    return select_expiring(rows, refresh_ttl_days(), within_days, _now())


# ------------------------------------------------------------------ connecting and disconnecting

def begin_connect(username: str, redirect_uri: str, return_to: str) -> str:
    """Record a sign-in for `username` and return the workspace URL to send them to."""
    target = safe_return_to(return_to) or "/"
    user = _person(username)
    if not user:
        raise ConnectError("not_signed_in", target)
    try:
        cfg = _config()
    except VaultError:
        raise ConnectError("not_set_up", target) from None
    if not redirect_uri:
        raise ConnectError("not_set_up", target)
    verifier, challenge = new_pkce()
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(16)
    now = _now()
    try:
        _write([
            (SQL_PENDING_PURGE, (now - timedelta(seconds=PENDING_SECONDS),)),
            # The verifier is encrypted like everything else the vault keeps, so a
            # reader of this table who also saw a code in flight couldn't redeem it.
            (SQL_PENDING_ADD, (state, user, encrypt(verifier, cfg.cipher), nonce, redirect_uri, target, now)),
        ])
    except Exception as e:  # noqa: BLE001
        logger.warning("Couldn't record %s's sign-in: %s", user, type(e).__name__)
        raise ConnectError("storage_failed", target) from None
    return authorize_url(cfg.workspace, cfg.client_id, redirect_uri, state, challenge, nonce)


def _take_pending(state: str) -> Optional[Pending]:
    """The sign-in `state` names, deleted as it is read so a state works once."""
    try:
        conn = _connect()
        try:
            c = conn.cursor()
            c.execute(SQL_PENDING_TAKE, (state[:256],))
            row = c.fetchone()
            conn.commit()
        except Exception:
            _quietly(conn.rollback)
            raise
        finally:
            _quietly(conn.close)
    except Exception as e:  # noqa: BLE001
        logger.warning("Couldn't read a sign-in's state: %s", type(e).__name__)
        raise ConnectError("storage_failed") from None
    return Pending(*row) if row else None


def complete_connect(username: str, *, code: str, state: str, error: str = "") -> str:
    """Finish the sign-in the workspace sent back; returns where to send the browser.

    Stores the refresh token only when the state is this caller's, unexpired and
    unused, the code exchange succeeds, and the id_token names this caller.
    """
    user = _person(username)
    if not user:
        raise ConnectError("not_signed_in")
    if not state:
        raise ConnectError("invalid_state")
    now = _now()
    pending = _take_pending(state)
    problem = pending_problem(pending, user, now)
    if problem:
        logger.info("Sign-in for %s refused: its state is %s", user, problem)
        raise ConnectError("invalid_state", "/" if pending is None or problem.startswith("started") else pending.return_to)
    target = safe_return_to(pending.return_to) or "/"
    if error:
        logger.info("Sign-in for %s ended at the workspace: %s", user, error[:64])
        raise ConnectError("denied" if error == "access_denied" else "idp_error", target)
    try:
        cfg = _config()
    except VaultError:
        raise ConnectError("not_set_up", target) from None
    if not code:
        raise ConnectError("exchange_failed", target)
    try:
        verifier = decrypt(pending.verifier_enc, cfg.cipher)
    except Undecryptable:
        raise ConnectError("invalid_state", target) from None

    try:
        body = _token_request(cfg, {"grant_type": "authorization_code", "code": code,
                                    "redirect_uri": pending.redirect_uri, "code_verifier": verifier})
    except TokenEndpointError as e:
        logger.warning("Sign-in for %s: the code exchange failed (%s %s)", user, e.error, e.description)
        raise ConnectError("exchange_failed", target) from None
    id_token = str(body.get("id_token") or "")
    if not id_token:
        raise ConnectError("no_id_token", target)
    try:
        claims = decode_jwt_payload(id_token)
    except (ValueError, UnicodeError):
        raise ConnectError("invalid_id_token", target) from None
    verdict = check_id_token(claims, issuer=cfg.workspace + ISSUER_PATH, client=cfg.client_id, username=user,
                             nonce=pending.nonce, now=now)
    if verdict:
        logger.warning("Sign-in for %s refused: %s (%s)", user, verdict[0], verdict[1])
        raise ConnectError(verdict[0], target)
    refresh = str(body.get("refresh_token") or "")
    if not refresh:
        raise ConnectError("no_refresh_token", target)

    access = str(body.get("access_token") or "")
    access_until = now + timedelta(seconds=_seconds(body.get("expires_in"), DEFAULT_ACCESS_SECONDS)) if access else None
    lifetime = refresh_lifetime(body)
    scopes = " ".join(str(body.get("scope") or SCOPE).split())[:500]
    try:
        _write([(SQL_STORE, (
            user, encrypt(refresh, cfg.cipher), encrypt(access, cfg.cipher) if access else None, access_until,
            scopes, now, now, now + timedelta(seconds=lifetime) if lifetime else None, now,
        ))])
    except Exception as e:  # noqa: BLE001
        logger.error("Couldn't store %s's connection: %s", user, type(e).__name__)
        raise ConnectError("storage_failed", target) from None
    activity.record(user, "oauth.connect", "oauth", None, {"scopes": scopes})
    return target


def disconnect(username: str) -> bool:
    """Forget `username`'s connection; whether there was one.

    The workspace's OAuth discovery document advertises no revocation endpoint, so
    the token is deleted rather than revoked: no copy is left for anything to use,
    and the workspace lets it lapse at its own expiry.
    """
    user = _person(username)
    if not user:
        return False
    removed = _write([(SQL_DELETE, (user,)), (SQL_PENDING_DROP_USER, (user,))]) > 0
    if removed:
        activity.record(user, "oauth.disconnect", "oauth")
    return removed


def purge_pending() -> None:
    """Drop sign-ins nobody finished. Runs on the background runner; `begin_connect`
    also purges as it goes."""
    _write([(SQL_PENDING_PURGE, (_now() - timedelta(seconds=PENDING_SECONDS),))])


# ------------------------------------------------------------------ the Setup card

def capability() -> Dict[str, Any]:
    """The `scheduling` check: an OAuth client id, a vault key and a workspace."""
    cid, cid_problem = client_id()
    keys = key_state()
    workspace = workspace_url()
    ttl = refresh_ttl_days()
    redirect = callback_url() or f"https://<this app's address>{CALLBACK_PATH}"

    missing: List[str] = []
    if cid_problem:
        missing.append(cid_problem)
    elif not cid:
        missing.append(f"A custom OAuth app integration for this app: a public client (no client secret) with the "
                       f"scopes {', '.join(SCOPES)}, the redirect URL {redirect}, and a {ttl}-day refresh-token "
                       f"lifetime")
        missing.append("Its client id, in Admin Panel → Settings → Scheduling → OAuth client id")
    if keys.problem:
        missing.append(keys.problem)
    if not workspace:
        missing.append("DATABRICKS_HOST, the workspace this app belongs to")

    if cid_problem or not cid:
        next_step = (f"An account admin opens the account console → Settings → App connections → Add connection, "
                     f"picks the SQL access scope, leaves Generate a client secret off, adds the redirect URL "
                     f"{redirect}, and sets the refresh token TTL to {ttl * 1440} minutes. Paste the client id it "
                     f"shows under Scheduling on this page.")
    elif keys.problem:
        next_step = ("Give the app a valid TOKEN_VAULT_KEY (generate one with "
                     "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`) "
                     "as a secret resource, or remove it to use the key derived from the app's own secret.")
    elif not workspace:
        next_step = "Set DATABRICKS_HOST to the workspace's URL; every Databricks App has it, so this is a local run."
    elif keys.source == "derived":
        next_step = ("Optional: set TOKEN_VAULT_KEY as a secret resource, so rotating the app's own secret "
                     "doesn't make everyone reconnect.")
    else:
        next_step = ""
    return capabilities.result(not missing, missing=missing, next_step=next_step)
