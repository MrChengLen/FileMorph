# SPDX-License-Identifier: AGPL-3.0-or-later
"""Landing-page content for ``/convert/video-to-mp3``.

One page for every video format, as for ``/convert/video-to-gif``
(``video_gif_content``): saving the sound of a video is the same task
whatever the source container. The page is pre-set to MP3; the converter's
other audio targets are in its list. Like the other content modules the
prose is plain bilingual data (``de`` / ``en``); the page chrome is
translated in ``templates/layouts/tool_page.html``.

Every fact stated here is the converter's own (``VideoToAudioConverter`` in
``app/converters/video.py``, documented in ``docs/formats.md``): the first
audio track only, no metadata from the video, a video without sound refused,
the audio targets of ``_AUDIO_TARGETS``, and the anonymous upload limit.
"""

from __future__ import annotations

from app.core.i18n import normalize_locale

# Per-locale fields: title (<=48 chars), meta (50-160), h1, hero, limits,
# how_it_works [(step, text)], when, faq [(question, answer)].
VIDEO_AUDIO_CONTENT: dict[str, dict] = {
    "en": {
        "title": "Convert a video to MP3 online — free",
        "meta": (
            "Save the sound of a video (MP4, MOV, MKV, WebM and more) as MP3, M4A or "
            "WAV online for free, no account. Files deleted right after."
        ),
        "h1": "Convert a video to MP3",
        "hero": (
            "Save the sound of an MP4, MOV, MKV or WebM video as an MP3 — or as M4A, "
            "WAV and other audio formats."
        ),
        "limits": (
            "Only the sound is saved: the video's first audio track — if it has "
            "several, such as one per language, the first one. A video without sound "
            "is refused with a note. The audio file carries no location, device, "
            "date, title or chapters from the video. The video file must fit the "
            "upload limit of 30 MB without an account, and the audio file the "
            "output-size limit like any other download: a long video saved as WAV, "
            "which is uncompressed, can pass it — choose MP3 or M4A, a fraction of "
            "the size."
        ),
        "how_it_works": [
            (
                "Choose your video",
                "MP4, MOV, AVI, MKV, WebM, FLV or WMV. MP3 is pre-set; M4A, WAV, FLAC, "
                "OGG, AAC, Opus and WMA are in the list.",
            ),
            (
                "Server saves the sound",
                "ffmpeg takes the first audio track from the video and encodes it in "
                "the format you chose; the picture is left out.",
            ),
            (
                "Download the audio file",
                "The video is deleted right after, and the audio file carries no "
                "location, device or date from it.",
            ),
        ],
        "when": (
            "Use it when only the sound matters: a talk, a lecture, an interview or a "
            "voice note that was recorded as a video. An audio file is much smaller "
            "than the video, plays in any music or podcast app and opens in an audio "
            "editor as it is."
        ),
        "faq": [
            (
                "Which audio format should I choose?",
                "MP3 plays everywhere. M4A (AAC) sounds better at the same size and is "
                "Apple's default. WAV and FLAC add no further loss, for editing — both "
                "are several times the size of an MP3 (WAV uncompressed, FLAC "
                "compressed without loss). OGG and Opus are open formats; WMA is a "
                "legacy Windows format. Surround sound becomes stereo for MP3, Opus "
                "and WMA, and stays for the others.",
            ),
            (
                "Why was my video refused?",
                "It has no sound, the file is over the upload limit, or it is in a "
                "format FileMorph doesn't read. A video without sound has nothing to "
                "save: choose one with sound. A file over the upload limit: export the "
                "video at a lower resolution first — the sound stays the same. Another "
                "format: save the video as MP4 first.",
            ),
            (
                "Do I need an account?",
                "No. The conversion works without an account, and the video is "
                "deleted right after.",
            ),
        ],
    },
    "de": {
        "title": "Video in MP3 umwandeln — kostenlos",
        "meta": (
            "Den Ton eines Videos (MP4, MOV, MKV, WebM und mehr) kostenlos online als "
            "MP3, M4A oder WAV speichern, ohne Konto. Dateien sofort gelöscht."
        ),
        "h1": "Video in MP3 umwandeln",
        "hero": (
            "Den Ton eines MP4-, MOV-, MKV- oder WebM-Videos als MP3 speichern – oder "
            "in M4A, WAV und weiteren Audioformaten."
        ),
        "limits": (
            "Gespeichert wird nur der Ton: die erste Tonspur des Videos – hat es "
            "mehrere, etwa eine pro Sprache, die erste. Ein Video ohne Ton wird mit "
            "einem Hinweis abgelehnt. Die Audiodatei übernimmt keinen Ort, kein Gerät, "
            "kein Datum, keinen Titel und keine Kapitel aus dem Video. Die Videodatei "
            "muss in die Upload-Grenze von 30 MB ohne Konto passen und die Audiodatei "
            "wie jeder Download in die Größengrenze für Ergebnisse: Ein langes Video "
            "als WAV, das unkomprimiert ist, kann sie überschreiten – wähle dann MP3 "
            "oder M4A, die nur einen Bruchteil so groß sind."
        ),
        "how_it_works": [
            (
                "Video wählen",
                "MP4, MOV, AVI, MKV, WebM, FLV oder WMV. MP3 ist voreingestellt; M4A, "
                "WAV, FLAC, OGG, AAC, Opus und WMA stehen in der Liste.",
            ),
            (
                "Der Server speichert den Ton",
                "ffmpeg nimmt die erste Tonspur aus dem Video und kodiert sie im "
                "gewählten Format; das Bild bleibt außen vor.",
            ),
            (
                "Audiodatei herunterladen",
                "Das Video wird danach sofort gelöscht, und die Audiodatei übernimmt "
                "keinen Ort, kein Gerät und kein Datum daraus.",
            ),
        ],
        "when": (
            "Wenn nur der Ton zählt: ein Vortrag, eine Vorlesung, ein Interview oder "
            "eine Sprachnotiz, die als Video aufgenommen wurde. Eine Audiodatei ist "
            "viel kleiner als das Video, läuft in jeder Musik- oder Podcast-App und "
            "lässt sich direkt in einem Audio-Editor öffnen."
        ),
        "faq": [
            (
                "Welches Audioformat soll ich wählen?",
                "MP3 läuft überall. M4A (AAC) klingt bei gleicher Größe besser und ist "
                "Apples Standard. WAV und FLAC verlieren nichts weiter, zum Bearbeiten – "
                "beide sind ein Vielfaches einer MP3 (WAV unkomprimiert, FLAC "
                "verlustfrei komprimiert). OGG und Opus sind offene Formate; WMA ist "
                "ein altes Windows-Format. Raumklang wird bei MP3, Opus und WMA zu "
                "Stereo, bei den anderen bleibt er erhalten.",
            ),
            (
                "Warum wurde mein Video abgelehnt?",
                "Es hat keinen Ton, die Datei ist größer als die Upload-Grenze, oder "
                "sie hat ein Format, das FileMorph nicht liest. Ein Video ohne Ton hat "
                "nichts zu speichern: Wähle eines mit Ton. Ist die Datei zu groß, "
                "exportiere das Video vorher in einer geringeren Auflösung – der Ton "
                "bleibt dabei gleich. Bei einem anderen Format: Speichere das Video "
                "vorher als MP4.",
            ),
            (
                "Brauche ich ein Konto?",
                "Nein. Die Umwandlung funktioniert ohne Konto, und das Video wird direkt "
                "danach gelöscht.",
            ),
        ],
    },
}


def get_video_audio_content(locale: str) -> dict:
    """Return the localized ``/convert/video-to-mp3`` content block."""
    return VIDEO_AUDIO_CONTENT[normalize_locale(locale)]
