### Changed — `/convert/batch` refuses a target format longer than 16 characters up front

`POST /api/v1/convert/batch` now looks at every `target_formats` value before
it processes any file. A value longer than 16 characters — no format FileMorph
knows comes close; the longest has 4 — refuses the whole batch with `422` and
"Unknown target format. GET /api/v1/formats lists the supported ones.", the
way a mismatch between the number of `files` and `target_formats` values
already does. A shorter unknown value still fails only its own file, as
before. A test checks that every registered target fits under the limit, so a
new converter with a longer format name can't be refused by the batch route
without CI noticing.
