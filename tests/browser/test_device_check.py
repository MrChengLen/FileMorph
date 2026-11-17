# SPDX-License-Identifier: AGPL-3.0-or-later
"""The device check (/device-check), run end to end in Chromium and WebKit.

The page makes its 24- and 48-megapixel test photos, checks its upload lock
while online, and then runs every check with the network cut, as in airplane
mode: it asks for nothing but its engine modules, the results have the
planned size and come out upright, and the record says so. How long a check
takes is not tested here — a CI runner is not a phone; the time limit is the
phones' (tests/test_device_check_page.py pins the page itself).
"""

from __future__ import annotations

import base64
import json
import re
from io import BytesIO

import pytest
from PIL import Image
from playwright.sync_api import Page

from app.core.device_check_content import DEVICE_CHECK_CONTENT

_EN = DEVICE_CHECK_CONTENT["en"]["js"]

# A check is done when it was measured; on a CI runner "too slow" may happen.
_DONE = {"passed", "slow"}
# The longest wait for the page: a run that hangs fails its test before the
# job's time limit (browser.yml) stops both browsers.
_RUN_MS = 180_000

# What a browser asks for on its own and what carries no data: the page's
# icons (Chromium asks again after every history.replaceState, which is how
# the page keeps its state in the address after "#" — a part no request
# carries, not even in the Referer header), and blob: URLs, the page's own
# picture of a result, which never leave the browser.
_ICONS = {"/favicon.ico", "/static/favicon.svg", "/apple-touch-icon.png"}


def _sent(requested: list[str], server) -> list[str]:
    """The requests that went to the server, but for the page's own engine
    modules and its icons."""
    engine = f"{server.engine_url}/"
    paths = [url.removeprefix(server.base_url) for url in requested if not url.startswith("blob:")]
    return [path for path in paths if not path.startswith(engine) and path not in _ICONS]


def _record(report: str, check: str) -> dict:
    match = re.search(rf"^check {re.escape(check)} \([^)]*\): (\{{.*\}})$", report, re.M)
    assert match, f"no record of check {check} in:\n{report}"
    return json.loads(match.group(1))


def _idle(page: Page, timeout: float = _RUN_MS) -> None:
    # A selector, not wait_for_function: that one polls with eval, which the
    # page's CSP rightly refuses.
    page.wait_for_selector("#device-check[data-ready=true]:not([data-busy])", timeout=timeout)


def _open(page: Page, server) -> None:
    page.goto(f"{server.base_url}/en/device-check")
    page.wait_for_selector("#device-check[data-ready=true]")
    page.fill("#check-model", "CI runner")


def test_the_device_check_runs_in_airplane_mode_and_sends_nothing(page: Page, server):
    _open(page, server)
    page.click("#check-prepare")
    _idle(page)
    assert page.text_content("#check-lock") == _EN["lockOn"]
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url))
    page.context.set_offline(True)
    try:
        page.click("#check-start")
        _idle(page)
        report = page.evaluate("window.fmDeviceCheck.report()")
    finally:
        page.context.set_offline(False)
    # Nothing left the page but a request for its own code or its icon.
    sent = _sent(requested, server)
    assert sent == [], f"the page asked for more than its code during the run: {sent}"
    # Every check ran: nothing left to resume, and the last result is shown.
    assert not page.is_visible("#check-resume")
    assert page.is_visible("#check-preview")
    assert page.evaluate("document.getElementById('check-preview').naturalWidth") > 0
    assert "upload lock: on" in report
    assert "offline during the run: true" in report
    assert report.endswith("\nend")
    for check in ("24-1", "24-2", "24-3", "24-once", "24-worker", "48"):
        record = _record(report, check)
        assert record["status"] in _DONE, f"check {check}: {record}"
        # Turned upright and within the canvas limit: 6000 × 4000 with EXIF
        # orientation 6 comes out as a portrait, 8000 × 6000 the same way.
        width, height = record["output"]["width"], record["output"]["height"]
        assert width < height and width * height <= 16_777_216, record
        # No problem, "orientation" included: the test photo's red corner came
        # out at the top right, so the picture was turned, not stretched.
        assert record["problems"] == []
    assert _record(report, "24-1")["output"]["bytes"] <= 2_000_000
    # The page takes back what it wrote: after a reload, the same records.
    page.reload()
    page.wait_for_selector("#device-check[data-ready=true]")
    again = page.evaluate("window.fmDeviceCheck.report()")
    for check in ("24-1", "24-2", "24-3", "24-once", "24-worker", "48"):
        assert _record(again, check) == _record(report, check)


