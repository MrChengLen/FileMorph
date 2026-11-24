### Changed — text pages: 16 px text, one page header, readable lists

The security policy, privacy policy, terms of use, Impressum and contact page
now read like the tool pages:

- Body text is 16 px instead of 14 px (the Impressum mixed 14 and 16 px),
  sections are 48 px apart and their headings 18 px.
- One page header on all five pages: a 24 px back link, the page heading in
  the shared size (it grows with the screen like on the tool pages), and the
  date or legal basis under it.
- Lists indent their wrapped lines instead of running them back under the
  bullet; links in the text are underlined (they were told apart by colour
  alone).
- The Impressum's address is one address block, and its headings look like
  those of the other legal pages (they were small grey capitals).
- "In scope" and "Out of scope" on the security policy are sub-headings.
- The contact form shows its outcome in the message box: green-tinted when
  the message went out, red-tinted with "!" when it did not. The
  confirmation was plain grey text before; the errors did not show at all
  (see the fix for that).

Texts, links and addresses are unchanged. Under the hood: a `page_header`
component, `notice` takes data-* attributes, and
`tests/test_layout_standards.py` keeps the five pages and `contact.js` on the
design tokens.
