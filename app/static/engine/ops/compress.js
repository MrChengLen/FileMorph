// SPDX-License-Identifier: AGPL-3.0-or-later
// Compressing a photo in the browser, end to end: read its header, plan the
// size (never above the canvas limit), decode it upright and scaled, check
// that something was drawn, encode it as JPEG — once at a set quality, or
// searching for a target size — and check the result's header. The result
// keeps no metadata: a canvas carries none, so location, device and capture
// time stay behind. Every step is timed. Runs in a window and in a worker
// (ops/worker.js).

import { HEAD_BYTES, imageInfo, jpegInfo } from "../core/sniff.js";
import { MAX_CANVAS_PIXELS, displaySize, fitPixels, searchQuality } from "../core/plan.js";
import { decode, draw, encode, isBlank, release } from "../raster/shrink.js";

const RESULT_HEAD = 1 << 16;

/** An error with a code the page translates, never a raw message. */
export class EngineError extends Error {
  constructor(code, detail = "") {
    super(detail ? `${code}: ${detail}` : code);
    this.code = code;
    this.detail = detail;
  }
}

/**
 * Compresses `file` (a Blob) to a JPEG. Options: `mode` "once" (encode at
 * `quality`) or "target" (the highest quality whose result fits
 * `targetBytes`, in a few encodes at most); `maxPixels`, the size cap.
 * Resolves to `{ input, planned, decoded, scaledBy, output, blank, timings,
 * blob }`; `timings` in milliseconds per step.
 */
export async function compress(
  file,
  { mode = "once", quality = 0.85, targetBytes = 2_000_000, maxPixels = MAX_CANVAS_PIXELS } = {},
) {
  const marks = [["start", performance.now()]];
  const mark = (name) => marks.push([name, performance.now()]);

  const input = imageInfo(new Uint8Array(await file.slice(0, HEAD_BYTES).arrayBuffer()));
  mark("header");
  if (!input.format) throw new EngineError("unsupported-format");

  // The planned size, when the header gave one: the decoder is asked to scale
  // to it. A browser that does not, or a header without a size, leaves the
  // scaling to the canvas.
  const shown = input.width ? displaySize(input.width, input.height, input.orientation) : null;
  const planned = shown ? fitPixels(shown.width, shown.height, maxPixels) : null;
  let bitmap;
  try {
    bitmap = await decode(file, planned && planned.scale < 1 ? planned : null);
  } catch (error) {
    throw new EngineError("decode-failed", (error && error.name) || "");
  }
  mark("decode");
  const decoded = { width: bitmap.width, height: bitmap.height };
  const size = fitPixels(decoded.width, decoded.height, maxPixels);
  // Who scaled: the decoder, the canvas (the decoder gave the full size), or nobody.
  const scaledBy = size.scale < 1 ? "canvas" : planned && planned.scale < 1 ? "decoder" : "none";

  let canvas;
  try {
    canvas = draw(bitmap, size);
  } finally {
    bitmap.close();
  }
  mark("draw");

  let blank;
  let blob;
  let passes = 1;
  let met = null;
  let used = quality;
  try {
    blank = isBlank(canvas);
    if (mode === "target") {
      // Only what can still be the answer is kept: the best fit, or the smallest miss.
      let fit = null;
      let miss = null;
      const found = await searchQuality(async (q) => {
        const candidate = await encode(canvas, q);
        if (candidate.size <= targetBytes) {
          if (!fit || q > fit.quality) fit = { quality: q, blob: candidate };
        } else if (!miss || candidate.size < miss.blob.size) {
          miss = { quality: q, blob: candidate };
        }
        return candidate.size;
      }, targetBytes);
      blob = found.met ? fit.blob : miss.blob;
      passes = found.passes;
      met = found.met;
      used = found.quality;
    } else {
      blob = await encode(canvas, quality);
    }
  } finally {
    release(canvas);
  }
  mark("encode");

  const result = jpegInfo(new Uint8Array(await blob.slice(0, RESULT_HEAD).arrayBuffer()));
  mark("verify");

  const timings = {};
  for (let i = 1; i < marks.length; i++) timings[marks[i][0]] = marks[i][1] - marks[i - 1][1];
  timings.total = marks[marks.length - 1][1] - marks[0][1];
  return {
    input,
    planned,
    decoded,
    scaledBy,
    output: {
      width: result ? result.width : null,
      height: result ? result.height : null,
      bytes: blob.size,
      quality: used,
      passes,
      met,
    },
    blank,
    timings,
    blob,
  };
}
