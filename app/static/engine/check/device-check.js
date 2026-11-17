// SPDX-License-Identifier: AGPL-3.0-or-later
// The device check (/device-check, app/templates/device_check.html): does
// this phone compress a large photo in the browser fast enough, without the
// page crashing? It makes its own test photos (check/sample.js), runs the
// engine's compression on them (ops/compress.js) and shows each check with
// its numbers; "Copy result" gives the whole record as text.
//
// The page sends nothing: its CSP refuses every connection, and no file here
// but the lock's self-test (check/upload-lock.js) has network code
// (tests/test_engine_code.py). Its state lives in the address after "#",
// the part a browser never sends, so that a reload after a crash still knows
// what ran, without cookies or local storage.

import { DELIVERY } from "../delivery.js";
import { HEAD_BYTES, imageInfo } from "../core/sniff.js";
import { MAX_CANVAS_PIXELS, displaySize, fitPixels } from "../core/plan.js";
import { compress } from "../ops/compress.js";
import { decode, draw, release } from "../raster/shrink.js";
import { testPhoto } from "./sample.js";
import { uploadLockActive } from "./upload-lock.js";

const PROTOCOL = 1;
const LIMIT_MS = 6000;
const TARGET_BYTES = 2_000_000;
// From this size on, a photo of the user's counts as a 24-megapixel one.
const GATE_PIXELS = 22_800_000;
const PHOTOS = { 24: [6000, 4000], 48: [8000, 6000] };

// The checks, in the order they run; "gate" ones decide the verdict, and of
// those only the 48-megapixel one has no time limit (it tests memory).
const CHECKS = [
  { id: "24-1", photo: 24, mode: "target", gate: true, label: ["label24", { n: 1 }] },
  { id: "24-2", photo: 24, mode: "target", gate: true, label: ["label24", { n: 2 }] },
  { id: "24-3", photo: 24, mode: "target", gate: true, label: ["label24", { n: 3 }] },
  { id: "24-once", photo: 24, mode: "once", label: ["label24Once", {}] },
  { id: "24-worker", photo: 24, mode: "target", worker: true, label: ["label24Worker", {}] },
  { id: "48", photo: 48, mode: "once", gate: true, memory: true, label: ["label48", {}] },
];
const BUTTONS = ["check-prepare", "check-start", "check-resume", "check-own", "check-camera", "check-copy"];

const root = document.getElementById("device-check");
const T = JSON.parse(document.getElementById("fm-check-strings").textContent);
const $ = (id) => document.getElementById(id);
const say = (key, values = {}) => T[key].replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? ""));
const decimal = (value) => value.toFixed(1).replace(".", T.decimalPoint);
const labelOf = (check) => say(...check.label);

// ── State, kept in the address fragment ─────────────────────────────────────

const toBase64Url = (text) => {
  let binary = "";
  for (const byte of new TextEncoder().encode(text)) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};
const fromBase64Url = (text) =>
  new TextDecoder().decode(
    Uint8Array.from(atob(text.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0)),
  );

// The model as typed, at most 80 characters, without control, format or
// separator characters: a line break of any kind would make a line of its
// own in the copied record, a direction mark would reorder what it shows.
// Cut before trimmed, so that a cleaned model stays as it is.
const cleanModel = (value) =>
  [...String(value).replace(/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/gu, "")].slice(0, 80).join("").trim();

// A state from the address is taken only if it is one this page could have
// written: anyone can send a link with "#s=…", and the page shows and copies
// what the state says. Anything else, and the page starts afresh. What the
// page writes, every check and the photos of one's own it keeps (EXTRA_MAX),
// takes about 7 KB: far below STATE_MAX, or it would refuse its own state.
const STATE_MAX = 16_384;
const EXTRA_MAX = 10;
const STATUSES = new Set(["passed", "slow", "wrong", "failed", "crashed", "invalid", "measured"]);
const MEASURED = new Set(["passed", "slow", "wrong", "measured"]);
// A record's code: the engine's own (decode-failed, worker-timeout…), with
// the cause it knows of, or the name of a browser error.
const CODE = /^[A-Za-z][\w-]{0,39}$/;
const PROBLEMS = new Set(["size", "orientation", "blank", "target"]);
const PARTS = {
  input: ["format", "width", "height", "orientation"],
  decoded: ["width", "height"],
  output: ["width", "height", "bytes", "quality", "passes"],
  ms: ["header", "decode", "draw", "encode", "verify", "total"],
};
const isObject = (value) => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const onlyKeys = (value, keys) => Object.keys(value).every((key) => keys.includes(key));
const isNumber = (value) => value === null || (Number.isFinite(value) && value >= 0 && value <= 1e10);

