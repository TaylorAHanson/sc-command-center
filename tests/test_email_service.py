"""Tests for email through Amazon SES (services/email_service.py).

No network and no database: settings come from a stand-in for the settings
table, SES is a fake client, and email_log is a fake connection that records
every statement. Pinned here:

- the recipient policy: addresses normalized, malformed ones refused, only the
  sender's own domain until an admin lists others, and the caps;
- that the Markdown renderer escapes everything it doesn't understand, links
  only to http/https/mailto, never draws an image, and caps a table;
- the CSV attachment, including the spreadsheet-formula guard;
- which transport runs (SES, the local log, or off) for each combination of
  setup, and what the `email` capability tells an admin;
- that the log row is written before SES is called, holds no body, and that
  refusals, the daily cap, a failed log write and a failed send all behave.
"""
import csv
import io
import logging
import os
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

try:
    import database
    from services import capabilities, email_service as es, settings_store
except Exception as e:  # pragma: no cover - needs the backend venv
    print(f"SKIP test_email_service: {e}")
    sys.exit(0)

ME = "ana@example.com"
FROM = "command-center@example.com"
SES_ENV = {"AWS_ACCESS_KEY_ID": "AKIATEST", "AWS_SECRET_ACCESS_KEY": "secret-test", "AWS_REGION": "us-east-1",
           "AWS_DEFAULT_REGION": None, "APP_ENVIRONMENT": "prod"}
NO_SES_ENV = {"AWS_ACCESS_KEY_ID": None, "AWS_SECRET_ACCESS_KEY": None, "AWS_REGION": None,
              "AWS_DEFAULT_REGION": None}
EMAIL_ENV_VARS = [spec.env for key, spec in settings_store.SETTING_SPECS.items() if key.startswith("email_")]


@contextmanager
def configured(rows=None, env=None):
    """Settings rows and process env as given; every email env var cleared
    unless named, so the developer's own shell can't leak in."""
    env = {**{name: None for name in EMAIL_ENV_VARS}, **(env or {})}
    original_reader = settings_store._read_rows
    original_env = {key: os.environ.get(key) for key in env}
    settings_store._read_rows = lambda: dict(rows or {})
    settings_store.invalidate()
    for key, value in env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        settings_store._read_rows = original_reader
        settings_store.invalidate()
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class FakeConn:
    """email_log and activity_events, as far as email_service writes them."""

    def __init__(self, sent_today=0, fail_on=None):
        self.sent_today = sent_today
        self.fail_on = fail_on
        self.statements = []
        self.commits = 0
        self.next_id = 100

    def cursor(self):
        conn = self

        class C:
            def __init__(self):
                self.result = None

            def execute(self, sql, params=None):
                text = " ".join(sql.split())
                if conn.fail_on and conn.fail_on in text:
                    raise RuntimeError("connection reset")
                conn.statements.append((text, params))
                if text.startswith("SELECT COUNT(*) FROM email_log"):
                    self.result = (conn.sent_today,)
                elif "RETURNING id" in text:
                    conn.next_id += 1
                    self.result = (conn.next_id,)

            def fetchone(self):
                return self.result

        return C()

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass

    def of(self, prefix):
        return [params for text, params in self.statements if text.startswith(prefix)]


class FakeSES:
    def __init__(self, conn=None, error=None):
        self.calls = []
        self.conn = conn
        self.error = error
        self.log_rows_at_call = None

    def send_email(self, **kwargs):
        if self.conn is not None:
            self.log_rows_at_call = list(self.conn.of("INSERT INTO email_log"))
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"MessageId": "0100-abc"}


class ClientError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


@contextmanager
def wired(conn, ses):
    original_conn, original_client = database.get_db_connection, es._ses_client
    database.get_db_connection = lambda *a, **k: conn
    es._ses_client = lambda: ses
    try:
        yield
    finally:
        database.get_db_connection, es._ses_client = original_conn, original_client


