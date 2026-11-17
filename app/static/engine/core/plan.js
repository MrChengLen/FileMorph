// SPDX-License-Identifier: AGPL-3.0-or-later
// How large the browser may make a picture, and how the engine searches for
// a JPEG quality that meets a target size. Pure functions; no browser API.

// Safari on the iPhone draws nothing on a canvas above 16,777,216 pixels
// (4096 × 4096) — no error, just an empty picture. Every canvas the engine
// makes stays at or below it, in every browser, so that a result never
// depends on which one ran.
export const MAX_CANVAS_PIXELS = 16_777_216;

// The most JPEG encodes a target-size search may take.
export const MAX_PASSES = 7;

/**
 * The largest size within `maxPixels` with the aspect ratio of `width` ×
 * `height`: `{ width, height, scale }`, `scale` = 1 when it fits already.
 */
export function fitPixels(width, height, maxPixels = MAX_CANVAS_PIXELS) {
  if (!(width > 0 && height > 0)) throw new RangeError("a size needs a positive width and height");
  if (width * height <= maxPixels) return { width, height, scale: 1 };
  let scale = Math.sqrt(maxPixels / (width * height));
  let w = Math.max(1, Math.floor(width * scale));
  let h = Math.max(1, Math.floor(height * scale));
  // A side that rounds up to 1 pixel can leave the other one too long.
  if (w * h > maxPixels) {
    if (w >= h) w = Math.max(1, Math.floor(maxPixels / h));
    else h = Math.max(1, Math.floor(maxPixels / w));
  }
  scale = Math.min(w / width, h / height);
  return { width: w, height: h, scale };
}

/** `width` × `height` as the picture shows after EXIF orientation 5–8 turned it. */
export function displaySize(width, height, orientation) {
  return orientation >= 5 && orientation <= 8 ? { width: height, height: width } : { width, height };
}

/**
 * The quality search for a target size: a bisection over JPEG qualities
 * `low`…`high` (0–1) with at most `passes` encodes. `encode(quality)` returns
 * the size in bytes. Resolves to `{ quality, bytes, passes, met }` — the
 * highest quality tried whose result fits, or the smallest result when none
 * does (`met` false).
 */
export async function searchQuality(encode, targetBytes, { low = 0.3, high = 0.95, passes = MAX_PASSES } = {}) {
  let best = null;
  let smallest = null;
  let used = 0;
  // Try the top first: a photo that fits at high quality needs one pass.
  let lo = low;
  let hi = high;
  let quality = high;
  while (used < passes) {
    const bytes = await encode(quality);
    used += 1;
    if (!smallest || bytes < smallest.bytes) smallest = { quality, bytes };
    if (bytes <= targetBytes) {
      if (!best || quality > best.quality) best = { quality, bytes };
      if (quality === high) break;
      lo = quality;
    } else {
      hi = quality;
    }
    if (hi - lo < 0.02) break;
    quality = Math.round(((lo + hi) / 2) * 100) / 100;
    if (best && quality <= best.quality) break;
  }
  const chosen = best || smallest;
  return { quality: chosen.quality, bytes: chosen.bytes, passes: used, met: Boolean(best) };
}