function validRecord(record, extra) {
  if (!isObject(record)) return false;
  if (!onlyKeys(record, ["status", "problems", "scaledBy", "invalid", "code", "kind", ...Object.keys(PARTS)])) {
    return false;
  }
  if (!STATUSES.has(record.status)) return false;
  if (extra ? !["own", "camera"].includes(record.kind) : "kind" in record) return false;
  if ("code" in record && !(typeof record.code === "string" && CODE.test(record.code))) return false;
  // What the page wrote for a status must be there, or the page could not
  // show it: a measured record has its input, output and times, a failed
  // one its code. (A result whose header gave no size has none: null.)
  const timed =
    isObject(record.ms) &&
    Number.isFinite(record.ms.total) &&
    isObject(record.output) &&
    Number.isFinite(record.output.bytes);
  const complete = timed && isObject(record.input) && isObject(record.decoded) && Array.isArray(record.problems);
  if ("ms" in record && !timed) return false;
  if (MEASURED.has(record.status) && !complete) return false;
  if (record.status === "failed" && !("code" in record)) return false;
  if ("invalid" in record && record.invalid !== true) return false;
  if ("scaledBy" in record && !["decoder", "canvas", "none"].includes(record.scaledBy)) return false;
  if ("problems" in record && !(Array.isArray(record.problems) && record.problems.every((p) => PROBLEMS.has(p)))) {
    return false;
  }
  return Object.entries(PARTS).every(([part, keys]) => {
    if (!(part in record)) return true;
    const value = record[part];
    if (!isObject(value) || !onlyKeys(value, keys)) return false;
    return Object.entries(value).every(([key, item]) =>
      key === "format" ? item === null || (typeof item === "string" && /^[a-z]{3,4}$/.test(item)) : isNumber(item),
    );
  });
}

function validState(saved) {
  return (
    isObject(saved) &&
    onlyKeys(saved, ["v", "model", "results", "extra", "running", "lock", "offline"]) &&
    saved.v === PROTOCOL &&
    typeof saved.model === "string" &&
    saved.model === cleanModel(saved.model) &&
    isObject(saved.results) &&
    Object.entries(saved.results).every(
      ([id, record]) => CHECKS.some((check) => check.id === id) && validRecord(record, false),
    ) &&
    Array.isArray(saved.extra) &&
    saved.extra.length <= EXTRA_MAX &&
    saved.extra.every((record) => validRecord(record, true)) &&
    (saved.running === null ||
      CHECKS.some((check) => check.id === saved.running) ||
      ["extra-own", "extra-camera"].includes(saved.running)) &&
    [true, false, null].includes(saved.lock) &&
    [true, false, null].includes(saved.offline)
  );
}

function loadState() {
  const match = /^#s=([A-Za-z0-9_-]+)$/.exec(window.location.hash);
  if (match && match[1].length <= STATE_MAX) {
    try {
      const saved = JSON.parse(fromBase64Url(match[1]));
      if (validState(saved)) return saved;
    } catch {
      // A damaged fragment: start afresh.
    }
  }
  return { v: PROTOCOL, model: "", results: {}, extra: [], running: null, lock: null, offline: null };
}

const state = loadState();
const saveState = () => history.replaceState(null, "", `#s=${toBase64Url(JSON.stringify(state))}`);
// Of the photos of one's own, the page keeps the last EXTRA_MAX.
function addExtra(record) {
  state.extra = [...state.extra, record].slice(-EXTRA_MAX);
}

// A reload while something ran means the browser threw the page away: a
// crash of that check. It is recorded, and nothing restarts on its own.
let crashedOnLoad = state.running;
if (crashedOnLoad) {
  if (crashedOnLoad.startsWith("extra-")) {
    addExtra({ kind: crashedOnLoad.slice(6), status: "crashed" });
  } else {
    state.results[crashedOnLoad] = { status: "crashed" };
  }
  state.running = null;
  saveState();
}

// ── What the browser and the device are ────────────────────────────────────