SES_READY = {"email_from_address": FROM}


# --- addresses and the recipient policy -------------------------------------

def test_addresses_are_normalized():
    assert es.normalize_address("  Ana@Example.COM ") == ME
    assert es.normalize_address("first.last+tag@sub.example.co.uk") == "first.last+tag@sub.example.co.uk"


def test_malformed_addresses_are_refused():
    for bad in ["", "ana", "ana@", "@example.com", "ana@example", "ana@@example.com", "ana example@example.com",
                "ana@exa_mple.com", "ana@example.com\r\nBcc: eve@evil.com", '"ana"@example.com', "a..b@example.com",
                ".ana@example.com", "ana@-example.com", "ana@example.c", "x" * 65 + "@example.com", None, 42]:
        assert es.normalize_address(bad) is None, bad


def test_pasted_lists_are_split_and_deduplicated():
    good, bad = es.parse_recipients(
        'Ana <ana@example.com>, "Doe, Jane" <jane@example.com>; bob@example.com\nANA@example.com cy@example.com')
    assert good == [ME, "jane@example.com", "bob@example.com", "cy@example.com"]
    assert bad == []
    assert es.parse_recipients(["bob@example.com", " Bob@Example.com "]) == (["bob@example.com"], [])


def test_rejected_entries_come_back_as_typed():
    good, bad = es.parse_recipients("bob@example.com, not-an-address, Eve <eve@>")
    assert good == ["bob@example.com"]
    assert bad == ["not-an-address", "Eve <eve@>"]
    check = es.check_recipients("bob@example.com, nope", ME, [], 10)
    assert check.reason == "bad_address" and "nope" in check.problem


def test_without_an_allowlist_only_the_senders_own_domain():
    assert es.check_recipients(["bob@example.com"], ME, [], 10).problem is None
    outside = es.check_recipients(["bob@example.com", "eve@other.com"], ME, [], 10)
    assert outside.reason == "domain_not_allowed"
    assert "eve@other.com" in outside.problem and "example.com" in outside.problem
    # Exactly the sender's domain: a subdomain is somewhere else.
    assert es.check_recipients(["bob@eu.example.com"], ME, [], 10).reason == "domain_not_allowed"


def test_an_allowlist_replaces_the_default():
    allowed = ["partner.com", "*.example.com"]
    assert es.check_recipients(["a@partner.com", "b@eu.example.com"], ME, allowed, 10).problem is None
    assert es.check_recipients(["a@example.com"], ME, allowed, 10).reason == "domain_not_allowed"
    assert es.check_recipients(["a@notexample.com"], ME, allowed, 10).reason == "domain_not_allowed"
    assert es.check_recipients(["a@evil.partner.com"], ME, allowed, 10).reason == "domain_not_allowed"


def test_the_recipient_count_is_capped():
    eleven = [f"p{i}@example.com" for i in range(11)]
    check = es.check_recipients(eleven, ME, [], 10)
    assert check.reason == "too_many_recipients" and "10" in check.problem
    assert es.check_recipients(eleven[:10], ME, [], 10).problem is None
    sixty = [f"p{i}@example.com" for i in range(60)]
    assert es.check_recipients(sixty, ME, [], 500).reason == "too_many_recipients"


def test_no_recipients_and_no_sender_address_are_refused():
    assert es.check_recipients([], ME, [], 10).reason == "no_recipients"
    assert es.check_recipients("  ", ME, [], 10).reason == "no_recipients"
    # A service principal's id has no domain to default to.
    assert es.check_recipients(["bob@example.com"], "4f6e0a7c-0000-4000-8000-000000000000", [], 10).reason == "no_sender"


