// SPDX-License-Identifier: AGPL-3.0-or-later
// What an image file says about itself in its first bytes: the format, the
// pixel size and the orientation — read before anything decodes it, so the
// engine knows what decoding will cost (a 48-megapixel photo needs about
// 190 MB as pixels) and can refuse or plan for it first. Pure functions on a
// Uint8Array; no browser API.

// Enough for the headers of a camera photo: the EXIF block of a JPEG sits
// within its first 64 KB, the metadata of a HEIC within its first few KB.
export const HEAD_BYTES = 1 << 20;

const ascii = (bytes, start, length) =>
  String.fromCharCode(...bytes.subarray(start, start + length));
const u16 = (bytes, at, little = false) =>
  little ? bytes[at] | (bytes[at + 1] << 8) : (bytes[at] << 8) | bytes[at + 1];
const u32 = (bytes, at, little = false) =>
  little
    ? (bytes[at] | (bytes[at + 1] << 8) | (bytes[at + 2] << 16) | (bytes[at + 3] << 24)) >>> 0
    : ((bytes[at] << 24) | (bytes[at + 1] << 16) | (bytes[at + 2] << 8) | bytes[at + 3]) >>> 0;

/** "jpeg", "png", "heic", "avif", "webp", "gif" — or null for anything else. */
export function format(bytes) {
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "jpeg";
  if (bytes.length >= 8 && u32(bytes, 0) === 0x89504e47 && u32(bytes, 4) === 0x0d0a1a0a) return "png";
  if (bytes.length >= 12 && ascii(bytes, 0, 4) === "RIFF" && ascii(bytes, 8, 4) === "WEBP") return "webp";
  if (bytes.length >= 6 && (ascii(bytes, 0, 6) === "GIF87a" || ascii(bytes, 0, 6) === "GIF89a")) return "gif";
  if (bytes.length >= 12 && ascii(bytes, 4, 4) === "ftyp") {
    const brands = [];
    const size = Math.min(u32(bytes, 0), bytes.length);
    for (let at = 8; at + 4 <= size; at += 4) {
      if (at !== 12) brands.push(ascii(bytes, at, 4)); // skip minor_version
    }
    if (brands.some((b) => b === "avif" || b === "avis")) return "avif";
    if (brands.some((b) => ["heic", "heix", "heim", "heis", "mif1", "msf1"].includes(b))) return "heic";
  }
  return null;
}

// The EXIF orientation (1–8) in a TIFF block starting at `start`, or 1.
function tiffOrientation(bytes, start, end) {
  if (start + 8 > end) return 1;
  const order = ascii(bytes, start, 2);
  if (order !== "II" && order !== "MM") return 1;
  const little = order === "II";
  const ifd = start + u32(bytes, start + 4, little);
  if (ifd + 2 > end) return 1;
  const entries = u16(bytes, ifd, little);
  for (let i = 0; i < entries; i++) {
    const at = ifd + 2 + i * 12;
    if (at + 12 > end) break;
    if (u16(bytes, at, little) === 0x0112) {
      const value = u16(bytes, at + 8, little);
      return value >= 1 && value <= 8 ? value : 1;
    }
  }
  return 1;
}

/**
 * A JPEG's size and orientation from its markers, up to the first scan:
 * `{ width, height, components, progressive, orientation, icc }`, or null if
 * the header is cut short or broken.
 */
