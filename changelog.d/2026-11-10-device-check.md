### Added — the local engine's first modules and a device check, behind `LOCAL_TOOLS_ENABLED`

The browser engine (`app/static/engine/`, switched off by default) gets its
first real modules: reading an image's format, size and orientation from its
header before anything decodes it, keeping every canvas within the size
Safari on the iPhone still draws (16.7 megapixels), and compressing a photo
to JPEG in the browser — turned upright, without its metadata, once at a set
quality or searching for a target size in at most seven passes. Every step
is timed, and a result is checked: the planned size, upright, not empty.

With the switch on, `/device-check` puts them to work on the device in hand.
It makes its own 24- and 48-megapixel test photos in the browser, so no
photo needs to be at hand or downloaded, compresses them, shows each check
with its time, and gives the whole record under **Copy result** (sizes
and times, browser, system and device model, the date — no photo, file
name or location). A photo of your own or one from the camera can be tried as
well. The page runs under the strict CSP profile `local` and says so — it
checks its own upload lock and asks for airplane mode before the run —
keeps its state in the address after `#` so that a reload after a crashed
tab still knows what ran, answers with `X-Robots-Tag: noindex`, and is
linked from nowhere.

- The test photos carry a red corner, so the check sees that a result came
  out turned, not only at the right size. The placeholder module is gone.
- The browser tests run the device check end to end in Chromium and WebKit,
  with the network cut, and check that it asks for nothing but its own code
  (`tests/browser/test_device_check.py`); the pure modules run under Node
  against Pillow (`tests/test_engine_modules.py`).
- The Docker PR smoke test starts the image once more with the switch on and
  checks that it serves the engine under the hash git computes, with its
  type, `immutable` cache and the `local` CSP, and the device check.