def test_domain_entries_are_checked():
    assert es.parse_domain_entry(" Example.com ") == ("example.com", None)
    assert es.parse_domain_entry("@example.com") == ("example.com", None)
    assert es.parse_domain_entry("*.Example.com") == ("*.example.com", None)
    for bad in ["*", "*.com", "example", "http://example.com", "exa mple.com", "ex*ample.com"]:
        assert es.parse_domain_entry(bad)[1], bad
    # Read back leniently: a bad entry is dropped, not allowed and not fatal.
    assert es.allowed_domain_list("example.com, *.partner.co.uk\nbad entry *\nexample.com") == [
        "example.com", "*.partner.co.uk"]


def test_settings_validate_the_new_kinds():
    assert settings_store.validate_value("email_from_address", " CC@Example.com ") == ("cc@example.com", None)
    assert settings_store.validate_value("email_from_address", "Command Center <cc@example.com>")[1]
    assert settings_store.validate_value("email_allowed_domains", "Example.com, *.partner.co.uk\nexample.com") == (
        "example.com\n*.partner.co.uk", None)
    cleaned, error = settings_store.validate_value("email_allowed_domains", "example.com\n*")
    assert cleaned == "" and "*" in error
    assert settings_store.validate_value("email_max_recipients", "51")[1]
    assert settings_store.validate_value("email_daily_limit", "0")[1]
    assert settings_store.validate_value("email_enabled", "off") == ("false", None)


def test_email_settings_have_their_own_group():
    groups = {g["key"] for g in settings_store.SETTING_GROUPS}
    keys = ["email_enabled", "email_from_address", "email_allowed_domains", "email_max_recipients",
            "email_daily_limit"]
    assert "email" in groups
    assert all(settings_store.SETTING_SPECS[k].group == "email" for k in keys)
    # The keys and region are the deployment's secrets, never a setting.
    assert not any("aws" in k or "region" in k for k in settings_store.SETTING_SPECS)
    with configured():
        assert es.current_settings() == es.Settings(True, "", [], 10, 50)


# --- Markdown ----------------------------------------------------------------

def test_script_tags_and_raw_html_are_escaped():
    out = es.render_markdown('<script>alert(1)</script>\n\n<img src=x onerror="alert(1)">')
    assert "<script" not in out and "<img" not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    assert "onerror=&quot;alert(1)&quot;" in out


def test_links_only_to_safe_schemes():
    out = es.render_markdown("[docs](https://example.com/a?b=1&c=2) and [mail](mailto:bob@example.com)")
    assert '<a href="https://example.com/a?b=1&amp;c=2"' in out
    assert '<a href="mailto:bob@example.com"' in out
    for url in ["javascript:alert(1)", "data:text/html,hi", "vbscript:x", "//evil.example/x", "/relative"]:
        out = es.render_markdown(f"[click]({url})")
        assert "href" not in out and "click" in out, url


def test_a_link_cannot_break_out_of_its_attribute():
    out = es.render_markdown('[x](https://a.example/"onmouseover=alert(1))')
    assert 'href="https://a.example/"' not in out
    assert '"onmouseover' not in out


def test_images_never_load():
    out = es.render_markdown("![chart](https://tracker.example/pixel.png?u=ana)")
    assert "<img" not in out
    assert '<a href="https://tracker.example/pixel.png?u=ana"' in out


def test_block_and_inline_forms():
    md = ("# Q3 results\n\nRevenue is **up** and costs are *down*.\nSecond line.\n\n"
          "- one\n- two\n\n1. first\n2. second\n\n> quoted\n\n---\n\n"
          "```\n<b>not html</b>\n```\n\nUse `<b>` and `**not bold**`; snake_case_name stays.\n\n# C#")
    out = es.render_markdown(md)
    assert '<h1 style="' in out and "Q3 results</h1>" in out
    assert "<strong>up</strong>" in out and "<em>down</em>" in out
    assert "costs are <em>down</em>.<br>Second line." in out
    assert out.count("<li ") == 4 and "<ul " in out and "<ol " in out
    assert "<blockquote " in out and "<hr " in out
    assert "&lt;b&gt;not html&lt;/b&gt;</pre>" in out
    assert ">&lt;b&gt;</code>" in out and ">**not bold**</code>" in out
    assert "snake_case_name" in out and out.count("<em>") == 1
    assert "C#</h1>" in out


