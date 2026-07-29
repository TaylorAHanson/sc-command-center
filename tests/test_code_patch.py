"""Standalone tests for splicing model-authored widget edits."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services.code_patch import (  # noqa: E402
    apply_edits,
    continuation_anchor,
    extract_code_block,
    looks_truncated,
    parse_edits,
    strip_edit_blocks,
)

WIDGET = """export default function Widget(props) {
  const [rows, setRows] = useState([]);

  useEffect(() => {
    fetch('/api/data').then(r => r.json()).then(setRows);
  }, []);

  return <div className="p-4">{rows.length}</div>;
}"""


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


def test_ambiguous_match_warns_and_takes_the_first():
    code = "const a = 1;\nconst b = 2;\nconst a = 1;"
    result = apply_edits(code, parse_edits(_block("const a = 1;", "const a = 99;")))
    assert result.applied == 1
    assert result.code == "const a = 99;\nconst b = 2;\nconst a = 1;"
    assert any("occurs 2 times" in w for w in result.warnings)


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


if __name__ == "__main__":
    tests = [
        test_parses_multiple_blocks_and_keeps_prose,
        test_applies_edits_sequentially,
        test_lines_up_added_lines_when_indentation_was_dropped,
        test_matches_a_block_indented_differently_and_reindents,
        test_tolerates_trailing_whitespace_difference,
        test_reports_unmatched_block_without_touching_code,
        test_partial_application_keeps_the_good_edit,
        test_ambiguous_match_warns_and_takes_the_first,
        test_empty_search_writes_a_new_file_but_never_overwrites,
        test_ignores_fences_a_model_wrapped_around_blocks,
        test_extract_code_block_prefers_typed_fence_over_sql,
        test_truncation_detection_and_anchor,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