function browserName(ua) {
  for (const [name, pattern] of [
    ["Edge", /EdgA?\/(\d+)/],
    ["Chrome", /(?:CriOS|Chrome)\/(\d+)/],
    ["Firefox", /(?:FxiOS|Firefox)\/(\d+)/],
    ["Safari", /Version\/(\d+(?:\.\d+)?)[^)]*Safari/],
  ]) {
    const match = pattern.exec(ua);
    if (match) return `${name} ${match[1]}`;
  }
  return "?";
}

function systemName(ua) {
  if (/iPhone|iPad|iPod/.test(ua)) return "iOS";
  const android = /Android (\d+(?:\.\d+)?)/.exec(ua);
  if (android) return `Android ${android[1]}`;
  if (/Mac OS X/.test(ua)) return "macOS";
  if (/Windows/.test(ua)) return "Windows";
  if (/Linux/.test(ua)) return "Linux";
  return "?";
}

async function deviceInfo() {
  const ua = navigator.userAgent;
  const info = {
    browser: browserName(ua),
    system: systemName(ua),
    userAgent: ua,
    model: null,
    cores: navigator.hardwareConcurrency || null,
    memoryGb: navigator.deviceMemory || null,
    screen: `${window.screen.width}x${window.screen.height}@${window.devicePixelRatio}`,
    offscreenCanvas: typeof OffscreenCanvas === "function",
    imageBitmap: typeof createImageBitmap === "function",
    worker: typeof Worker === "function",
  };
  if (navigator.userAgentData && navigator.userAgentData.getHighEntropyValues) {
    try {
      const values = await navigator.userAgentData.getHighEntropyValues(["model", "platformVersion"]);
      info.model = values.model || null;
      if (values.platform === "Android" && values.platformVersion) {
        info.system = `Android ${values.platformVersion}`;
      }
    } catch {
      // Not offered: the user agent string has to do.
    }
  }
  return info;
}

// ── Running a check ─────────────────────────────────────────────────────────

const photos = {};
let device = null;
let busy = false;
let hiddenDuringRun = false;
let warmWorker = null;

async function photo(megapixels) {
  if (!photos[megapixels]) {
    const [width, height] = PHOTOS[megapixels];
    const chunks = await testPhoto({
      width,
      height,
      onProgress: (done) => status("statusPreparing", { percent: Math.round(done * 100) }),
    });
    photos[megapixels] = new Blob(chunks, { type: "image/jpeg" });
  }
  return photos[megapixels];
}

const newWorker = () => new Worker(new URL("../ops/worker.js", import.meta.url), { type: "module" });

// A run that never ends would hold the page busy for good: after this long
// it counts as failed.
const RUN_LIMIT_MS = 120_000;

function withinLimit(promise) {
  let timer;
  const limit = new Promise((_, reject) => {
    timer = setTimeout(() => reject(Object.assign(new Error("timeout"), { code: "timeout" })), RUN_LIMIT_MS);
  });
  return Promise.race([promise, limit]).finally(() => clearTimeout(timer));
}

// One job per worker, which then ends and hands its memory back. The first
// one was started by "Prepare test", while the phone was still online, so its
// modules are loaded even in airplane mode.
function inWorker(file, options) {
  return new Promise((resolve, reject) => {
    const worker = warmWorker || newWorker();
    warmWorker = null;
    const timer = setTimeout(() => fail("worker-timeout"), RUN_LIMIT_MS);
    function fail(code, detail = "") {
      clearTimeout(timer);
      worker.terminate();
      reject(Object.assign(new Error(code), { code, detail }));
    }
    worker.onmessage = (event) => {
      if (!event.data.ok) return fail(event.data.code, event.data.detail);
      clearTimeout(timer);
      worker.terminate();
      resolve(event.data.result);
    };
    worker.onerror = () => fail("worker-failed");
    worker.postMessage({ file, options });
  });
}

// Whether a result is what the engine had to make: the planned size (a turned
// photo comes out with its sides swapped), something drawn, and the target
// size met when one was set. That a test photo came out upright, not just
// at the right size, markerAtTopRight checks.
function problemsOf(result, mode) {
  const { input, output } = result;
  // A header without a size (WebP, GIF, some HEIC): the decoded picture is
  // already upright, so its size is the one shown.
  const shown = input.width ? displaySize(input.width, input.height, input.orientation) : result.decoded;
  const planned = fitPixels(shown.width, shown.height, MAX_CANVAS_PIXELS);
  const problems = [];
  if (output.width !== planned.width || output.height !== planned.height) problems.push("size");
  if (result.blank) problems.push("blank");
  if (mode === "target" && !output.met) problems.push("target");
  return problems;
}