export function jpegInfo(bytes) {
  let at = 2;
  let orientation = 1;
  let icc = false;
  while (at + 4 <= bytes.length) {
    if (bytes[at] !== 0xff) return null;
    const marker = bytes[at + 1];
    if (marker === 0xff) {
      at += 1; // fill byte
      continue;
    }
    if (marker === 0xd8 || (marker >= 0xd0 && marker <= 0xd7) || marker === 0x01) {
      at += 2;
      continue;
    }
    const length = u16(bytes, at + 2);
    const body = at + 4;
    const end = at + 2 + length;
    if (length < 2) return null;
    if (marker === 0xe1 && end <= bytes.length && ascii(bytes, body, 6) === "Exif\0\0") {
      orientation = tiffOrientation(bytes, body + 6, end);
    } else if (marker === 0xe2 && end <= bytes.length && ascii(bytes, body, 12) === "ICC_PROFILE\0") {
      icc = true;
    } else if (
      marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc
    ) {
      if (body + 6 > bytes.length) return null;
      return {
        width: u16(bytes, body + 3),
        height: u16(bytes, body + 1),
        components: bytes[body + 5],
        progressive: marker === 0xc2 || marker === 0xc6 || marker === 0xca || marker === 0xce,
        orientation,
        icc,
      };
    } else if (marker === 0xda || marker === 0xd9) {
      return null; // a scan or the end before any frame header
    }
    at = end;
  }
  return null;
}

/** A PNG's `{ width, height }` from its IHDR chunk, or null. */
export function pngInfo(bytes) {
  if (bytes.length < 24 || ascii(bytes, 12, 4) !== "IHDR") return null;
  return { width: u32(bytes, 16), height: u32(bytes, 20), orientation: 1 };
}

// ISOBMFF boxes in bytes[start, end): yields [type, bodyStart, boxEnd].
function* boxes(bytes, start, end) {
  let at = start;
  while (at + 8 <= end) {
    let size = u32(bytes, at);
    let header = 8;
    if (size === 1) {
      if (at + 16 > end) return;
      size = u32(bytes, at + 8) * 2 ** 32 + u32(bytes, at + 12);
      header = 16;
    } else if (size === 0) {
      size = end - at;
    }
    if (size < header || at + size > end) return;
    yield [ascii(bytes, at + 4, 4), at + header, at + size];
    at += size;
  }
}

/**
 * A HEIC or AVIF image's `{ width, height, orientation }` from the largest
 * `ispe` (image spatial extent) property in its `meta` box, which is the
 * primary image's or its grid's, and the rotation of an `irot` box. Null if
 * the metadata is not within `bytes`.
 */
export function heifInfo(bytes) {
  for (const [type, body, end] of boxes(bytes, 0, bytes.length)) {
    if (type !== "meta") continue;
    let best = null;
    let rotation = 0;
    for (const [inner, innerBody, innerEnd] of boxes(bytes, body + 4, end)) {
      if (inner !== "iprp") continue;
      for (const [prop, propBody, propEnd] of boxes(bytes, innerBody, innerEnd)) {
        if (prop !== "ipco") continue;
        for (const [item, itemBody] of boxes(bytes, propBody, propEnd)) {
          if (item === "ispe") {
            const width = u32(bytes, itemBody + 4);
            const height = u32(bytes, itemBody + 8);
            if (!best || width * height > best.width * best.height) best = { width, height };
          } else if (item === "irot") {
            rotation = (bytes[itemBody] & 0x3) * 90;
          }
        }
      }
    }
    if (!best) return null;
    // irot turns anti-clockwise; as EXIF orientations: 90° → 8, 180° → 3, 270° → 6.
    const orientation = { 0: 1, 90: 8, 180: 3, 270: 6 }[rotation];
    return { ...best, orientation };
  }
  return null;
}

/**
 * Everything the header of `bytes` tells: `{ format, width, height,
 * orientation, … }`; `width`/`height` are null when the format is known but
 * its size is not in these bytes.
 */
export function imageInfo(bytes) {
  const kind = format(bytes);
  const info =
    kind === "jpeg" ? jpegInfo(bytes) : kind === "png" ? pngInfo(bytes) : kind === "heic" || kind === "avif" ? heifInfo(bytes) : null;
  return { format: kind, width: null, height: null, orientation: 1, ...info };
}

/** True if EXIF orientation `orientation` swaps width and height. */
export const swapsSides = (orientation) => orientation >= 5 && orientation <= 8;
