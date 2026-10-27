### Added — a page for Video → GIF: `/convert/video-to-gif`

Turning a short video into an animated GIF (added in 1.3.0) now has its own
page, one for every video format: MP4, MOV, AVI, MKV, WebM, FLV and WMV. It
states the limits before anything is uploaded (up to 30 seconds, 10 frames per
second, at most 480 × 480 pixels, no sound, and the 30 MB upload limit without
an account) and embeds the converter, pre-set to GIF. Until now the conversion
showed up only in the target list after a video was chosen and as plain text
on `/formats`. The page is listed on `/tools`, linked from `/compress` and in
the footer, the sitemap and `/llms.txt`.

On every page that is pre-set to a target (the conversion pages and this one),
each file of a batch now starts at that target too; until now only a single
file did.
