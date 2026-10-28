### Changed — the homepage's quick actions come in groups, now with “Insert PDF pages” and “Video to GIF”

The quick actions under the converter on the homepage now sit in groups named
after the `/tools` sections: “PDF tools”, “Images” and “More tools”. Two tools
join them, so there are nine:

- “Insert PDF pages” (`/pdf/insert`);
- “Video to GIF” (`/convert/video-to-gif`).

Unchanged: the converter, its target list and the “All tools →” link. The groups
come from the page catalogue (`app/core/catalog.py`) and follow the section rule
of `/tools`, so a tool sits under the same name on both pages. The catalogue now
allows up to twelve quick actions, at most six to a group.
