### Security — text on a page stays text

Every page carries two JSON blocks inside `<script>` elements: the text
catalogue the scripts read, and the structured data for search engines. Both
are now written with Jinja's HTML-safe JSON encoding (the one behind
`|tojson`): `<`, `>`, `&` and `'` become JSON Unicode escapes, so no text — a
future translation, a configured base URL — can end the element or open a
comment, and a JSON parser reads the same data.

The scripts no longer put values into the page unescaped: three empty states
are set as text, and the account menu and the API-key list escape what they
show (e-mail address, key name, labels).
