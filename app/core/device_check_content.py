# SPDX-License-Identifier: AGPL-3.0-or-later
"""Page copy for ``/device-check``, the local engine's test page.

Like ``tools_content.TOOLS_CONTENT``, the text lives as plain bilingual data
(``de`` / ``en``), not gettext: the page is a technical test, served only with
``LOCAL_TOOLS_ENABLED`` and listed nowhere (app/api/routes/pages.py). ``js``
holds the strings the page's script (app/static/engine/check/device-check.js)
shows; the template hands them over as a JSON data block, and
tests/test_device_check_page.py checks that each key the script uses is here
in both languages.
"""

from __future__ import annotations

from app.core.i18n import normalize_locale

DEVICE_CHECK_CONTENT: dict[str, dict] = {
    "en": {
        "title": "Device check: editing photos in the browser",
        "h1": "Device check: editing photos in the browser",
        "intro": (
            "A technical test, not a tool (about 5 minutes). It measures whether this phone "
            "can shrink a large photo in the browser quickly enough — that decides whether "
            "FileMorph can later do such work right on your device."
        ),
        "privacy": (
            "Your photos are not uploaded: this page edits them only here in your browser and "
            "needs no network for it — the test runs in airplane mode. Your browser also "
            "refuses this page data connections and form uploads; the page checks that "
            "itself. “Copy result” holds the model you entered and the one your browser "
            "reports, the browser and system with its identifier (user agent), cores, memory "
            "and screen size, the date and time of copying, and each check's sizes and "
            "times — no photo, no file name, no location."
        ),
        "model_label": "Which phone is this?",
        "model_placeholder": "e.g. iPhone 13",
        "steps": [
            "Tap “Prepare test” and wait for “Ready”.",
            "Switch on airplane mode (and Wi-Fi off).",
            "Tap “Start test” and leave the phone alone, unlocked, for about two minutes.",
            "Optional: try a photo of your own and one from the camera.",
            "Switch airplane mode off and tap “Copy result”.",
        ],
        "prepare": "Prepare test",
        "start": "Start test",
        "resume": "Run missing checks",
        "own": "Your own photo",
        "camera": "Take a photo",
        "copy_result": "Copy result",
        "results": "Checks",
        "preview": "Last result, made in this browser",
        "fallback": (
            "If this page does not react, or a button stays grey: take a screenshot — with the "
            "name of the phone, that is the result."
        ),
        "back": "Back to the tools",
        "js": {
            "decimalPoint": ".",
            "statusIdle": "Tap “Prepare test”.",
            "statusPreparing": "Preparing the test photos … {percent} %",
            "statusOnline": (
                "Ready. Now switch on airplane mode (and Wi-Fi off), then tap “Start test”."
            ),
            "statusReady": "Ready, already offline. Tap “Start test”.",
            "statusModel": "First enter which phone this is.",
            "statusRunning": (
                "Running: check {n} of {total}. Please keep the phone unlocked and this page open."
            ),
            "statusDone": "Done. Switch airplane mode off, then tap “Copy result”.",
            "statusCopied": "Copied. Paste it wherever you collect the results.",
            "statusCopyFailed": "Copying did not work: select the text below and copy it by hand.",
            "statusCrashed": (
                "The page was reloaded during “{label}” — that counts as a crash. "
                "Tap “Run missing checks” to go on."
            ),
            "statusCrashedDone": (
                "The page was reloaded during “{label}” — that counts as a crash, and the "
                "result has it. Switch airplane mode off, then tap “Copy result”."
            ),
            "statusNotAPhoto": (
                "That file is not a photo this page can read. Take a JPG, PNG, WebP or HEIC photo."
            ),
            "lockOn": (
                "Upload lock: on — your browser refuses this page data connections and form "
                "uploads."
            ),
            "lockOff": (
                "Upload lock: NOT on. Do not use your own photos on this page, and copy the "
                "result anyway."
            ),
            "verdictPass": "Passed: this phone manages every check.",
            "verdictFail": "Not passed: {reason}.",
            "verdictOpen": "Not finished yet: {count} check(s) missing.",
            "reasonCrash": "the page crashed during “{label}”",
            "reasonWrong": "“{label}” gave no usable result",
            "reasonSlow": "“{label}” took {seconds} seconds",
            "label24": "Test photo 24 MP to 2 MB, run {n}",
            "label24Once": "Test photo 24 MP, saved once",
            "label24Worker": "Test photo 24 MP to 2 MB, in the background",
            "label48": "Test photo 48 MP (memory)",
            "labelOwn": "Your photo",
            "labelCamera": "Camera photo",
            "numbers": "{seconds} s · {pixels} MP · {size} MB",
            "numbersLimit": "{seconds} s (target: under 6) · {pixels} MP · {size} MB",
            "numbersFailed": "error: {code}",
            "notCounted": "Not counted: your photo has {mp} MP — the test photo counts.",
            "detected": "Detected: {browser} on {system}, {cores} cores.",
            "unsupported": (
                "This browser lacks {feature}: update it (Settings → General → Software Update), "
                "then run the test and copy the result anyway."
            ),
            "state_passed": "passed",
            "state_slow": "too slow",
            "state_wrong": "wrong result",
            "state_failed": "failed",
            "state_crashed": "crashed",
            "state_invalid": "invalid – repeat",
            "state_measured": "measured",
        },
    },
    "de": {
        "title": "Handy-Test: Fotos im Browser bearbeiten",
        "h1": "Handy-Test: Fotos im Browser bearbeiten",
        "intro": (
            "Ein technischer Test, kein Werkzeug (ca. 5 Minuten). Er misst, ob dieses Handy "
            "ein großes Foto schnell genug im Browser verkleinern kann – davon hängt ab, ob "
            "FileMorph solche Arbeit künftig direkt auf deinem Gerät erledigen kann."
        ),
        "privacy": (
            "Deine Fotos werden nicht hochgeladen: Diese Seite bearbeitet sie nur hier in "
            "deinem Browser und braucht dafür kein Netz – der Test läuft im Flugmodus. Dein "
            "Browser verweigert dieser Seite außerdem Datenverbindungen und Formular-Uploads; "
            "das prüft die Seite selbst. „Ergebnis kopieren“ enthält das eingetragene Modell "
            "und das, das dein Browser meldet, Browser und System samt Kennung (User-Agent), "
            "Kerne, Arbeitsspeicher und Bildschirmgröße, Datum und Uhrzeit des Kopierens sowie "
            "Maße und Zeiten jeder Prüfung – kein Foto, keinen Dateinamen, keinen Standort."
        ),
        "model_label": "Welches Handy ist das?",
        "model_placeholder": "z. B. iPhone 13",
        "steps": [
            "„Test vorbereiten“ tippen und auf „Bereit“ warten.",
            "Flugmodus einschalten (und WLAN aus).",
            "„Test starten“ tippen und das Handy etwa zwei Minuten liegen lassen, nicht sperren.",
            "Freiwillig: ein eigenes Foto und eines direkt aus der Kamera ausprobieren.",
            "Flugmodus ausschalten und „Ergebnis kopieren“ tippen.",
        ],
        "prepare": "Test vorbereiten",
        "start": "Test starten",
        "resume": "Fehlende Prüfungen starten",
        "own": "Eigenes Foto",
        "camera": "Foto aufnehmen",
        "copy_result": "Ergebnis kopieren",
        "results": "Prüfungen",
        "preview": "Letztes Ergebnis, in diesem Browser erstellt",
        "fallback": (
            "Reagiert die Seite nicht oder bleibt ein Knopf grau: Mach einen Screenshot – "
            "zusammen mit dem Namen des Handys ist er das Ergebnis."
        ),
        "back": "Zurück zu den Werkzeugen",
        "js": {
            "decimalPoint": ",",
            "statusIdle": "Tippe auf „Test vorbereiten“.",
            "statusPreparing": "Testfotos werden vorbereitet … {percent} %",
            "statusOnline": (
                "Bereit. Jetzt den Flugmodus einschalten (und WLAN aus), dann „Test starten“ tippen."
            ),
            "statusReady": "Bereit, schon offline. Tippe auf „Test starten“.",
            "statusModel": "Trag zuerst ein, welches Handy das ist.",
            "statusRunning": (
                "Läuft: Prüfung {n} von {total}. Bitte das Handy nicht sperren und diese Seite "
                "offen lassen."
            ),
            "statusDone": "Fertig. Flugmodus ausschalten, dann „Ergebnis kopieren“ tippen.",
            "statusCopied": "Kopiert. Füg es dort ein, wo du die Ergebnisse sammelst.",
            "statusCopyFailed": (
                "Kopieren hat nicht geklappt: Markiere den Text unten und kopiere ihn von Hand."
            ),
            "statusCrashed": (
                "Die Seite wurde während „{label}“ neu geladen – das zählt als Absturz. "
                "Tippe auf „Fehlende Prüfungen starten“, um weiterzumachen."
            ),
            "statusCrashedDone": (
                "Die Seite wurde während „{label}“ neu geladen – das zählt als Absturz und "
                "steht im Ergebnis. Flugmodus ausschalten, dann „Ergebnis kopieren“ tippen."
            ),
            "statusNotAPhoto": (
                "Diese Datei ist kein Foto, das diese Seite lesen kann. Nimm ein JPG-, PNG-, "
                "WebP- oder HEIC-Foto."
            ),
            "lockOn": (
                "Upload-Sperre: aktiv – dein Browser verweigert dieser Seite Datenverbindungen "
                "und Formular-Uploads."
            ),
            "lockOff": (
                "Upload-Sperre: NICHT aktiv. Nimm auf dieser Seite keine eigenen Fotos und "
                "kopier das Ergebnis trotzdem."
            ),
            "verdictPass": "Bestanden: Dein Handy schafft alle Prüfungen.",
            "verdictFail": "Nicht bestanden: {reason}.",
            "verdictOpen": "Noch nicht fertig: {count} Prüfung(en) fehlen.",
            "reasonCrash": "Die Seite ist bei „{label}“ abgestürzt",
            "reasonWrong": "„{label}“ hat kein brauchbares Ergebnis geliefert",
            "reasonSlow": "„{label}“ hat {seconds} Sekunden gebraucht",
            "label24": "Testfoto 24 MP auf 2 MB, Lauf {n}",
            "label24Once": "Testfoto 24 MP, einmal gespeichert",
            "label24Worker": "Testfoto 24 MP auf 2 MB, im Hintergrund",
            "label48": "Testfoto 48 MP (Speicher)",
            "labelOwn": "Dein Foto",
            "labelCamera": "Kamera-Foto",
            "numbers": "{seconds} s · {pixels} MP · {size} MB",
            "numbersLimit": "{seconds} s (Ziel: unter 6) · {pixels} MP · {size} MB",
            "numbersFailed": "Fehler: {code}",
            "notCounted": "Nicht gewertet: Dein Foto hat {mp} MP – es zählt das Testfoto.",
            "detected": "Erkannt: {browser} auf {system}, {cores} Kerne.",
            "unsupported": (
                "Diesem Browser fehlt {feature}: Bitte aktualisieren (Einstellungen → Allgemein → "
                "Softwareupdate), dann den Test machen und das Ergebnis trotzdem kopieren."
            ),
            "state_passed": "bestanden",
            "state_slow": "zu langsam",
            "state_wrong": "falsches Ergebnis",
            "state_failed": "fehlgeschlagen",
            "state_crashed": "abgestürzt",
            "state_invalid": "ungültig – wiederholen",
            "state_measured": "gemessen",
        },
    },
}


def get_device_check_content(locale: str) -> dict:
    return DEVICE_CHECK_CONTENT[normalize_locale(locale)]
