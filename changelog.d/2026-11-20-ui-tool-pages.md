### Changed — tool pages: readable text, one message box, bigger tap targets

The tool pages (/compress, /convert/…, /pdf/…, and where they are switched on
/redact and /device-check) and the tool card on the homepage now follow one
design language:

- Only the tool is a card. The sections below it (honest limits, how it works,
  FAQ, related tools) have no boxes any more, a hairline above each, 18 px
  headings and 16 px text in lines of at most about 65 characters (was 12 px
  in lines of about 118). The line under each page heading is 16 px.
- Every hint, warning, success line and error is one box: a soft tint in its
  tone (information, success, warning, error) with a small round icon, 14 px
  text and the same corners. There were 19 boxes in 9 styles.
- Drop fields, mode switches and buttons look the same on every tool: the
  download button matches the start button (48 px, same corners), "Process
  another file", "Clear" and the next-step links are real buttons (36 px
  instead of 16-px text links), the related tools are 44-px chips.
- On a phone: the file name in a batch gets its own line (it shrank to 5–95 px
  at 320–390 px), the remove button is 44 px (was 10 × 16 px), and the mode
  switches and the "Where?" choices of /pdf/insert are 44-px rows. Cards on
  every page (also sign-in, pricing, the dashboard) keep 16 px of inner space
  on a phone instead of 24 px.
- While a file is dragged over the drop field of /pdf/… and /redact, its
  border now turns brand-coloured; it stayed grey there before.
- A missing input on the convert and compress tools ("select a file", "choose
  a target format") is shown in the tool's error box instead of a browser
  dialog, as the PDF tools already did; the box goes as soon as the input is
  given.
- Enter or Space on a button inside a drop field ("Clear", a file's remove
  button) works that button instead of opening the file picker.
- A button that a page disables while it works (a tool's start button,
  "Signing in…" on the sign-in page) looks disabled on every page, with its
  text still readable.

Texts, links and addresses are unchanged. Under the hood: new components
`notice`, `dropzone`, `segmented` and `chip`, a `success` variant of `button`,
`section(divided=True)`, status-tone colour tokens, and
`tests/test_layout_standards.py` now keeps the tool templates and their scripts
on the design tokens.
