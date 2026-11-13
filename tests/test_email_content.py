"""Tests for what an email may carry beyond Markdown (services/email_content.py).

No network and no database. Pinned here:

- that HTML is rebuilt from an allow-list: scripts, styles, frames, forms and
  event handlers never come through, links go only to http/https/mailto, CSS
  keeps only plain properties with values that fetch nothing, and every tag
  opened is closed, so nothing escapes into the footer;
- that images are embedded or left out: a data: URL becomes an inline part, a
  `cid:` reference names an attached image, and anything from another site is
  dropped with a note for the person previewing it;
- which files may be attached (text, CSV, TSV, JSON, Markdown, PNG, JPEG, GIF,
  WebP), that an image must really be one, that a CSV gets the formula guard,
  and the caps;
- the plain-text part, which keeps the words and where each link went.
"""
import base64
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))

from services import email_content as ec  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
GIF = b"GIF89a" + b"\x00" * 10
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 10
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 8


def data_url(kind, raw):
    return f"data:{kind};base64,{base64.b64encode(raw).decode()}"


def clean(markup, files=()):
    return ec.sanitize_html(markup, files)


# --- HTML -----------------------------------------------------------------------

def test_scripts_styles_and_frames_go_with_their_content():
    out = clean('<p>Hi</p><script>alert(1)</script><style>p{color:red}</style>'
                '<iframe src="https://evil"><p>inner</p></iframe><svg><text>svg</text></svg><p>Bye</p>')
    assert out.html == "<p>Hi</p><p>Bye</p>"
    assert "alert" not in out.text and "inner" not in out.text and "svg" not in out.text


def test_unknown_tags_go_but_their_words_stay():
    out = clean('<form action="https://evil"><button onclick="x()">Press</button><input value="v"></form>')
    assert out.html == "Press"


def test_event_handlers_and_unknown_attributes_go():
    out = clean('<p onclick="steal()" class="x" id="y" style="color:red">Hi</p>')
    assert out.html == '<p style="color:red">Hi</p>'


def test_links_only_to_safe_schemes():
    out = clean('<a href="javascript:alert(1)">a</a><a href="jav&#x61;script:x">b</a>'
                '<a href="https://example.com/x?a=1&amp;b=2">c</a><a href="mailto:bob@example.com">d</a>'
                '<a href="data:text/html,hi">e</a>')
    assert out.html == ('<a>a</a><a>b</a><a href="https://example.com/x?a=1&amp;b=2">c</a>'
                        '<a href="mailto:bob@example.com">d</a><a>e</a>')


def test_attribute_values_cannot_break_out():
    out = clean('<p title="&quot; onmouseover=&quot;x()">Hi</p>')
    assert out.html == '<p title="&quot; onmouseover=&quot;x()">Hi</p>'


def test_every_tag_opened_is_closed():
    out = clean('<div><table><tr><td>cell')
    assert out.html == "<div><table><tr><td>cell</td></tr></table></div>"
    # A stray closing tag can't close the body around it.
    assert clean("<p>a</p></div></body></html><p>b</p>").html == "<p>a</p><p>b</p>"


def test_text_is_escaped_once():
    out = clean("<p>1 &lt; 2 &amp; 3 &gt; 2</p><p><b>&lt;script&gt;</b></p>")
    assert out.html == "<p>1 &lt; 2 &amp; 3 &gt; 2</p><p><b>&lt;script&gt;</b></p>"
    assert "1 < 2 & 3 > 2" in out.text


def test_css_keeps_plain_properties_only():
    style = ("color:#123456; background-color:rgb(1,2,3); font-family:'Segoe UI',Arial; padding:4px 8px;"
             "border-top-left-radius:6px; background:url(https://evil/p.gif); width:expression(alert(1));"
             "position:absolute; behavior:url(x.htc); color:red\\9; display:none; -moz-binding:url(x);"
             "font-size:12px /* hi */")
    assert ec.clean_style(style) == ("color:#123456;background-color:rgb(1,2,3);font-family:'Segoe UI',Arial;"
                                     "padding:4px 8px;border-top-left-radius:6px")