def test_nul_bytes_cannot_forge_a_placeholder():
    out = es.render_markdown("\x000\x00 [x](javascript:alert(1)) `\x000\x00`")
    assert "href" not in out and "\x00" not in out and "javascript" not in out
    assert ">0 x <code" in out


def test_link_targets_may_hold_parentheses():
    out = es.render_markdown("[wiki](https://en.wikipedia.org/wiki/Margin_(finance)) after")
    assert '<a href="https://en.wikipedia.org/wiki/Margin_(finance)"' in out and "</a> after" in out


# --- tables and the CSV -------------------------------------------------------

def table(n, columns=("Region", "Revenue")):
    return {"columns": list(columns), "rows": [[f"R{i}", i * 10] for i in range(n)]}


def test_the_table_in_the_body_is_capped():
    t = es.normalize_table(table(120))
    out = es.table_html(t)
    assert out.count("<tr>") == es.TABLE_MAX_ROWS + 1
    assert "Showing 50 of 120 rows." in out
    with_csv = es.table_html(t, csv_rows=120)
    assert "The attached CSV has them all." in with_csv
    assert es.table_html(es.normalize_table(table(3))).count("<tr>") == 4


def test_table_cells_are_escaped_and_shortened():
    t = es.normalize_table({"columns": ["<b>x</b>"], "rows": [["<script>alert(1)</script>"], ["y" * 500]]})
    out = es.table_html(t)
    assert "<script" not in out and "&lt;script&gt;" in out and "&lt;b&gt;x&lt;/b&gt;" in out
    assert "y" * es.TABLE_CELL_CHARS not in out and "…" in out


def test_rows_may_be_objects_and_values_any_json():
    t = es.normalize_table({"rows": [{"a": 1, "b": None}, {"b": True, "c": {"k": [1]}}]})
    assert t.columns == ["a", "b", "c"]
    assert t.rows == [["1", "", ""], ["", "true", '{"k":[1]}']]
    padded = es.normalize_table({"columns": ["a", "b"], "rows": [[1], [1, 2, 3]]})
    assert padded.rows == [["1", ""], ["1", "2"]]


def test_unreadable_tables_are_refused():
    for bad in ["text", {"rows": "x"}, {"columns": "a", "rows": []}, {"rows": [[1, 2]]}, {"columns": ["a"], "rows": [5]}]:
        try:
            es.normalize_table(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    assert es.normalize_table(None) is None and es.normalize_table({}) is None
    wide = es.normalize_table({"columns": [f"c{i}" for i in range(60)], "rows": [list(range(60))]})
    assert len(wide.columns) == es.MAX_COLUMNS and wide.dropped_columns == 10
    assert "10 more columns left out." in es.table_html(wide)


def test_the_csv_attachment():
    t = es.normalize_table({"columns": ["Name", "Note", "Delta"], "rows": [
        ["Ana", "=HYPERLINK(\"http://evil\")", "-5"],
        ["Bob, Jr.", 'says "hi"\nthen leaves', "+cmd"],
        ["@SUM(A1)", "-x", "1e5"],
    ]})
    data, rows = es.table_csv(t)
    assert rows == 3 and data.startswith("\ufeff".encode("utf-8"))
    parsed = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert parsed[0] == ["Name", "Note", "Delta"]
    assert parsed[1] == ["Ana", "'=HYPERLINK(\"http://evil\")", "-5"]
    assert parsed[2] == ["Bob, Jr.", 'says "hi"\nthen leaves', "'+cmd"]
    assert parsed[3] == ["'@SUM(A1)", "'-x", "1e5"]


def test_the_csv_stops_at_its_size_cap():
    original = es.CSV_MAX_BYTES
    es.CSV_MAX_BYTES = 200
    try:
        data, rows = es.table_csv(es.normalize_table(table(100)))
    finally:
        es.CSV_MAX_BYTES = original
    assert 0 < rows < 100 and len(data) <= 200
    assert len(list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))) == rows + 1


