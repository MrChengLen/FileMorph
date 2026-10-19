### Changed — Table conversions stop at the output cap

XLSX → CSV, JSON → CSV and CSV → JSON stop writing as soon as the output
passes your tier's output cap, instead of writing the whole file first. They
answer `413` with `X-FileMorph-Error-Code: output_cap_exceeded` and "Output
too large (over the N MB cap). Split the table into smaller files and convert
them one by one …" on `/convert`, and "Output too large (over the N MB cap).
Split the table or upgrade your plan." per file on `/convert/batch`. JSON →
CSV refuses a table whose rows × columns alone can't fit before writing
anything. A conversion that fits writes the same file as before.