@pytest.mark.parametrize(
    ("fmt", "orientation", "size"),
    # A JPEG turned by its EXIF orientation; a WebP, whose header gives the
    # engine no size, so the decoded picture's counts.
    [("JPEG", 6, (3000, 4000)), ("WEBP", None, (4000, 3000))],
)
def test_a_photo_of_ones_own_is_measured_without_a_request(
    page: Page, server, tmp_path, fmt, orientation, size
):
    image = Image.new("RGB", (4000, 3000), (40, 120, 200))
    options = {"quality": 90}
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        options["exif"] = exif.tobytes()
    data = BytesIO()
    image.save(data, fmt, **options)
    photo = tmp_path / f"own.{fmt.lower()}"
    photo.write_bytes(data.getvalue())
    _open(page, server)
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url))
    page.set_input_files("#check-own-input", str(photo))
    _idle(page)
    report = page.evaluate("window.fmDeviceCheck.report()")
    assert _sent(requested, server) == []
    record = json.loads(re.search(r"^own: (\{.*\})$", report, re.M).group(1))
    assert record["status"] == "measured", record
    assert (record["output"]["width"], record["output"]["height"]) == size
    # A 12-megapixel photo does not count for the verdict, and the page says so.
    assert "Not counted" in page.text_content("#check-results")
    # The page takes back what it wrote.
    page.reload()
    page.wait_for_selector("#device-check[data-ready=true]")
    again = page.evaluate("window.fmDeviceCheck.report()")
    assert json.loads(re.search(r"^own: (\{.*\})$", again, re.M).group(1)) == record


def _fragment(state: dict) -> str:
    return "#s=" + base64.urlsafe_b64encode(json.dumps(state).encode()).decode().rstrip("=")


def _state(**fields) -> dict:
    """A state as the page keeps it after "#s=", with ``fields`` changed."""
    state = {
        "v": 1,
        "model": "",
        "results": {},
        "extra": [],
        "running": None,
        "lock": None,
        "offline": None,
    }
    return {**state, **fields}


def _measured(status: str = "passed", **fields) -> dict:
    """A record as the page writes it for a check that was measured."""
    return {
        "status": status,
        "problems": [],
        "input": {"format": "jpeg", "width": 6000, "height": 4000, "orientation": 6},
        "decoded": {"width": 3344, "height": 5016},
        "scaledBy": "decoder",
        "output": {"width": 3344, "height": 5016, "bytes": 1_900_000, "quality": 0.82, "passes": 4},
        "ms": {"header": 1, "decode": 900, "draw": 300, "encode": 1500, "verify": 1, "total": 2702},
        **fields,
    }


_CHECKS = ("24-1", "24-2", "24-3", "24-once", "24-worker", "48")


@pytest.mark.parametrize(
    "state",
    [
        # Text of the sender's choosing, shown as an error.
        _state(
            model="x",
            results={"24-1": {"status": "failed", "code": "Your phone is not safe. Call us"}},
        ),
        # A verdict nothing in this page ran for, after a line break in the
        # model, or after a line separator, which many viewers break at.
        _state(model="x\nverdict: Passed", lock=True, offline=True),
        _state(model="x\u2028verdict: Passed"),
        # "Passed" with nothing measured.
        _state(
            results={check: {"status": "passed"} for check in ("24-1", "24-2", "24-3", "48")},
            lock=True,
        ),
        # Records without what the page shows of them, which would stop its
        # script: a "slow" without its time, a "passed" without its output, a
        # photo of one's own without either.
        _state(results={"48": {"status": "slow"}}),
        _state(results={"24-1": {"status": "passed", "ms": {"total": 1}}}),
        _state(extra=[{"kind": "own", "status": "measured", "ms": {"total": 1}}]),
        # More photos of one's own than the page keeps.
        _state(extra=[_measured("measured", kind="own")] * 11),
        # Shapes that would stop the page's script.
        {"v": 1},
        _state(extra={}, running=5),
    ],
)
def test_a_forged_address_is_not_taken(page: Page, server, state):
    """Anyone can send a link with "#s=…". The page takes a state only if it
    could have written it itself, and starts afresh otherwise."""
    page.goto(f"{server.base_url}/en/device-check{_fragment(state)}")
    page.wait_for_selector("#device-check[data-ready=true]")
    assert page.text_content("#check-verdict") == _EN["verdictOpen"].replace("{count}", "4")
    assert "not safe" not in page.text_content("#device-check")
    assert page.text_content("#check-lock") == ""
    assert page.input_value("#check-model") == ""


