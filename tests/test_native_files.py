"""Standalone tests for handing an uploaded file to a model verbatim.

The provider shapes are not interchangeable — Anthropic rejects a `file` part and
OpenAI rejects a `document` one — so getting the flavor wrong fails the whole
call rather than degrading. These tests pin the shapes and the size rules; the
bytes come from a stubbed store, so nothing here needs credentials.
"""
import base64
import io
import os
import random
import sys

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services import native_files, upload_store  # noqa: E402

RAW = b"\x89PNG pretend bytes"


def _stub_store():
    upload_store.load_raw = lambda env, upload_id: RAW  # type: ignore[assignment]


def _image(**over):
    meta = {"id": "u1", "kind": "image", "mime": "image/png",
            "filename": "shot.png", "size_bytes": 1024}
    meta.update(over)
    return meta


def _pdf(**over):
    meta = {"id": "u2", "kind": "document", "mime": "application/pdf",
            "filename": "spec.pdf", "size_bytes": 1024,
            "profile": {"pages": 3, "chars": 5000}}
    meta.update(over)
    return meta


def test_flavor_recognises_both_families_and_neither():
    assert native_files.flavor("databricks-claude-sonnet-4") == native_files.ANTHROPIC
    assert native_files.flavor("databricks-gpt-oss-120b") == native_files.OPENAI
    assert native_files.flavor("system.ai.o3") == native_files.OPENAI
    # A model we know nothing about gets no parts and reads the extracted text.
    assert native_files.flavor("databricks-llama-4-maverick") is None
    assert native_files.flavor("") is None


def test_an_unknown_model_is_sent_nothing():
    _stub_store()
    assert native_files.parts("some-other-model", "dev", [_image()]) == []
    assert native_files.parts("databricks-claude-sonnet-4", "dev", []) == []


def test_an_image_goes_over_as_a_data_url_for_either_provider():
    _stub_store()
    expected = f"data:image/png;base64,{base64.b64encode(RAW).decode('ascii')}"
    for model in ("databricks-claude-sonnet-4", "databricks-gpt-oss-120b"):
        assert native_files.parts(model, "dev", [_image()]) == [
            {"type": "image_url", "image_url": {"url": expected}}
        ]


def test_an_image_with_no_usable_mime_is_typed_from_its_name():
    _stub_store()
    part = native_files.parts("databricks-claude-sonnet-4", "dev",
                              [_image(mime="", filename="widget.jpeg")])[0]
    assert part["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert native_files.guess_image_mime("no-extension") == "image/png"


def test_a_pdf_uses_the_shape_its_provider_accepts():
    _stub_store()
    anthropic = native_files.parts("databricks-claude-sonnet-4", "dev", [_pdf()])[0]
    assert anthropic["type"] == "document"
    assert anthropic["source"]["media_type"] == "application/pdf"

    openai = native_files.parts("databricks-gpt-oss-120b", "dev", [_pdf()])[0]
    assert openai["type"] == "file"
    assert openai["file"]["filename"] == "spec.pdf"


def test_a_long_text_bearing_pdf_stays_on_the_tool_path():
    """300 pages through the context window is what this design avoids."""
    _stub_store()
    assert native_files.parts("databricks-claude-sonnet-4", "dev",
                              [_pdf(profile={"pages": 400, "chars": 900000})]) == []


def test_a_scan_goes_over_however_long_it_is():
    """No extracted text means reading the pages is the only thing that will work."""
    _stub_store()
    parts = native_files.parts("databricks-claude-sonnet-4", "dev",
                               [_pdf(profile={"pages": 400, "chars": 0})])
    assert len(parts) == 1


def test_an_oversized_file_and_an_unreadable_one_are_both_skipped():
    _stub_store()
    max_bytes, _ = native_files.limits()
    assert native_files.parts("databricks-claude-sonnet-4", "dev",
                              [_pdf(size_bytes=max_bytes + 1)]) == []

    upload_store.load_raw = lambda env, upload_id: None  # type: ignore[assignment]
    assert native_files.parts("databricks-claude-sonnet-4", "dev", [_image()]) == []


def _png(width, height, noisy=False):
    img = Image.new("RGB", (width, height), (240, 240, 240))
    if noisy:
        rng = random.Random(7)
        img.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(width * height)])
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _size(data):
    with Image.open(io.BytesIO(data)) as img:
        return img.size


