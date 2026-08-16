"""A minimal, hand-assembled PDF writer -- FIXTURE MACHINERY ONLY.

The Phase 1 extraction pipeline reads PDFs with `pypdf`, and the pypdf
adapter is worth an end-to-end test. `pypdf` can copy and merge pages but it
cannot CREATE a page carrying text, and no PDF-authoring library (reportlab,
fpdf) is installed -- the controller adaptation forbids adding dependencies.

So this module emits a valid one-object-per-page PDF by hand: a catalog, a
page tree, one Helvetica text content stream per page, and a correct xref
table. ~40 lines, no dependency, and it exercises the real pypdf code path
instead of stubbing it.

Nothing outside `tests/` may import this. The text it is given comes from
`tests/fixtures/phase1/testco_filing.json`, which is obviously fake.
"""
from __future__ import annotations


def _escape(text: str) -> str:
    return (text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            .encode("ascii", "replace").decode("ascii"))


def _wrap(text: str, width: int = 88) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def build_pdf(pages: list[str]) -> bytes:
    """A PDF whose page N carries `pages[N]` as extractable text."""
    n = len(pages)
    font_id = 3 + 2 * n
    objects: dict[int, bytes] = {}

    page_ids = [3 + 2 * i for i in range(n)]
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode("ascii")

    for i, text in enumerate(pages):
        page_id, content_id = page_ids[i], 4 + 2 * i
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> "
            f">> >>").encode("ascii")
        body = ["BT", "/F1 10 Tf", "12 TL", "36 750 Td"]
        for line in _wrap(text):
            body.append(f"({_escape(line)}) Tj T*")
        body.append("ET")
        stream = "\n".join(body).encode("ascii")
        objects[content_id] = (f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
                               + stream + b"\nendstream")

    objects[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for object_id in sorted(objects):
        offsets[object_id] = len(out)
        out += f"{object_id} 0 obj\n".encode("ascii") + objects[object_id] + b"\nendobj\n"

    xref_offset = len(out)
    size = font_id + 1
    out += f"xref\n0 {size}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for object_id in range(1, size):
        out += f"{offsets[object_id]:010d} 00000 n \n".encode("ascii")
    out += (f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n"
            f"{xref_offset}\n%%EOF\n").encode("ascii")
    return bytes(out)
