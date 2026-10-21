### Changed — CSV → XLSX and CSV → JSON read the CSV row by row

CSV → XLSX and CSV → JSON check that the uploaded CSV is UTF-8 and then read
it row by row while they convert it, so the memory they take depends on the
longest row, not on the file's size. The output is unchanged: line endings
inside quoted cells stay as uploaded, and a leading BOM (Excel's "CSV UTF-8")
is dropped. A CSV that is not UTF-8 still gets the same `400` and message,
before anything is converted. CSV → XLSX of a very large file can still end
at the conversion's 90-second time limit.
`tests/test_isolated_conversions.py` checks that converting a CSV takes far
less memory than the file's size.
