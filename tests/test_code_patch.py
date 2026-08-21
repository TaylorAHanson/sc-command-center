"""Standalone tests for splicing model-authored widget edits."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services.code_patch import (  # noqa: E402
    apply_edits,
    assess_rewrite,
    continuation_anchor,
    extract_code_block,
    has_conflict_markers,
    looks_truncated,
    parse_edits,
    sloc,
    strip_edit_blocks,
)

WIDGET = """export default function Widget(props) {
  const [rows, setRows] = useState([]);

  useEffect(() => {
    fetch('/api/data').then(r => r.json()).then(setRows);
  }, []);

  return <div className="p-4">{rows.length}</div>;
}"""

# Something long enough for the size checks to have an opinion about, standing in
# for the widgets users actually lose.
BIG_WIDGET = "export default function Widget(props) {\n" + "".join(
    f"  const v{i} = {i};\n" for i in range(40)
) + '  return <div className="p-4">{v1}</div>;\n}'


def _block(search, replace):
    return f"<<<<<<< SEARCH\n{search}\n=======\n{replace}\n>>>>>>> REPLACE"


def test_parses_multiple_blocks_and_keeps_prose():
    response = (
        "Adding sorting.\n\n"
        + _block("  const [rows, setRows] = useState([]);",
                 "  const [rows, setRows] = useState([]);\n  const [key, setKey] = useState('name');")
        + "\n\n"
        + _block('    <div className="p-4">{rows.length}</div>',
                 '    <div className="p-4">{key}: {rows.length}</div>')
        + "\n\nThat's it."
    )
    edits = parse_edits(response)
    assert len(edits) == 2
    assert edits[0].search.strip().startswith("const [rows")
    assert strip_edit_blocks(response) == "Adding sorting.\n\nThat's it."


def test_applies_edits_sequentially():
    edits = parse_edits(
        _block("  const [rows, setRows] = useState([]);",
               "  const [rows, setRows] = useState([]);\n  const [key, setKey] = useState('name');")
    )
    result = apply_edits(WIDGET, edits)
    assert result.applied == 1
    assert not result.failures
    assert "const [key, setKey] = useState('name');" in result.code
    # Everything the edit didn't mention survives untouched.
    assert "fetch('/api/data')" in result.code
    assert result.code.count("const [rows, setRows]") == 1


def test_lines_up_added_lines_when_indentation_was_dropped():
    # The model reproduced the line flush-left. Its first line splices in after the
    # indentation already in the file; the line it adds has to be shifted to match.
    edits = parse_edits(_block("const [rows, setRows] = useState([]);",
                               "const [rows, setRows] = useState([]);\nconst [busy, setBusy] = useState(false);"))
    result = apply_edits(WIDGET, edits)
    assert result.applied == 1
    assert "  const [rows, setRows] = useState([]);\n  const [busy, setBusy] = useState(false);" in result.code


def test_matches_a_block_indented_differently_and_reindents():
    # Over-indented relative to the file: no substring match exists at all.
    edits = parse_edits(_block("    const [rows, setRows] = useState([]);",
                               "    const [rows, setRows] = useState([]);\n    const [busy, setBusy] = useState(false);"))
    result = apply_edits(WIDGET, edits)
    assert result.applied == 1
    assert "  const [busy, setBusy] = useState(false);" in result.code
    assert "    const [busy" not in result.code
    assert any("indentation" in w for w in result.warnings)


def test_tolerates_trailing_whitespace_difference():
    edits = parse_edits(_block("  }, []);   ", "  }, [props.data.dataSource]);"))
    result = apply_edits(WIDGET, edits)
    assert result.applied == 1
    assert "}, [props.data.dataSource]);" in result.code


def test_reports_unmatched_block_without_touching_code():
    edits = parse_edits(_block("const nothingLikeThis = 1;", "const somethingElse = 2;"))
    result = apply_edits(WIDGET, edits)
    assert result.applied == 0
    assert result.code == WIDGET
    assert len(result.failures) == 1
    assert "could not find" in result.failures[0]


def test_partial_application_keeps_the_good_edit():
    edits = parse_edits(
        _block("  const [rows, setRows] = useState([]);", "  const [rows, setRows] = useState(null);")
        + "\n" + _block("const missing = true;", "const missing = false;")
    )
    result = apply_edits(WIDGET, edits)
    assert result.applied == 1
    assert "useState(null)" in result.code
    assert len(result.failures) == 1


def test_ambiguous_match_is_refused_rather_than_guessed_at():
    code = "const a = 1;\nconst b = 2;\nconst a = 1;"
    result = apply_edits(code, parse_edits(_block("const a = 1;", "const a = 99;")))
    assert result.applied == 0
    assert result.code == code
    assert "matches 2 different places" in result.failures[0]


def test_ambiguity_is_refused_on_the_whitespace_tolerant_paths_too():
    # The same duplicate, reachable only after the exact pass misses on indentation.
    code = "  const a = 1;   \nconst b = 2;\n    const a = 1;"
    result = apply_edits(code, parse_edits(_block("const a = 1;", "const a = 99;")))
    assert result.applied == 0 and result.code == code
    assert "matches 2 different places" in result.failures[0]


def test_a_block_carrying_a_stray_marker_is_refused_not_written():
    # The regression: a model that "left a duplicate marker" mid-edit. SEARCH stops
    # at the first =======, so the second one lands inside REPLACE, and applying it
    # writes a conflict marker into the widget — which then can't compile, and the
    # auto-fix rounds edit a file that is half marker.
    malformed = (
        "<<<<<<< SEARCH\n  const [rows, setRows] = useState([]);\n"
        "=======\n  const [mapReady, setMapReady] = React.useState(false);\n"
        "=======\n  );\n>>>>>>> REPLACE"
    )
    result = apply_edits(WIDGET, parse_edits(malformed))
    assert result.applied == 0
    assert result.code == WIDGET
    assert "=======" not in result.code
    assert "stray conflict marker" in result.failures[0]


def test_damaged_code_is_recognised_so_a_rewrite_can_be_asked_for():
    # Edits cannot repair this: a SEARCH body ends at the first ======= line, so
    # no block can quote the damage. Detecting it is what lets the caller ask for
    # the whole file instead of looping on edits that can never land.
    assert has_conflict_markers("const a = 1;\n=======\nconst b = 2;")
    assert has_conflict_markers("<<<<<<< SEARCH\nconst a = 1;")
    assert not has_conflict_markers(WIDGET)
    # Not so trigger-happy that ordinary code trips it.
    assert not has_conflict_markers("const line = '========';\n// ====== section ======")


def test_a_rewrite_that_echoes_the_damage_back_is_refused():
    damaged = WIDGET.replace("  useEffect", "=======\n  useEffect")
    risk = assess_rewrite(damaged, damaged.replace("fetch('/api/data')", "fetch('/api/rows')"))
    assert risk and risk.blocking and "edit marker" in risk.reason


def test_empty_search_writes_a_new_file_but_never_overwrites():
    created = apply_edits("", parse_edits(_block("", "export default function W() {}")))
    assert created.applied == 1 and created.code == "export default function W() {}"

    guarded = apply_edits(WIDGET, parse_edits(_block("", "export default function W() {}")))
    assert guarded.applied == 0 and guarded.code == WIDGET


def test_ignores_fences_a_model_wrapped_around_blocks():
    edits = parse_edits(
        "<<<<<<< SEARCH\n```tsx\n  const [rows, setRows] = useState([]);\n```\n"
        "=======\n```tsx\n  const [rows, setRows] = useState([1]);\n```\n>>>>>>> REPLACE"
    )
    result = apply_edits(WIDGET, edits)
    assert result.applied == 1
    assert "useState([1])" in result.code
    assert "```" not in result.code


def test_extract_code_block_prefers_typed_fence_over_sql():
    content = "Query:\n```sql\nSELECT 1\n```\nComponent:\n```tsx\nexport default function W() {}\n```"
    code, prose = extract_code_block(content)
    assert code == "export default function W() {}"
    assert "SELECT 1" in prose


def test_truncation_detection_and_anchor():
    complete = "```tsx\nexport default function W() {}\n```"
    cut_off = "Here you go:\n```tsx\nexport default function W() {\n  const a = 1;"
    assert looks_truncated(complete) is False
    # A closing fence with anything after it is still a closed fence — this was a
    # false positive that spent continuation calls on finished responses.
    assert looks_truncated(complete + "\n\nLet me know what you think.\n") is False
    assert looks_truncated("```sql\nSELECT 1\n```\n" + complete + "\n") is False
    assert looks_truncated(cut_off) is True
    code, _ = extract_code_block(cut_off)
    assert code.startswith("export default function W() {")
    assert continuation_anchor("a\nb\nc\nd", lines=2) == "c\nd"


def test_accepts_a_real_rewrite_and_ignores_unrelated_cases():
    rewrite = BIG_WIDGET.replace("const v1 = 1;", "const v1 = 1;\n  const extra = useMemo(() => 2, []);")
    assert assess_rewrite(BIG_WIDGET, rewrite) is None
    # Nothing to protect: a new widget, or the same file back again.
    assert assess_rewrite("", BIG_WIDGET) is None
    assert assess_rewrite(BIG_WIDGET, BIG_WIDGET) is None


def test_rejects_elided_rest_of_the_widget():
    for placeholder in (
        "  // ... rest of the component unchanged",
        "  // ...",
        "  {/* ... existing markup ... */}",
        "  // rest of the render logic stays the same",
        "  // ... (unchanged)",
    ):
        reply = f"export default function Widget(props) {{\n  const v0 = 99;\n{placeholder}\n}}"
        risk = assess_rewrite(BIG_WIDGET, reply)
        assert risk is not None and risk.blocking, placeholder
        assert "leaves the rest" in risk.reason


def test_rejects_an_excerpt_of_the_existing_file():
    excerpt = "  const v3 = 3;\n  const v4 = 4;"
    risk = assess_rewrite(BIG_WIDGET, excerpt)
    assert risk is not None and risk.blocking
    assert "excerpt" in risk.reason


def test_rejects_a_fragment_that_exports_nothing():
    fragment = "function formatRow(row) {\n  return row.name.toUpperCase();\n}"
    risk = assess_rewrite(BIG_WIDGET, fragment)
    assert risk is not None and risk.blocking
    assert "exports nothing" in risk.reason


def test_rejects_code_that_is_cut_off():
    cut = "export default function Widget(props) {\n  const rows = useRows();\n  return (\n    <div>"
    risk = assess_rewrite(BIG_WIDGET, cut)
    assert risk is not None and risk.blocking

    # Braces inside strings and comments are not evidence of anything.
    honest = BIG_WIDGET.replace(
        'const v0 = 0;', 'const brace = "}"; // a } in a comment\n  const v0 = 0;'
    )
    assert assess_rewrite(BIG_WIDGET, honest) is None


def test_flags_a_drastic_shrink_without_blocking_it():
    smaller = "export default function Widget() {\n  return <div>tiny</div>;\n}"
    risk = assess_rewrite(BIG_WIDGET, smaller)
    assert risk is not None and risk.blocking is False
    assert f"{sloc(BIG_WIDGET)} lines down to {sloc(smaller)}" in risk.reason

    # A small widget legitimately becoming a slightly smaller one isn't news.
    assert assess_rewrite(WIDGET, "export default function Widget() {\n  return <div/>;\n}") is None


if __name__ == "__main__":
    tests = [
        test_parses_multiple_blocks_and_keeps_prose,
        test_applies_edits_sequentially,
        test_lines_up_added_lines_when_indentation_was_dropped,
        test_matches_a_block_indented_differently_and_reindents,
        test_tolerates_trailing_whitespace_difference,
        test_reports_unmatched_block_without_touching_code,
        test_partial_application_keeps_the_good_edit,
        test_ambiguous_match_is_refused_rather_than_guessed_at,
        test_ambiguity_is_refused_on_the_whitespace_tolerant_paths_too,
        test_a_block_carrying_a_stray_marker_is_refused_not_written,
        test_damaged_code_is_recognised_so_a_rewrite_can_be_asked_for,
        test_a_rewrite_that_echoes_the_damage_back_is_refused,
        test_empty_search_writes_a_new_file_but_never_overwrites,
        test_ignores_fences_a_model_wrapped_around_blocks,
        test_extract_code_block_prefers_typed_fence_over_sql,
        test_truncation_detection_and_anchor,
        test_accepts_a_real_rewrite_and_ignores_unrelated_cases,
        test_rejects_elided_rest_of_the_widget,
        test_rejects_an_excerpt_of_the_existing_file,
        test_rejects_a_fragment_that_exports_nothing,
        test_rejects_code_that_is_cut_off,
        test_flags_a_drastic_shrink_without_blocking_it,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
