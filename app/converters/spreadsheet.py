# SPDX-License-Identifier: AGPL-3.0-or-later
import csv
import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

from app.converters.base import BaseConverter, InvalidInputError, read_utf8_text
from app.converters.registry import register

if TYPE_CHECKING:
    from openpyxl import Workbook


def _load_cells_only(upload: BinaryIO) -> "Workbook":
    """Open an XLSX for its cell values only.

    Read-only, with stored values instead of formulas, without links to other
    workbooks, and without the drawings (charts, images) of chart sheets — a
    CSV holds none of these; openpyxl's read-only mode already skips the
    drawings of worksheets. ``read_chartsheet`` is openpyxl 3.1.5's without
    its drawings; re-check it on an openpyxl upgrade. Same as
    ``openpyxl.load_workbook`` otherwise.
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
                writer = csv.writer(f)
                for row in ws.iter_rows(values_only=True):
                    writer.writerow(["" if v is None else str(v) for v in row])
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
        rows = list(csv.DictReader(io.StringIO(read_utf8_text(input_path), newline="")))
        output_path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
        return output_path


@register(("json", "csv"))
class JsonToCsvConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        data = json.loads(read_utf8_text(input_path))
        if not isinstance(data, list) or not data:
            raise InvalidInputError("JSON must be a non-empty array of objects for CSV conversion.")
        fieldnames = list(data[0].keys())
        with output_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(data)
        return output_path