// What the record keeps of a result: sizes and times, never a picture.
function recordOf(result, problems) {
  const { input, output } = result;
  return {
    problems,
    input: { format: input.format, width: input.width, height: input.height, orientation: input.orientation },
    decoded: result.decoded,
    scaledBy: result.scaledBy,
    output: {
      width: output.width,
      height: output.height,
      bytes: output.bytes,
      quality: output.quality,
      passes: output.passes,
    },
    ms: Object.fromEntries(Object.entries(result.timings).map(([step, ms]) => [step, Math.round(ms)])),
  };
}

// The test photos carry a marker, a red corner, at the top left as stored
// (check/sample.js); turned by their EXIF orientation 6, it must come out at
// the top right. A browser that scaled a photo without turning it would give
// one of the planned size, stretched, with the marker still at the top left.
async function markerAtTopRight(blob) {
  const size = { width: 12, height: 12 };
  const bitmap = await decode(blob, size);
  let canvas;
  try {
    canvas = draw(bitmap, size);
  } finally {
    bitmap.close();
  }
  try {
    const context = canvas.getContext("2d", { alpha: false });
    const red = (x, y) => {
      const [r, g, b] = context.getImageData(x, y, 1, 1).data;
      return r > 170 && g < 60 && b < 80;
    };
    return red(11, 0) && !red(0, 0);
  } finally {
    release(canvas);
  }
}

// A record's code: the engine's own, with the cause it knows of
// ("decode-failed-EncodingError"), or the name of a browser error — not a
// DOMException's numeric legacy code.
function codeOf(error) {
  const code = typeof error?.code === "string" ? error.code : error?.name;
  const full = error?.detail ? `${code}-${error.detail}` : code;
  return [full, code].find((item) => typeof item === "string" && CODE.test(item)) || "error";
}

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function measure(running, file, options, { worker = false, marker = false } = {}) {
  state.running = running;
  saveState();
  hiddenDuringRun = false;
  // Let the page paint and settle before the clock starts.
  await pause(50);
  // A check that starts with the page in the background counts no more than
  // one sent there while it ran: no visibilitychange tells of it.
  if (document.hidden) hiddenDuringRun = true;
  let record;
  try {
    const result = worker ? await inWorker(file, options) : await withinLimit(compress(file, options));
    const problems = problemsOf(result, options.mode);
    if (marker && !(await markerAtTopRight(result.blob))) problems.push("orientation");
    record = recordOf(result, problems);
    showPreview(result.blob);
  } catch (error) {
    record = { problems: [], code: codeOf(error) };
  }
  if (hiddenDuringRun || document.hidden) record.invalid = true;
  state.running = null;
  return record;
}

async function runCheck(check) {
  const file = await photo(check.photo);
  const record = await measure(
    check.id,
    file,
    { mode: check.mode, targetBytes: TARGET_BYTES },
    { worker: check.worker, marker: true },
  );
  record.status = record.invalid
    ? "invalid"
    : record.code
      ? "failed"
      : record.problems.length
        ? "wrong"
        : check.memory || record.ms.total < LIMIT_MS
          ? "passed"
          : "slow";
  state.results[check.id] = record;
  saveState();
  render();
}

// ── The verdict ─────────────────────────────────────────────────────────────

function verdict() {
  const gate = CHECKS.filter((check) => check.gate);
  for (const check of gate) {
    const result = state.results[check.id] || {};
    if (result.status === "crashed") return ["verdictFail", { reason: say("reasonCrash", { label: labelOf(check) }) }];
    if (result.status === "wrong" || result.status === "failed") {
      return ["verdictFail", { reason: say("reasonWrong", { label: labelOf(check) }) }];
    }
    if (result.status === "slow") {
      const seconds = decimal(result.ms.total / 1000);
      return ["verdictFail", { reason: say("reasonSlow", { label: labelOf(check), seconds }) }];
    }
  }
  const missing = gate.filter((check) => (state.results[check.id] || {}).status !== "passed").length;
  return missing ? ["verdictOpen", { count: missing }] : ["verdictPass", {}];
}

// ── The page ────────────────────────────────────────────────────────────────

function status(key, values) {
  $("check-status").textContent = say(key, values);
}