def test_a_small_image_is_sent_untouched():
    raw = _png(800, 600)
    assert native_files.fit_image(raw, "image/png") == (raw, "image/png")


def test_a_retina_screenshot_is_scaled_to_the_long_edge_the_model_uses():
    data, mime = native_files.fit_image(_png(3456, 2234), "image/png")
    assert mime == "image/png"
    assert _size(data) == (native_files.IMAGE_LONG_EDGE, round(2234 * native_files.IMAGE_LONG_EDGE / 3456))


def test_an_image_png_cannot_fit_falls_back_to_jpeg_under_the_budget():
    data, mime = native_files.fit_image(_png(1568, 1200, noisy=True), "image/png")
    assert mime == "image/jpeg" and len(data) <= native_files.IMAGE_MAX_BYTES


def test_an_unreadable_image_is_sent_only_if_already_small_enough():
    assert native_files.fit_image(RAW, "image/png") == (RAW, "image/png")
    assert native_files.fit_image(b"x" * (native_files.IMAGE_MAX_BYTES + 1), "image/png") is None


def test_an_upload_over_the_file_limit_is_shrunk_rather_than_dropped():
    max_bytes, _ = native_files.limits()
    big = _png(4000, 3000)
    upload_store.load_raw = lambda env, upload_id: big  # type: ignore[assignment]
    [part] = native_files.parts("databricks-claude-sonnet-4", "dev", [_image(size_bytes=max_bytes + 1)])
    head, _, data = part["image_url"]["url"].partition(",")
    assert head == "data:image/png;base64"
    assert max(_size(base64.b64decode(data))) == native_files.IMAGE_LONG_EDGE


def test_a_preview_screenshot_is_shrunk_too():
    url = "data:image/png;base64," + base64.b64encode(_png(3000, 1000)).decode("ascii")
    part = native_files.image_part("databricks-claude-sonnet-4", url)
    head, _, data = part["image_url"]["url"].partition(",")
    assert head == "data:image/png;base64" and _size(base64.b64decode(data))[0] == native_files.IMAGE_LONG_EDGE
    small = "data:image/png;base64," + base64.b64encode(_png(400, 300)).decode("ascii")
    assert native_files.image_part("databricks-claude-sonnet-4", small)["image_url"]["url"] == small
    assert native_files.image_part("databricks-claude-sonnet-4", "data:image/png;base64,not base64!") is None


def test_a_spreadsheet_is_left_to_extraction():
    _stub_store()
    assert native_files.parts("databricks-claude-sonnet-4", "dev", [
        {"id": "u3", "kind": "table", "mime": "text/csv",
         "filename": "rows.csv", "size_bytes": 2048},
    ]) == []


def test_limits_survive_a_malformed_override():
    os.environ["AGENT_RUNTIME_NATIVE_FILE_MB"] = "not a number"
    os.environ["AGENT_RUNTIME_NATIVE_PDF_PAGES"] = ""
    try:
        assert native_files.limits() == (8 * 1024 * 1024, 20)
    finally:
        del os.environ["AGENT_RUNTIME_NATIVE_FILE_MB"]
        del os.environ["AGENT_RUNTIME_NATIVE_PDF_PAGES"]


if __name__ == "__main__":
    original = upload_store.load_raw
    tests = [
        test_flavor_recognises_both_families_and_neither,
        test_an_unknown_model_is_sent_nothing,
        test_an_image_goes_over_as_a_data_url_for_either_provider,
        test_an_image_with_no_usable_mime_is_typed_from_its_name,
        test_a_pdf_uses_the_shape_its_provider_accepts,
        test_a_long_text_bearing_pdf_stays_on_the_tool_path,
        test_a_scan_goes_over_however_long_it_is,
        test_an_oversized_file_and_an_unreadable_one_are_both_skipped,
        test_a_small_image_is_sent_untouched,
        test_a_retina_screenshot_is_scaled_to_the_long_edge_the_model_uses,
        test_an_image_png_cannot_fit_falls_back_to_jpeg_under_the_budget,
        test_an_unreadable_image_is_sent_only_if_already_small_enough,
        test_an_upload_over_the_file_limit_is_shrunk_rather_than_dropped,
        test_a_preview_screenshot_is_shrunk_too,
        test_a_spreadsheet_is_left_to_extraction,
        test_limits_survive_a_malformed_override,
    ]
    try:
        for test in tests:
            test()
            print(f"PASS {test.__name__}")
    finally:
        upload_store.load_raw = original
