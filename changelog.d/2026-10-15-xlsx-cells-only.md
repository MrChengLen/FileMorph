### Fixed — XLSX → CSV reads cell values only; a workbook with an active chart sheet converts

XLSX → CSV now opens the workbook for its cell values only: chart sheets are
read without their charts and images, and links to other workbooks are left
unread — a CSV holds none of these. When a chart sheet is the active sheet, the
first worksheet is exported; that used to fail with a `500`. A workbook
without any worksheet gets `400` with `X-FileMorph-Error-Code: invalid_input`
and a message that names the fix. The workbook file is closed after the export, and also when reading
it fails.