def test_the_attachment_is_named_after_the_subject():
    assert es.csv_filename("Q3 Revenue — by Region!") == "q3-revenue-by-region.csv"
    assert es.csv_filename("") == "table.csv"
    rendered = es.build_email("Q3 Revenue", "Hi", es.normalize_table(table(60)), True, ME)
    name, data, rows = rendered.attachment
    assert name == "q3-revenue.csv" and rows == 60
    assert "The attached CSV has them all." in rendered.html and "Attached: q3-revenue.csv" in rendered.text
    assert es.build_email("Q3", "Hi", es.normalize_table(table(3)), False, ME).attachment is None


# --- the whole email ------------------------------------------------------------

def test_a_subject_cannot_add_headers():
    assert es.clean_line("Hi\r\nBcc: eve@evil.com", 200) == "Hi Bcc: eve@evil.com"
    long = es.clean_line("word " * 100, es.MAX_SUBJECT_CHARS)
    assert len(long) == es.MAX_SUBJECT_CHARS and long.endswith("…")


def test_the_view_link_must_be_this_app():
    link = "https://cc.example.com/#/app/sales/q3"
    assert es.own_view_link(link, origin="https://cc.example.com") == link
    assert es.own_view_link(link, origin="https://CC.example.com") == link
    assert es.own_view_link(link, host="cc.example.com") == link
    for bad, origin in [("https://evil.example/#/app/x", "https://cc.example.com"),
                        ("http://cc.example.com/#/app/x", "https://cc.example.com"),
                        ("javascript:alert(1)", "https://cc.example.com"),
                        ("https://user:pw@cc.example.com/", "https://cc.example.com"),
                        ("https://cc.example.com/\r\nx", "https://cc.example.com"),
                        (link, "")]:
        assert es.own_view_link(bad, origin=origin) == "", bad


def test_the_footer_names_the_sender_and_the_view():
    rendered = es.build_email("Q3", "Numbers", None, False, ME, "Sales <Q3>", "https://cc.example.com/#/app/sales")
    assert f'href="mailto:{ME}"' in rendered.html and "from Sales &lt;Q3&gt;" in rendered.html
    assert '<a href="https://cc.example.com/#/app/sales"' in rendered.html and "Open Sales &lt;Q3&gt;" in rendered.html
    assert f"Sent by {ME} from Sales <Q3> using Command Center." in rendered.text
    assert "Open Sales <Q3>: https://cc.example.com/#/app/sales" in rendered.text


# --- transport and the capability -------------------------------------------------

def test_which_transport_runs():
    K, R, F = es.MISSING_KEYS, es.MISSING_REGION, es.MISSING_FROM
    cases = [
        ((True, FROM, True, "us-east-1", "prod"), ("ses", [])),
        ((True, FROM, True, "us-east-1", "local"), ("ses", [])),
        ((True, "", True, "us-east-1", "local"), ("log", [F])),
        ((True, "", False, "", "LOCAL"), ("log", [K, R, F])),
        ((True, "", False, "", "prod"), ("off", [K, R, F])),
        ((True, FROM, False, "us-east-1", "dev"), ("off", [K])),
        ((True, FROM, True, "", "stage"), ("off", [R])),
        ((True, FROM, True, "us-east-1", ""), ("ses", [])),
        ((True, "", True, "us-east-1", ""), ("off", [F])),
        ((False, FROM, True, "us-east-1", "prod"), ("off", [es.MISSING_ENABLED])),
        ((False, "", False, "", "local"), ("off", [es.MISSING_ENABLED, K, R, F])),
    ]
    for args, expected in cases:
        assert es.choose_transport(*args) == expected, args