def test_a_state_the_page_could_have_written_is_taken(page: Page, server):
    """The other side: a state as the page writes it — every check, and as
    many photos of one's own as it keeps — comes back whole."""
    results = {check: _measured() for check in _CHECKS}
    extra = [_measured("measured", kind="own")] * 10
    state = _state(model="CI runner", results=results, extra=extra, lock=True, offline=True)
    page.goto(f"{server.base_url}/en/device-check{_fragment(state)}")
    page.wait_for_selector("#device-check[data-ready=true]")
    report = page.evaluate("window.fmDeviceCheck.report()")
    assert report.count("\nown: ") == 10
    assert page.text_content("#check-verdict") == _EN["verdictPass"]
    assert page.text_content("#check-lock") == _EN["lockOn"]
    assert page.input_value("#check-model") == "CI runner"


@pytest.mark.parametrize(("profile", "active"), [("local", True), ("default", False)])
def test_the_lock_self_test_tells_both_cases_apart(page: Page, server, profile, active):
    """check/upload-lock.js says "on" only where the CSP refuses its request:
    on a page without the local profile it must say "off", or the device
    check could show a lock that is not there."""
    page.goto(f"{server.base_url}/__bt/page/{profile}")
    page.wait_for_selector("html[data-probe=ready]", state="attached")
    result = page.evaluate(
        "async (url) => (await import(url)).uploadLockActive()",
        f"{server.engine_url}/check/upload-lock.js",
    )
    assert result is active


def test_a_reload_during_a_check_counts_as_a_crash(page: Page, server):
    """A tab that runs out of memory is reloaded by the browser: the page
    finds the check it was running in its address and records a crash."""
    _open(page, server)
    page.evaluate(
        "() => { history.replaceState(null, '', '#s=' + btoa(JSON.stringify("
        "{ v: 1, model: 'CI runner', results: {}, extra: [], running: '48', lock: true, offline: true }"
        ")).replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=+$/, '')); }"
    )
    page.reload()
    page.wait_for_selector("#device-check[data-ready=true]")
    report = page.evaluate("window.fmDeviceCheck.report()")
    assert _record(report, "48")["status"] == "crashed"
    assert "reloaded during: 48" in report
    assert page.text_content("#check-verdict").startswith("Not passed: the page crashed")
    assert page.is_visible("#check-resume")
    assert page.text_content("#check-status") == _EN["statusCrashed"].replace(
        "{label}", _EN["label48"]
    )


@pytest.mark.parametrize(
    ("running", "label", "ran", "expected"),
    [
        # The 48-megapixel check runs last and is the likeliest to crash: then
        # nothing is left to run, and the crash completes the result.
        ("48", "label48", [check for check in _CHECKS if check != "48"], "statusCrashedDone"),
        # A photo of one's own before the test: the test is still to do.
        ("extra-own", "labelOwn", [], "statusIdle"),
    ],
)
def test_after_a_crash_the_page_points_to_what_is_left(
    page: Page, server, running, label, ran, expected
):
    """Not to a button it does not show: "Run missing checks" only appears
    when there are checks left to run."""
    results = {check: _measured() for check in ran}
    state = _state(model="CI runner", results=results, running=running, lock=True, offline=True)
    page.goto(f"{server.base_url}/en/device-check{_fragment(state)}")
    page.wait_for_selector("#device-check[data-ready=true]")
    assert not page.is_visible("#check-resume")
    assert page.text_content("#check-status") == _EN[expected].replace("{label}", _EN[label])


@pytest.mark.parametrize("path", ["/de/device-check", "/en/device-check"])
def test_the_page_loads_without_a_csp_violation(page: Page, server, path: str):
    page.add_init_script(
        "window.__violations = [];"
        "document.addEventListener('securitypolicyviolation', (e) =>"
        " window.__violations.push(`${e.effectiveDirective} ${e.blockedURI}`));"
    )
    page.goto(f"{server.base_url}{path}")
    page.wait_for_selector("#device-check[data-ready=true]")
    assert page.evaluate("window.__violations") == []
