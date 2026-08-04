"""Minimal XLSX -> CSV converter, standard library only.

Exists because AMFI publishes its half-yearly stock categorisation as .xlsx
while `app.companies.universe.normalize.parse_amfi_rows` reads CSV, and this
environment has no openpyxl. An .xlsx is a zip of XML, so the conversion
needs no dependency at all -- adding one just to read a half-yearly file
would be a poor trade.

Deliberately not general: it handles shared strings, inline strings, numbers
and blank cells, which is everything AMFI's sheet uses. It does not handle
dates, formulas, or multiple sheets. If a future file needs those, install
openpyxl rather than growing this.

    python xlsx_to_csv.py <input.xlsx> <output.csv> [--header-contains TOKEN]

AMFI's sheet opens with a title row above the real header, so csv.DictReader
would otherwise key every row on the title. `--header-contains ISIN` drops
everything before the first row containing that token.
"""
import csv
import re
import sys
import zipfile
from xml.etree import ElementTree

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_CELL_REF = re.compile(r"([A-Z]+)(\d+)")


def _column_index(ref: str) -> int:
    """'A' -> 0, 'B' -> 1, ... 'AA' -> 26. Needed because a row omits its
    empty cells entirely, so position has to come from the reference rather
    than from counting."""
    letters = _CELL_REF.match(ref).group(1)
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    # Concatenate every <t> under an <si>: rich text splits one logical
    # string across several runs.
    return ["".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")) for si in root]


def _cell_text(cell, strings: list[str]) -> str:
    kind = cell.get("t")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iter(f"{{{_NS['m']}}}t")).strip()
    value = cell.find("m:v", _NS)
    if value is None or value.text is None:
        return ""
    if kind == "s":
        return strings[int(value.text)].strip()
    return value.text.strip()


def convert(xlsx_path: str, csv_path: str, header_contains: str | None = None) -> int:
    """Returns the number of rows written, header included.

    ``header_contains`` drops every row before the first one containing that
    token in any cell -- for sheets that open with a title row above the real
    header. Raises if the token is never found, rather than silently emitting
    a file keyed on the wrong row.
    """
    with zipfile.ZipFile(xlsx_path) as archive:
        strings = _shared_strings(archive)
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))

    rows = []
    for row in sheet.iter(f"{{{_NS['m']}}}row"):
        cells = {}
        for cell in row.findall("m:c", _NS):
            ref = cell.get("r")
            if ref:
                cells[_column_index(ref)] = _cell_text(cell, strings)
        if not cells:
            continue
        rows.append([cells.get(i, "") for i in range(max(cells) + 1)])

    if header_contains:
        start = next(
            (i for i, row in enumerate(rows) if any(header_contains in c for c in row)),
            None,
        )
        if start is None:
            raise SystemExit(f"no row contains {header_contains!r} -- refusing to guess the header")
        rows = rows[start:]

    width = max((len(r) for r in rows), default=0)
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for row in rows:
            writer.writerow(row + [""] * (width - len(row)))
    return len(rows)


if __name__ == "__main__":
    args = sys.argv[1:]
    token = None
    if "--header-contains" in args:
        at = args.index("--header-contains")
        token = args[at + 1]
        args = args[:at] + args[at + 2:]
    if len(args) != 2:
        raise SystemExit(__doc__)
    written = convert(args[0], args[1], header_contains=token)
    print(f"wrote {written} rows to {args[1]}")