def test_only_env_keys_count_as_credentials():
    assert not es.aws_keys_present({})
    assert not es.aws_keys_present({"AWS_ACCESS_KEY_ID": "AKIA"})
    assert not es.aws_keys_present({"AWS_ACCESS_KEY_ID": "AKIA", "AWS_SECRET_ACCESS_KEY": "  "})
    assert es.aws_keys_present({"AWS_ACCESS_KEY_ID": "AKIA", "AWS_SECRET_ACCESS_KEY": "s"})
    assert es.aws_region({"AWS_DEFAULT_REGION": "eu-west-1"}) == "eu-west-1"
    assert es.aws_region({"AWS_REGION": "us-east-1", "AWS_DEFAULT_REGION": "eu-west-1"}) == "us-east-1"


def test_the_capability_says_what_to_do():
    with configured(SES_READY, SES_ENV):
        assert es.capability() == capabilities.result(True, mode="ses")
    with configured({}, {**NO_SES_ENV, "APP_ENVIRONMENT": "local"}):
        res = es.capability()
        assert res["available"] and res["mode"] == "log"
        assert res["missing"] == [es.MISSING_KEYS, es.MISSING_REGION, es.MISSING_FROM]
        assert "backend.log" in res["next_step"]
    with configured({}, {**NO_SES_ENV, "APP_ENVIRONMENT": "prod"}):
        res = es.capability()
        assert not res["available"] and res["mode"] is None
        assert "ses:SendEmail" in res["next_step"] and "secret" in res["next_step"]
    with configured({}, {**SES_ENV}):
        res = es.capability()
        assert not res["available"] and res["missing"] == [es.MISSING_FROM]
        assert "From address" in res["next_step"]
    with configured({**SES_READY, "email_enabled": "false"}, SES_ENV):
        res = es.capability()
        assert not res["available"] and res["missing"][0] == es.MISSING_ENABLED
        assert res["next_step"].startswith("Turn on Allow email")


def test_the_capability_is_registered_by_startup():
    source = open(os.path.join(os.path.dirname(__file__), "..", "server", "main.py")).read()
    assert 'capabilities.register("email", "Email", email_service.capability)' in source
    assert 'prefix="/api/email"' in source


# --- sending and the log ----------------------------------------------------------

def send(**overrides):
    args = dict(sender_username=ME, sender_email=ME, to=["bob@example.com"], subject="Q3 numbers",
                message_md="Revenue is **up**. Secret plan inside.", table=table(3), attach_csv=True,
                view_name="Sales", view_link="https://cc.example.com/#/app/sales", request_id="req-1")
    args.update(overrides)
    return es.send_email(**args)


def test_a_send_is_logged_first_then_sent_through_ses():
    conn = FakeConn()
    ses = FakeSES(conn)
    with configured(SES_READY, SES_ENV), wired(conn, ses):
        result = send()
    assert result == {"ok": True, "status": "sent", "reason": None, "transport": "ses", "message_id": "0100-abc",
                      "recipients": ["bob@example.com"], "error": None, "log_id": 101}
    # The row existed, as `sending`, before SES was asked.
    assert len(ses.log_rows_at_call) == 1 and ses.log_rows_at_call[0][4] == "sending"
    call = ses.calls[0]
    assert call["FromEmailAddress"] == f"Command Center <{FROM}>"
    assert call["ReplyToAddresses"] == [ME]
    assert call["Destination"] == {"ToAddresses": ["bob@example.com"]}
    simple = call["Content"]["Simple"]
    assert simple["Subject"]["Data"] == "Q3 numbers"
    assert "<strong>up</strong>" in simple["Body"]["Html"]["Data"]
    assert simple["Attachments"][0]["FileName"] == "q3-numbers.csv"
    assert simple["Attachments"][0]["RawContent"].startswith("\ufeff".encode("utf-8"))
    texts = [t for t, _ in conn.statements]
    assert texts[0] == "SELECT pg_advisory_xact_lock(%s)"
    sender, sender_email, recipients, subject, status, transport, source, view, req, has_table, has_att, err = \
        conn.of("INSERT INTO email_log")[0]
    assert (sender, sender_email, recipients, subject, status) == (ME, ME, ["bob@example.com"], "Q3 numbers", "sending")
    assert (transport, source, view, req, has_table, has_att, err) == ("ses", "widget", "Sales", "req-1", True, True, None)
    assert conn.of("UPDATE email_log") == [("sent", "0100-abc", None, 101)]
    # Neither the log nor the activity event carries the body.
    every_param = repr(conn.statements)
    assert "Secret plan" not in every_param and "Revenue" not in every_param
    activity = conn.of("INSERT INTO activity_events")
    assert len(activity) == 1 and activity[0][1] == "email.send" and activity[0][3] == "101"
    assert '"via": "widget"' in activity[0][4] and '"status": "sent"' in activity[0][4]


