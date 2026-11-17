// SPDX-License-Identifier: AGPL-3.0-or-later
// The browser side of shrinking a photo: the browser's own decoder reads the
// file (JPEG, PNG and WebP everywhere, HEIC in Safari), turns it as its EXIF
// orientation says and, where the browser can, scales it while decoding; the
// picture is drawn on a canvas, scaled there if the decoder did not, and
// encoded as JPEG. Runs in a window and in a worker.

/** Whether this browser can make a canvas without a page, as a worker needs. */
export const offscreen = typeof OffscreenCanvas === "function";

/**
 * The picture in `blob`, upright, asked for at `size` (`{ width, height }`,
 * the size after turning) when given. Resolves to an ImageBitmap — at that
 * size if the browser scales while decoding, at full size if it does not.
 */
export function decode(blob, size) {
  const options = { imageOrientation: "from-image" };
  if (size) {
    options.resizeWidth = size.width;
    options.resizeHeight = size.height;
    options.resizeQuality = "high";
  }
  return createImageBitmap(blob, options);
}

function canvasOf(width, height) {
  if (offscreen) return new OffscreenCanvas(width, height);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

/** `bitmap` drawn on a canvas of `size`, without an alpha channel. */
export function draw(bitmap, size) {
  const canvas = canvasOf(size.width, size.height);
  const context = canvas.getContext("2d", { alpha: false });
  context.imageSmoothingQuality = "high";
  context.drawImage(bitmap, 0, 0, size.width, size.height);
  return canvas;
}

/**
 * True if nothing was drawn: Safari leaves a canvas it cannot hold empty
 * without an error. Nine points of a photo are never all pure black.
 */
export function isBlank(canvas) {
  const context = canvas.getContext("2d", { alpha: false });
  for (const fy of [0.25, 0.5, 0.75]) {
    for (const fx of [0.25, 0.5, 0.75]) {
      const x = Math.min(canvas.width - 1, Math.floor(canvas.width * fx));
      const y = Math.min(canvas.height - 1, Math.floor(canvas.height * fy));
      const [r, g, b] = context.getImageData(x, y, 1, 1).data;
      if (r || g || b) return false;
    }
  }
  return true;
}

/** The canvas as a JPEG Blob at `quality` (0–1). */
export function encode(canvas, quality) {
  if (offscreen && canvas instanceof OffscreenCanvas) {
    return canvas.convertToBlob({ type: "image/jpeg", quality });
  }
  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error("toBlob gave nothing"))),
      "image/jpeg",
      quality,
    ),
  );
}

/** Gives a canvas's memory back at once instead of at the next collection. */
export function release(canvas) {
  canvas.width = 0;
  canvas.height = 0;
}