def test_comments_and_doctypes_go():
    assert clean("<!doctype html><!-- secret --><p>Hi</p><![CDATA[x]]>").html == "<p>Hi</p>"


def test_numbers_and_enums_are_checked():
    out = clean('<table width="100%" border="1" cellpadding="x"><tr><td colspan="2" valign="top" '
                'align="javascript">a</td></tr></table>')
    assert out.html == '<table width="100%" border="1"><tr><td colspan="2" valign="top">a</td></tr></table>'


# --- images ---------------------------------------------------------------------

def test_a_data_image_becomes_an_inline_part():
    out = clean(f'<p><img src="{data_url("image/png", PNG)}" alt="Chart" width="300"></p>')
    [image] = out.images
    assert image.content_type == "image/png" and image.data == PNG and image.inline
    assert image.filename == "image-1.png"
    assert out.html == f'<p><img src="cid:{image.cid}" alt="Chart" width="300"></p>'
    assert out.notes == []


def test_a_cid_reference_names_an_attached_image():
    files = ec.normalize_attachments([{"filename": "Chart.png", "data": data_url("image/png", PNG)}])
    out = clean('<img src="cid:chart.png">', files)
    assert out.referenced == ["Chart.png"] and out.images == []
    inline = ec.inline_for_html(files, out.referenced)
    assert inline[0].inline and f'src="cid:{inline[0].cid}"' in out.html


def test_remote_images_are_left_out_with_a_note():
    out = clean('<img src="https://tracker.example/p.gif?u=1"><img src="//evil/x.png"><img>'
                '<img src="cid:nothing.png"><img src="data:image/png;base64,!!!">')
    assert out.html == "" and out.images == []
    assert out.notes == [
        "Left out 2 images that would load from another site; only embedded images are sent.",
        "Left out 2 images that couldn't be read.",
    ]


def test_an_embedded_image_must_be_an_image():
    # Declared PNG, really HTML: a mail client sniffing it must never get markup.
    out = clean(f'<img src="{data_url("image/png", b"<html><script>x</script>")}">'
                f'<img src="{data_url("image/svg+xml", b"<svg onload=x()></svg>")}">')
    assert out.images == [] and out.notes == ["Left out 2 images that couldn't be read."]


def test_inline_images_are_capped():
    markup = "".join(f'<img src="{data_url("image/gif", GIF)}">' for _ in range(ec.MAX_INLINE_IMAGES + 2))
    out = clean(markup)
    assert len(out.images) == ec.MAX_INLINE_IMAGES
    assert out.notes == [f"Left out images past the first {ec.MAX_INLINE_IMAGES}."]


def test_a_preview_draws_inline_images_as_data_urls():
    out = clean(f'<img src="{data_url("image/png", PNG)}">')
    shown = ec.with_data_urls(out.html, out.images)
    assert shown == f'<img src="{data_url("image/png", PNG)}">'


def test_html_is_capped():
    try:
        clean("<p>" + "x" * (ec.MAX_HTML_CHARS + 1) + "</p>")
    except ValueError as exc:
        assert "too long" in str(exc)
    else:
        raise AssertionError("expected a refusal")


# --- the plain-text part --------------------------------------------------------

def test_the_text_part_keeps_words_and_links():
    out = clean('<h2>Weekly</h2><p>Revenue is <b>up</b>.</p><ul><li>West</li><li>East</li></ul>'
                '<p>See <a href="https://example.com/r">the report</a> or '
                '<a href="https://example.com/x">https://example.com/x</a>.</p><pre>a  b\n c</pre>')
    assert out.text == ("Weekly\nRevenue is up.\n- West\n- East\n"
                        "See the report (https://example.com/r) or https://example.com/x.\na  b\n c")