def test_the_ses_request_matches_the_sesv2_model():
    # botocore's Stubber validates parameters against the service model offline,
    # which a hand-written fake can't: a misspelt key would pass the fake and
    # fail against SES.
    from botocore.stub import Stubber
    es._client.clear()
    try:
        with configured(SES_READY, SES_ENV):
            client = es._ses_client()
            assert client.meta.region_name == "us-east-1" and client.meta.service_model.service_name == "sesv2"
            assert client is es._ses_client()
            rendered = es.build_email("Q3", "Hi", es.normalize_table(table(2)), True, ME)
            with Stubber(client) as stub:
                stub.add_response("send_email", {"MessageId": "0100-stub"})
                assert es._send_ses(rendered, FROM, ME, ["bob@example.com"]) == "0100-stub"
                stub.assert_no_pending_responses()
    finally:
        es._client.clear()


def test_a_policy_refusal_is_logged_and_nothing_is_sent():
    conn = FakeConn()
    ses = FakeSES()
    with configured(SES_READY, SES_ENV), wired(conn, ses):
        result = send(to=["bob@example.com", "eve@other.com"])
    assert not result["ok"] and result["status"] == "refused" and result["reason"] == "domain_not_allowed"
    assert "eve@other.com" in result["error"]
    assert ses.calls == []
    assert conn.of("INSERT INTO email_log")[0][4] == "refused"
    assert conn.of("INSERT INTO email_log")[0][11] == "domain_not_allowed"
    assert not conn.of("SELECT pg_advisory_xact_lock")


def test_the_daily_cap_refuses_before_sending():
    conn = FakeConn(sent_today=50)
    ses = FakeSES()
    with configured(SES_READY, SES_ENV), wired(conn, ses):
        result = send()
    assert result["status"] == "refused" and result["reason"] == "daily_limit" and "50" in result["error"]
    assert ses.calls == []
    statuses = [row[4] for row in conn.of("INSERT INTO email_log")]
    assert statuses == ["refused"]
    with configured({**SES_READY, "email_daily_limit": "60"}, SES_ENV), wired(FakeConn(sent_today=50), FakeSES()):
        assert send()["ok"]


def test_a_log_that_cannot_be_written_means_no_send():
    conn = FakeConn(fail_on="INSERT INTO email_log")
    ses = FakeSES()
    with configured(SES_READY, SES_ENV), wired(conn, ses):
        result = send()
    assert result["status"] == "failed" and result["reason"] == "log_unavailable"
    assert ses.calls == []


def test_a_failed_send_is_recorded_with_ses_reason():
    conn = FakeConn()
    ses = FakeSES(error=ClientError("MessageRejected", "Email address is not verified: command-center@example.com"))
    with configured(SES_READY, SES_ENV), wired(conn, ses):
        result = send()
    assert result["status"] == "failed" and not result["ok"]
    assert "not verified" in result["error"]
    status, message_id, error, log_id = conn.of("UPDATE email_log")[0]
    assert status == "failed" and message_id is None and "not verified" in error
    denied = es.ses_error_message(ClientError("AccessDeniedException", "not authorized to perform ses:SendEmail"))
    assert "IAM policy" in denied
    assert es.ses_error_message(TimeoutError("read timed out")).startswith("Couldn't reach Amazon SES")