function numbers(record, withLimit) {
  if (record.code) return say("numbersFailed", { code: record.code });
  if (!record.ms) return "";
  const values = {
    seconds: decimal(record.ms.total / 1000),
    pixels: decimal((record.output.width * record.output.height) / 1e6),
    size: decimal(record.output.bytes / 1e6),
  };
  return say(withLimit ? "numbersLimit" : "numbers", values);
}

function row(text, stateKey, detail) {
  const item = $("check-row").content.firstElementChild.cloneNode(true);
  item.querySelector("[data-part=label]").textContent = text;
  item.querySelector("[data-part=state]").textContent = stateKey ? T[`state_${stateKey}`] : "";
  item.querySelector("[data-part=numbers]").textContent = detail;
  if (stateKey) item.dataset.state = stateKey;
  return item;
}

function render() {
  const list = $("check-results");
  list.replaceChildren();
  for (const check of CHECKS) {
    const record = state.results[check.id];
    list.append(
      row(labelOf(check), record && record.status, record ? numbers(record, check.gate && !check.memory) : ""),
    );
  }
  for (const record of state.extra) {
    // A header without a size (WebP, GIF, some HEIC): the decoded picture's.
    const size = record.input && record.input.width ? record.input : record.decoded;
    const pixels = size && size.width ? size.width * size.height : null;
    const note = pixels && pixels < GATE_PIXELS ? ` ${say("notCounted", { mp: decimal(pixels / 1e6) })}` : "";
    list.append(row(say(record.kind === "camera" ? "labelCamera" : "labelOwn"), record.status, numbers(record) + note));
  }
  const [key, values] = verdict();
  $("check-verdict").textContent = say(key, values);
  if (state.lock !== null) $("check-lock").textContent = say(state.lock ? "lockOn" : "lockOff");
  // The "hidden" class, not the attribute: a display class on the element
  // would override the attribute.
  $("check-resume").classList.toggle("hidden", !canResume());
}

// Whether "Run missing checks" has something to run, after a start: a check
// not run yet, or one that ran in the background.
function canResume() {
  const started = Object.keys(state.results).length > 0;
  return started && CHECKS.some((check) => !state.results[check.id] || state.results[check.id].status === "invalid");
}

function showPreview(blob) {
  const preview = $("check-preview");
  if (preview.dataset.url) URL.revokeObjectURL(preview.dataset.url);
  preview.src = URL.createObjectURL(blob);
  preview.dataset.url = preview.src;
  preview.classList.remove("hidden");
}

function report() {
  const [key, values] = verdict();
  const lines = [
    `FileMorph device check, protocol ${PROTOCOL}`,
    `engine: ${root.dataset.engine.split("/").pop()} delivery: ${DELIVERY}`,
    `date: ${new Date().toISOString()}`,
    `model (entered): ${state.model || "-"}`,
    `model (browser): ${device.model || "-"}`,
    `browser: ${device.browser} on ${device.system}`,
    `user agent: ${device.userAgent}`,
    `cores: ${device.cores ?? "-"}, memory (GB, Chromium only): ${device.memoryGb ?? "-"}, screen: ${device.screen}`,
    `offscreen canvas: ${device.offscreenCanvas}, createImageBitmap: ${device.imageBitmap}, worker: ${device.worker}`,
    `upload lock: ${state.lock === null ? "not checked" : state.lock ? "on" : "OFF"}`,
    `offline during the run: ${state.offline === null ? "-" : state.offline}`,
    `verdict: ${say(key, values)}`,
  ];
  for (const check of CHECKS) {
    const record = state.results[check.id];
    const how = `${check.mode}${check.worker ? ", worker" : ""}`;
    lines.push(`check ${check.id} (${how}): ${record ? JSON.stringify(record) : "not run"}`);
  }
  for (const record of state.extra) lines.push(`${record.kind}: ${JSON.stringify(record)}`);
  if (crashedOnLoad) lines.push(`reloaded during: ${crashedOnLoad}`);
  lines.push("end");
  return lines.join("\n");
}

async function copyReport() {
  const text = report();
  try {
    await navigator.clipboard.writeText(text);
    status("statusCopied");
  } catch {
    const area = $("check-report");
    area.value = text;
    area.classList.remove("hidden");
    area.select();
    status("statusCopyFailed");
  }
}

// ── Actions ─────────────────────────────────────────────────────────────────

