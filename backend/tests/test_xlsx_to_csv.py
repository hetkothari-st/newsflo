import csv
import zipfile

import pytest

from xlsx_to_csv import convert

_SHARED = """<?xml version="1.0"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <si><t>Title Row</t></si>
  <si><t>ISIN</t></si>
  <si><t>Categorization</t></si>
  <si><t>INE002A01018</t></si>
  <si><t>Large Cap</t></si>
</sst>"""

# Row 1 is a title above the real header (AMFI's actual shape). Row 3 omits
# its B cell entirely -- xlsx drops empty cells rather than emitting blanks,
# which is why column position has to come from the cell reference.
_SHEET = """<?xml version="1.0"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c></row>
    <row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2" t="s"><v>2</v></c></row>
    <row r="3"><c r="A3" t="s"><v>3</v></c><c r="B3" t="s"><v>4</v></c></row>
    <row r="4"><c r="A4" t="s"><v>3</v></c></row>
    <row r="5"><c r="A5"><v>42.5</v></c><c r="B5" t="inlineStr"><is><t>Inline</t></is></c></row>
  </sheetData>
</worksheet>"""


def _workbook(path):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", _SHARED)
        archive.writestr("xl/worksheets/sheet1.xml", _SHEET)
    return str(path)


def test_converts_shared_strings_numbers_and_inline_strings(tmp_path):
    out = tmp_path / "out.csv"
    convert(_workbook(tmp_path / "in.xlsx"), str(out))

    rows = list(csv.reader(out.open(encoding="utf-8")))
    assert rows[0] == ["Title Row", ""]
    assert rows[1] == ["ISIN", "Categorization"]
    assert rows[4] == ["42.5", "Inline"]


def test_header_contains_drops_the_title_preamble(tmp_path):
    out = tmp_path / "out.csv"
    convert(_workbook(tmp_path / "in.xlsx"), str(out), header_contains="ISIN")

    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    # Without the token the title row would become the header and every key
    # would be wrong -- this is the failure mode the flag exists to prevent.
    assert rows[0]["ISIN"] == "INE002A01018"
    assert rows[0]["Categorization"] == "Large Cap"


def test_missing_cells_keep_their_column_position(tmp_path):
    out = tmp_path / "out.csv"
    convert(_workbook(tmp_path / "in.xlsx"), str(out), header_contains="ISIN")

    rows = list(csv.DictReader(out.open(encoding="utf-8")))
    # Row 4 has no B cell; it must read as empty, not shift a later value left.
    assert rows[1]["ISIN"] == "INE002A01018"
    assert rows[1]["Categorization"] == ""


def test_absent_header_token_refuses_rather_than_guessing(tmp_path):
    with pytest.raises(SystemExit):
        convert(_workbook(tmp_path / "in.xlsx"), str(tmp_path / "out.csv"),
                header_contains="NOT_PRESENT")