def test_off_means_unavailable_and_nothing_written():
    conn = FakeConn()
    ses = FakeSES()
    with configured({}, {**NO_SES_ENV, "APP_ENVIRONMENT": "prod"}), wired(conn, ses):
        result = send()
    assert result["status"] == "unavailable" and result["error"] == es.UNAVAILABLE and result["reason"] == "not_set_up"
    assert conn.statements == [] and ses.calls == []
    with configured({**SES_READY, "email_enabled": "false"}, SES_ENV), wired(conn, ses):
        assert send()["reason"] == "disabled"
    assert ses.calls == []


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def test_a_local_run_writes_the_email_to_the_log():
    conn = FakeConn()

    def no_ses():
        raise AssertionError("SES must not be called by the log transport")

    capture = Capture()
    es.logger.addHandler(capture)
    es.logger.setLevel(logging.INFO)
    original_conn, original_client = database.get_db_connection, es._ses_client
    database.get_db_connection = lambda *a, **k: conn
    es._ses_client = no_ses
    try:
        with configured({}, {**NO_SES_ENV, "APP_ENVIRONMENT": "local"}):
            result = send()
    finally:
        database.get_db_connection, es._ses_client = original_conn, original_client
        es.logger.removeHandler(capture)
    assert result["ok"] and result["status"] == "logged" and result["transport"] == "log"
    assert result["message_id"].startswith("log-")
    assert conn.of("UPDATE email_log")[0][0] == "logged"
    logged = "\n".join(capture.messages)
    assert "Subject: Q3 numbers" in logged and "To: bob@example.com" in logged and "Revenue is **up**" in logged


def test_the_sender_must_have_an_address():
    conn = FakeConn()
    with configured(SES_READY, SES_ENV), wired(conn, FakeSES()):
        for who in ["", "unknown", "4f6e0a7c-0000-4000-8000-000000000000"]:
            result = send(sender_username=who, sender_email=who)
            assert result["status"] == "refused" and result["reason"] == "no_sender", who


def test_content_limits():
    with configured(SES_READY, SES_ENV), wired(FakeConn(), FakeSES()):
        assert send(subject=" \r\n ")["reason"] == "no_subject"
        assert send(message_md="x" * (es.MAX_MESSAGE_CHARS + 1))["reason"] == "message_too_long"
        assert send(message_md="", table=None)["reason"] == "empty"
        assert send(table={"rows": "nope"})["reason"] == "bad_table"
        assert send(message_md="", table=table(2))["ok"]


def test_send_email_never_raises():
    original = es.current_settings

    def broken():
        raise RuntimeError("settings table unreachable")

    es.current_settings = broken
    try:
        result = send()
    finally:
        es.current_settings = original
    assert result["status"] == "unavailable" and result["error"] == es.UNAVAILABLE


def test_a_preview_shows_the_email_without_writing():
    conn = FakeConn(sent_today=7)
    with configured(SES_READY, SES_ENV), wired(conn, FakeSES()):
        preview = es.preview_email(ME, ME, "eve@other.com", "Q3", "Hello **there**", table(2), True, "Sales")
    assert preview["available"] and preview["mode"] == "ses"
    assert preview["reason"] == "domain_not_allowed"
    # The recipients are wrong, but the rest still previews.
    assert "<strong>there</strong>" in preview["html"] and preview["attachment"]["filename"] == "q3.csv"
    assert preview["sent_today"] == 7 and preview["daily_limit"] == 50 and preview["from_address"] == FROM
    assert [t for t, _ in conn.statements if not t.startswith("SELECT COUNT")] == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
