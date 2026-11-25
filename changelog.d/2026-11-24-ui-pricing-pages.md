### Changed — pricing and Compliance Edition pages: shared cards and buttons, readable fine print

/pricing and the Compliance Edition page (/enterprise) now use the same
building blocks as the rest of the site:

- Fine print (limits, fair use, footnotes, the note on what is not done yet)
  is 14 px in a readable column instead of 12 px across the page. The
  Compliance Edition page's running text is 16 px instead of 14 px, in a
  column of at most 42rem.
- /pricing: the answers to the cost questions are 16 px instead of 14 px,
  with room between the questions; the blocks are 48 px apart instead of
  40 px; the "what you can verify" list has two columns instead of three
  between 640 and 1023 px; the small labels above the two free offers use the
  same grey as every other such label.
- Every button-style call to action is the shared button, at least 48 px high
  (some were 40 px).
- The Compliance Edition page has one heading size per level: the page
  heading grows with the screen like on the other pages (26 to 36 px, was 30
  or 36 px), and its section headings take the heading colour of the other
  pages instead of white. Its cards and tables share the site's look, and its
  blocks of three columns stack until 1024 px instead of 640 px. "Apply →"
  scrolls the design-partner heading right to the top of the screen (it left
  80 px of space above it).
- ✓ lists: the tick sits on the line of its text (it sat about 2 px low).
- Links in running text are underlined (they were told apart by colour
  alone), including the hosting note that also appears on the start page and
  the redaction page.
- Where plans can be booked (servers with Stripe; not filemorph.io): the plan
  cards stack until 1024 px instead of squeezing into three 222 px columns
  from 768 px; the highlighted plan is the shared card with its badge; the
  audience switch is the shared mode switch, 44 px high on a phone and
  announced as a group instead of as tabs; the waiver text next to the
  upgrade buttons is 14 px instead of 12 px.

Texts and links are unchanged. Under the hood: `card(badge=…)`,
`button(external=…)` and a `check_item` component; `button(disabled=True)`
keeps its variant, so a script can enable the button later;
`tests/test_layout_standards.py` covers both pages and `pricing-segment.js`.