async function withBusy(action) {
  if (busy) return;
  busy = true;
  root.dataset.busy = "true";
  for (const id of BUTTONS) $(id).disabled = true;
  let wake = null;
  try {
    if (navigator.wakeLock) wake = await navigator.wakeLock.request("screen").catch(() => null);
    await action();
  } finally {
    if (wake) wake.release().catch(() => {});
    busy = false;
    delete root.dataset.busy;
    for (const id of BUTTONS) $(id).disabled = false;
  }
}

async function prepare() {
  await withBusy(async () => {
    for (const megapixels of Object.keys(PHOTOS)) await photo(megapixels);
    if (!warmWorker && typeof Worker === "function") warmWorker = newWorker();
    // A refused request reports no CSP violation while the phone is offline.
    if (navigator.onLine) {
      state.lock = await uploadLockActive();
      saveState();
    }
    render();
    status(navigator.onLine ? "statusOnline" : "statusReady");
  });
}

async function start(onlyMissing) {
  state.model = cleanModel($("check-model").value);
  if (!state.model) {
    status("statusModel");
    $("check-model").focus();
    return;
  }
  await withBusy(async () => {
    state.offline = !navigator.onLine;
    // A new run starts empty, so that neither a record nor the note of a
    // crash mixes two runs.
    if (!onlyMissing) {
      state.results = {};
      crashedOnLoad = null;
      saveState();
      render();
    }
    for (const megapixels of Object.keys(PHOTOS)) await photo(megapixels);
    const todo = CHECKS.filter((check) => {
      const record = state.results[check.id];
      return !onlyMissing || !record || record.status === "invalid";
    });
    for (let i = 0; i < todo.length; i++) {
      status("statusRunning", { n: i + 1, total: todo.length });
      await runCheck(todo[i]);
    }
    status("statusDone");
  });
}

async function ownPhoto(input, kind) {
  const file = input.files && input.files[0];
  input.value = "";
  if (!file) return;
  await withBusy(async () => {
    const info = imageInfo(new Uint8Array(await file.slice(0, HEAD_BYTES).arrayBuffer()));
    if (!info.format) {
      status("statusNotAPhoto");
      return;
    }
    const record = await measure(`extra-${kind}`, file, { mode: "target", targetBytes: TARGET_BYTES });
    record.kind = kind;
    record.status = record.invalid ? "invalid" : record.code ? "failed" : record.problems.length ? "wrong" : "measured";
    if (!record.input) record.input = { format: info.format, width: info.width, height: info.height };
    addExtra(record);
    saveState();
    render();
    status("statusDone");
  });
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden && state.running) hiddenDuringRun = true;
});

$("check-prepare").addEventListener("click", prepare);
$("check-start").addEventListener("click", () => start(false));
$("check-resume").addEventListener("click", () => start(true));
// The file fields stay hidden; their buttons open them.
$("check-own").addEventListener("click", () => $("check-own-input").click());
$("check-camera").addEventListener("click", () => $("check-camera-input").click());
$("check-own-input").addEventListener("change", (event) => ownPhoto(event.target, "own"));
$("check-camera-input").addEventListener("change", (event) => ownPhoto(event.target, "camera"));
$("check-copy").addEventListener("click", copyReport);
$("check-model").value = state.model;

device = await deviceInfo();
let detected = say("detected", { browser: device.browser, system: device.system, cores: device.cores ?? "?" });
if (!device.offscreenCanvas || !device.imageBitmap) {
  detected += ` ${say("unsupported", { feature: device.offscreenCanvas ? "createImageBitmap" : "OffscreenCanvas" })}`;
}
$("check-device").textContent = detected;
render();
if (crashedOnLoad) {
  const check = CHECKS.find((item) => item.id === crashedOnLoad);
  const label = check ? labelOf(check) : say(crashedOnLoad === "extra-camera" ? "labelCamera" : "labelOwn");
  // "Run missing checks" only where it has something to run; after a whole
  // run, the crash completes the result; before one, the test is still to do.
  const started = Object.keys(state.results).length > 0;
  status(canResume() ? "statusCrashed" : started ? "statusCrashedDone" : "statusIdle", { label });
} else {
  status("statusIdle");
}
for (const id of BUTTONS) $(id).disabled = false;
root.dataset.ready = "true";

// For tests/browser/test_device_check.py: the record as "Copy result" gives it.
window.fmDeviceCheck = { report };
