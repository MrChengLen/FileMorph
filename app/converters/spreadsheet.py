# SPDX-License-Identifier: AGPL-3.0-or-later
import csv
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, TextIO

from app.converters.base import (
    BaseConverter,
    InvalidInputError,
    OutputTooLargeError,
    read_utf8_text,
)
from app.converters.registry import register

if TYPE_CHECKING:
    from openpyxl import Workbook


class _CappedText:
    """A UTF-8 text file that raises :class:`OutputTooLargeError` once more
    than ``limit`` bytes were written to it."""

    def __init__(self, f: TextIO, limit: int) -> None:
        self._f, self._left = f, limit

    def write(self, text: str) -> int:
        self._left -= len(text) if text.isascii() else len(text.encode("utf-8"))
        if self._left < 0:
            raise OutputTooLargeError
        return self._f.write(text)


def _capped(f: TextIO, limit: int | None):
    """``f``, or ``f`` stopped at ``limit`` bytes (``max_output_bytes``)."""
    return f if limit is None else _CappedText(f, limit)


def _rows_within(rows, out: _CappedText, longest: int):
    """``rows``, stopped before csv builds a row longer than ``out`` has left.

    csv builds a whole row before it writes it, and shared text can repeat in
    many cells, so a row can be far longer than the file. A row that could be
    that long, at ``longest`` characters per cell, is measured first.
    """
    per_cell = 2 * max(longest, 40) + 3  # every quote doubled, two more, a separator
    for row in rows:
        if len(row) * per_cell > out._left:
            texts = ["" if v is None else str(v) for v in row]
            # At least every character, the doubled quotes and a separator each.
            if sum(map(len, texts)) + sum(t.count('"') for t in texts) + len(texts) > out._left:
                raise OutputTooLargeError
        yield row


def _load_cells_only(upload: BinaryIO) -> "Workbook":
    """Open an XLSX for its cell values only.

    Read-only, with stored values instead of formulas, without links to other
    workbooks, and without the drawings (charts, images) of chart sheets — a
    CSV holds none of these; openpyxl's read-only mode already skips the
    drawings of worksheets. ``read_chartsheet`` is openpyxl 3.1.5's without
    its drawings, and XLSX → CSV reads ``ws._shared_strings``; re-check both
    on an openpyxl upgrade. Same as ``openpyxl.load_workbook`` otherwise.
    """
    from openpyxl.chartsheet import Chartsheet
    from openpyxl.reader.excel import ExcelReader
    from openpyxl.xml.functions import fromstring

    class _CellsOnlyReader(ExcelReader):
        def read_chartsheet(self, sheet, rel):
            with self.archive.open(rel.target, "r") as src:
                chartsheet = Chartsheet.from_tree(fromstring(src.read()))
            chartsheet._parent = self.wb
            chartsheet.title = sheet.name
            self.wb._add_sheet(chartsheet)

    reader = _CellsOnlyReader(upload, read_only=True, data_only=True, keep_links=False)
    reader.read()
    return reader.wb


@register(("xlsx", "csv"))
class XlsxToCsvConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        limit = kwargs.get("max_output_bytes")
        # Closed on every path: an upload that is still open can't be deleted on Windows.
        with input_path.open("rb") as upload:
            wb = _load_cells_only(upload)
            ws = wb.active
            if not hasattr(ws, "iter_rows"):  # a chart sheet is active, or none is
                ws = next(iter(wb.worksheets), None)
            if ws is None:
                raise InvalidInputError(
                    "This workbook has no worksheet with cells to export. Add a "
                    "worksheet with the data, save, and try again."
                )
            with output_path.open("w", newline="", encoding="utf-8") as f:
                # csv writes None as "" and str() of everything else.
                rows = ws.iter_rows(values_only=True)
                if limit is None:
                    csv.writer(f).writerows(rows)
                else:
                    out = _CappedText(f, limit)
                    longest = max(map(len, ws._shared_strings), default=0)
                    csv.writer(out).writerows(_rows_within(rows, out, longest))
        return output_path


@register(("csv", "xlsx"))
class CsvToXlsxConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        for row in csv.reader(io.StringIO(read_utf8_text(input_path), newline="")):
            ws.append(row)
        wb.save(str(output_path))
        return output_path


@register(("csv", "json"))
class CsvToJsonConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        rows = csv.DictReader(io.StringIO(read_utf8_text(input_path), newline=""))
        # Row by row, the same text json.dumps(list(rows), indent=2) would give.
        with output_path.open("w", encoding="utf-8") as f:
            out = _capped(f, kwargs.get("max_output_bytes"))
            out.write("[")
            empty = True
            for row in rows:
                # json.dumps escapes every "\n" inside a string, so each "\n"
                # left is between tokens and gets the list's indent.
                item = "  " + json.dumps(row, indent=2, ensure_ascii=False).replace("\n", "\n  ")
                out.write(("\n" if empty else ",\n") + item)
                empty = False
            out.write("]" if empty else "\n]")
        return output_path


@register(("json", "csv"))
class JsonToCsvConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        data = json.loads(read_utf8_text(input_path))
        if not isinstance(data, list) or not data:
            raise InvalidInputError("JSON must be a non-empty array of objects for CSV conversion.")
        fieldnames = list(data[0].keys())
        limit = kwargs.get("max_output_bytes")
        # Each field of each row takes at least a separator in the CSV.
        if limit is not None and len(data) * len(fieldnames) > limit:
            raise OutputTooLargeError
        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(_capped(f, limit), fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
        return output_path
