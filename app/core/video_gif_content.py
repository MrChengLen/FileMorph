# SPDX-License-Identifier: AGPL-3.0-or-later
"""Landing-page content for ``/convert/video-to-gif``.

One page for every video format instead of seven pair pages: the task is the
same whatever the source container. Like ``compress_content`` and
``pdf_tools_content`` the prose is plain bilingual data (``de`` / ``en``);
the page chrome is translated in ``templates/layouts/tool_page.html``.

Every limit stated here is the converter's own (``app/converters/video.py``,
``GIF_*`` in ``app/converters/_ffmpeg.py``, documented in ``docs/formats.md``):
up to 30 seconds (a longer video is refused, never cut short), 10 frames per
second, fitted into 480 × 480 pixels, no sound, no metadata from the video.
"""

from __future__ import annotations

from app.core.i18n import normalize_locale

# Per-locale fields: title (<=48 chars), meta (50-160), h1, hero, limits,
# how_it_works [(step, text)], when, faq [(question, answer)].
VIDEO_GIF_CONTENT: dict[str, dict] = {
    "en": {
        "title": "Convert a video to GIF online — free",
        "meta": (
            "Turn a short video clip (MP4, MOV, WebM and more, up to 30 seconds) "
            "into an animated GIF online for free, no account. Files deleted right after."
        ),
        "h1": "Convert a video to GIF",
        "hero": "Turn a short clip — MP4, MOV, WebM and more — into an animated GIF that loops.",
        "limits": (
            "The video may be up to 30 seconds long: a longer one is refused, not cut "
            "short — shorten it first, or convert it to MP4 or WebM instead. The GIF "
            "fits into 480 × 480 pixels at 10 frames per second, loops endlessly and "
            "has no sound, since GIF carries none. A video larger than 4096 × 2160 "
            "pixels is refused, and the GIF must fit the output-size limit like any "
            "other download. The video file must also fit the upload limit of 30 MB "
            "without an account. A 30-second Full-HD phone clip is often larger: "
            "export it at 720p first — the GIF is no larger than 480 × 480 pixels anyway."
        ),
        "how_it_works": [
            ("Choose your video", "MP4, MOV, AVI, MKV, WebM, FLV or WMV, up to 30 seconds."),
            (
                "Server makes the GIF",
                "ffmpeg picks one 256-colour palette for the whole clip, then maps every "
                "frame onto it, so areas that don't change stay identical and the file "
                "stays small.",
            ),
            (
                "Download the GIF",
                "The video is deleted right after, and the GIF carries no location, "
                "device or date from it.",
            ),
        ],
        "when": (
            "Use it for a short clip that has to play anywhere without a player — in "
            "a chat, a support ticket, a README or a slide. For anything longer, or "
            "with sound, a video file is the better choice: GIF knows only 256 colours "
            "and grows large quickly."
        ),
        "faq": [
            (
                "Why was my video refused?",
                "It is longer than 30 seconds, the file is over the upload limit, the "
                "video is larger than 4096 × 2160 pixels, or it is too complex to finish "
                "in time. A longer clip is refused rather than cut short: shorten it "
                "first, or convert it to MP4 or WebM instead. A file over the upload "
                "limit or a video above 4K: export it at 720p first — the GIF is no "
                "larger than 480 × 480 pixels anyway. Too complex: use a shorter clip or a "
                "lower resolution.",
            ),
            (
                "Does the GIF keep the sound?",
                "No. GIF is an image format and carries no audio. If you need the "
                "sound, convert the video to MP4 or WebM instead.",
            ),
            (
                "Do I need an account?",
                "No. The conversion works without an account, and the video is "
                "deleted right after.",
            ),
        ],
    },
    "de": {
        "title": "Video in GIF umwandeln — kostenlos",
        "meta": (
            "Kurze Videos (MP4, MOV, WebM und mehr, bis 30 Sekunden) kostenlos online "
            "in ein animiertes GIF umwandeln, ohne Konto. Dateien sofort gelöscht."
        ),
        "h1": "Video in GIF umwandeln",
        "hero": (
            "Einen kurzen Clip – MP4, MOV, WebM und mehr – in ein animiertes GIF "
            "umwandeln, das endlos läuft."
        ),
        "limits": (
            "Das Video darf bis zu 30 Sekunden lang sein: Ein längeres wird abgelehnt, "
            "nicht gekürzt – kürze es vorher oder wandle es stattdessen in MP4 oder "
            "WebM um. Das GIF passt in 480 × 480 Pixel, läuft mit 10 Bildern pro "
            "Sekunde in Endlosschleife und hat keinen Ton, denn GIF kann keinen. Ein "
            "Video über 4096 × 2160 Pixel wird abgelehnt, und das GIF muss wie jeder "
            "Download in die Größengrenze für Ergebnisse passen. Außerdem muss die "
            "Videodatei in die Upload-Grenze von 30 MB ohne Konto passen. Ein "
            "30-Sekunden-Clip in Full HD vom Handy ist oft größer: Exportiere ihn "
            "vorher in 720p – das GIF passt ohnehin in 480 × 480 Pixel."
        ),
        "how_it_works": [
            ("Video wählen", "MP4, MOV, AVI, MKV, WebM, FLV oder WMV, bis 30 Sekunden."),
            (
                "Der Server erstellt das GIF",
                "ffmpeg wählt eine Palette mit 256 Farben für den ganzen Clip und setzt "
                "jedes Bild daraus zusammen. Was sich nicht bewegt, bleibt gleich – das "
                "hält die Datei klein.",
            ),
            (
                "GIF herunterladen",
                "Das Video wird danach sofort gelöscht, und das GIF übernimmt keinen "
                "Ort, kein Gerät und kein Datum daraus.",
            ),
        ],
        "when": (
            "Für einen kurzen Clip, der überall ohne Player laufen soll – im Chat, in "
            "einem Support-Ticket, in einer README oder auf einer Folie. Für längere "
            "Clips oder solche mit Ton ist eine Videodatei besser: GIF kennt nur 256 "
            "Farben und wird schnell groß."
        ),
        "faq": [
            (
                "Warum wurde mein Video abgelehnt?",
                "Es ist länger als 30 Sekunden, die Datei ist größer als die "
                "Upload-Grenze, das Video hat mehr als 4096 × 2160 Pixel, oder es ist zu "
                "aufwendig, um rechtzeitig fertig zu werden. Ein längeres Video wird "
                "abgelehnt statt gekürzt: Kürze es vorher oder wandle es in MP4 oder "
                "WebM um. Bei einer zu großen Datei oder einem Video über 4K: Exportiere "
                "das Video vorher in 720p – das GIF passt ohnehin in 480 × 480 Pixel. Ist "
                "es zu aufwendig, hilft ein kürzerer Clip oder eine geringere Auflösung.",
            ),
            (
                "Behält das GIF den Ton?",
                "Nein. GIF ist ein Bildformat und hat keinen Ton. Brauchst du den Ton, "
                "wandle das Video in MP4 oder WebM um.",
            ),
            (
                "Brauche ich ein Konto?",
                "Nein. Die Umwandlung funktioniert ohne Konto, und das Video wird direkt "
                "danach gelöscht.",
            ),
        ],
    },
}


def get_video_gif_content(locale: str) -> dict:
    """Return the localized ``/convert/video-to-gif`` content block."""
    return VIDEO_GIF_CONTENT[normalize_locale(locale)]
