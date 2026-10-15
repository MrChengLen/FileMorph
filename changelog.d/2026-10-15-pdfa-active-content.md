### Security — PDF → PDF/A removes active content from pages, annotations, form fields and bookmarks

PDF → PDF/A (`target_format=pdfa`) removes the active content PDF/A-2
forbids and the files attached to the document, its pages and annotations, on
the Ghostscript output and on the markup-only path alike:

- from the document: additional actions (`/AA`), the open action, JavaScript,
  XFA forms, attached and associated files, portfolios, alternate
  presentations, renditions and page templates;
- from every page: additional actions, presentation steps, associated files,
  and file-attachment, sound, movie, screen, 3D and rich-media annotations;
- from the other annotations: additional actions and associated files;
- from form fields and their widgets: every action, as PDF/A-2 requires;
- from links and bookmarks: every action type PDF/A-2 does not permit, and from
  a permitted one the actions chained after it and an embedded copy of the file
  it opens.

Links (URI, GoTo and the other permitted types) and page navigation stay. A
PDF with an extreme number of pages, annotations, form fields and bookmarks
(around 200,000 together) gets a `400` (`invalid_input`) instead of a
half-checked PDF/A.

The comment on Ghostscript's `-dPDFACompatibilityPolicy=1` now says what the
setting does: Ghostscript drops a feature PDF/A-2 forbids and goes on writing
PDF/A.

Tests convert PDFs without Ghostscript and check what is left: active content
on a page, its annotations, form fields (one of them reached only through its
widget) and bookmarks; an attachment a popup still points to; an annotation
list two pages share; and malformed entries, among them names that aren't
UTF-8.