# --- files ----------------------------------------------------------------------

def test_the_kinds_of_file_that_may_go():
    files = ec.normalize_attachments([
        {"filename": "notes.txt", "content": "hello"},
        {"filename": "data.json", "content": "{\"a\": 1}"},
        {"filename": "readme.md", "content": "# Hi"},
        {"filename": "photo.JPG", "data": base64.b64encode(JPEG).decode()},
        {"filename": "anim.gif", "data": data_url("image/gif", GIF)},
        {"filename": "pic.webp", "data": data_url("image/webp", WEBP)},
    ])
    assert [(f.filename, f.content_type) for f in files] == [
        ("notes.txt", "text/plain"), ("data.json", "application/json"), ("readme.md", "text/markdown"),
        ("photo.JPG", "image/jpeg"), ("anim.gif", "image/gif"), ("pic.webp", "image/webp")]
    assert not any(f.inline for f in files)


def refused(items):
    try:
        ec.normalize_attachments(items)
    except ValueError as exc:
        return str(exc)
    raise AssertionError(f"expected a refusal for {items!r}")


def test_other_kinds_are_refused():
    for name in ("report.pdf", "book.xlsx", "page.html", "run.exe", "chart.svg", "noext", "x.png.exe"):
        assert "only .csv, .tsv, .txt, .json, .md, .png, .jpg, .gif, .webp" in refused(
            [{"filename": name, "content": "x"}]), name


def test_an_image_must_be_what_its_name_says():
    assert refused([{"filename": "x.png", "data": base64.b64encode(GIF).decode()}]) == \
        "x.png isn't the PNG image its name says."
    assert "send it as data" in refused([{"filename": "x.png", "content": "not bytes"}])


def test_text_must_be_utf8_and_data_must_be_base64():
    assert refused([{"filename": "x.txt", "data": base64.b64encode(b"\xff\xfe\x00").decode()}]) == \
        "x.txt isn't text: a .txt file must be UTF-8."
    assert "must be base64" in refused([{"filename": "x.txt", "data": "%%%"}])
    assert refused([{"filename": "x.txt"}]) == "x.txt has no content."
    assert refused([{"content": "x"}]) == "Each attachment needs a filename."
    assert refused("nope") == "Attachments must be a list of files."


def test_file_names_are_made_safe_and_unique():
    files = ec.normalize_attachments([
        {"filename": "../../etc/Report\r\nBcc: x.csv", "content": "a"},
        {"filename": "report.csv", "content": "b"},
        {"filename": "Report.csv", "content": "c"},
    ])
    names = [f.filename for f in files]
    assert names[0] == "Report-Bcc- x.csv"
    assert names[1:] == ["report.csv", "Report-2.csv"]


def test_a_callers_csv_gets_the_formula_guard():
    [f] = ec.normalize_attachments([{"filename": "a.csv", "content": "name,cmd\nAna,=HYPERLINK(\"x\")\nBo,-5\n"}])
    assert f.data.decode() == 'name,cmd\r\nAna,"\'=HYPERLINK(""x"")"\r\nBo,-5\r\n'
    [t] = ec.normalize_attachments([{"filename": "a.tsv", "content": "x\t@SUM(A1)\n"}])
    assert t.data.decode() == "x\t'@SUM(A1)\r\n"


def test_files_are_capped():
    assert refused([{"filename": f"{i}.txt", "content": "x"} for i in range(ec.MAX_ATTACHMENTS + 1)]) == \
        f"At most {ec.MAX_ATTACHMENTS} attachments."
    original = ec.ATTACHMENT_MAX_BYTES
    ec.ATTACHMENT_MAX_BYTES = 10
    try:
        assert refused([{"filename": "big.txt", "content": "x" * 11}]) == "big.txt is too large: at most 0 MB a file."
    finally:
        ec.ATTACHMENT_MAX_BYTES = original


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} passed")
