// SPDX-License-Identifier: AGPL-3.0-or-later AND IJG
// Test photos for the device check (check/device-check.js), made in the
// browser: a baseline JPEG encoder that writes the image strip by strip, so a
// 24- or 48-megapixel photo never needs a canvas (Safari on the iPhone draws
// nothing on one above 16.7 MP) and never needs a download (the page's CSP
// refuses every connection).
//
// The content imitates a photo where it costs: smooth colour areas with fine
// grain and edges, so the file is about as large and as slow to decode as a
// camera's, 4:2:0 chroma like a camera's, and an EXIF orientation of 6
// (rotate 90° clockwise), as a portrait photo from a phone carries. A red
// corner marks the top left as stored, so that the device check can see a
// result come out turned.

// The JPEG standard's example tables (ITU-T T.81, Annex K).
const LUMA_QT = [
  16, 11, 10, 16, 24, 40, 51, 61, 12, 12, 14, 19, 26, 58, 60, 55, 14, 13, 16, 24, 40, 57, 69, 56,
  14, 17, 22, 29, 51, 87, 80, 62, 18, 22, 37, 56, 68, 109, 103, 77, 24, 35, 55, 64, 81, 104, 113,
  92, 49, 64, 78, 87, 103, 121, 120, 101, 72, 92, 95, 98, 112, 100, 103, 99,
];
const CHROMA_QT = [
  17, 18, 24, 47, 99, 99, 99, 99, 18, 21, 26, 66, 99, 99, 99, 99, 24, 26, 56, 99, 99, 99, 99, 99,
  47, 66, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99,
  99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99, 99,
];
const ZIGZAG = [
  0, 1, 8, 16, 9, 2, 3, 10, 17, 24, 32, 25, 18, 11, 4, 5, 12, 19, 26, 33, 40, 48, 41, 34, 27, 20,
  13, 6, 7, 14, 21, 28, 35, 42, 49, 56, 57, 50, 43, 36, 29, 22, 15, 23, 30, 37, 44, 51, 58, 59, 52,
  45, 38, 31, 39, 46, 53, 60, 61, 54, 47, 55, 62, 63,
];
const DC_LUMA_BITS = [0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0];
const DC_LUMA_VALS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
const DC_CHROMA_BITS = [0, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0];
const DC_CHROMA_VALS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
const AC_LUMA_BITS = [0, 2, 1, 3, 3, 2, 4, 3, 5, 5, 4, 4, 0, 0, 1, 0x7d];
const AC_LUMA_VALS = [
  0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06, 0x13, 0x51, 0x61, 0x07,
  0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xa1, 0x08, 0x23, 0x42, 0xb1, 0xc1, 0x15, 0x52, 0xd1, 0xf0,
  0x24, 0x33, 0x62, 0x72, 0x82, 0x09, 0x0a, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x25, 0x26, 0x27, 0x28,
  0x29, 0x2a, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49,
  0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69,
  0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
  0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7,
  0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3, 0xc4, 0xc5,
  0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda, 0xe1, 0xe2,
  0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea, 0xf1, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
  0xf9, 0xfa,
];
const AC_CHROMA_BITS = [0, 2, 1, 2, 4, 4, 3, 4, 7, 5, 4, 4, 0, 1, 2, 0x77];
const AC_CHROMA_VALS = [
  0x00, 0x01, 0x02, 0x03, 0x11, 0x04, 0x05, 0x21, 0x31, 0x06, 0x12, 0x41, 0x51, 0x07, 0x61, 0x71,
  0x13, 0x22, 0x32, 0x81, 0x08, 0x14, 0x42, 0x91, 0xa1, 0xb1, 0xc1, 0x09, 0x23, 0x33, 0x52, 0xf0,
  0x15, 0x62, 0x72, 0xd1, 0x0a, 0x16, 0x24, 0x34, 0xe1, 0x25, 0xf1, 0x17, 0x18, 0x19, 0x1a, 0x26,
  0x27, 0x28, 0x29, 0x2a, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3a, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48,
  0x49, 0x4a, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59, 0x5a, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68,
  0x69, 0x6a, 0x73, 0x74, 0x75, 0x76, 0x77, 0x78, 0x79, 0x7a, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87,
  0x88, 0x89, 0x8a, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9a, 0xa2, 0xa3, 0xa4, 0xa5,
  0xa6, 0xa7, 0xa8, 0xa9, 0xaa, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7, 0xb8, 0xb9, 0xba, 0xc2, 0xc3,
  0xc4, 0xc5, 0xc6, 0xc7, 0xc8, 0xc9, 0xca, 0xd2, 0xd3, 0xd4, 0xd5, 0xd6, 0xd7, 0xd8, 0xd9, 0xda,
  0xe2, 0xe3, 0xe4, 0xe5, 0xe6, 0xe7, 0xe8, 0xe9, 0xea, 0xf2, 0xf3, 0xf4, 0xf5, 0xf6, 0xf7, 0xf8,
  0xf9, 0xfa,
];

// libjpeg's scaling of the example tables to a quality of 1–100.
function scaledTable(base, quality) {
  const scale = quality < 50 ? 5000 / quality : 200 - quality * 2;
  return base.map((q) => Math.min(255, Math.max(1, Math.floor((q * scale + 50) / 100))));
}

// Code and length per symbol, from a table's BITS and HUFFVAL lists.
function huffmanCodes(bits, values) {
  const codes = new Uint16Array(256);
  const sizes = new Uint8Array(256);
  let code = 0;
  let k = 0;
  for (let length = 1; length <= 16; length++) {
    for (let i = 0; i < bits[length - 1]; i++) {
      codes[values[k]] = code;
      sizes[values[k]] = length;
      code++;
      k++;
    }
    code <<= 1;
  }
  return { codes, sizes };
}

class BitWriter {
  constructor() {
    this.chunks = [];
    this.buffer = new Uint8Array(1 << 16);
    this.length = 0;
    this.bits = 0;
    this.count = 0;
  }

  byte(value) {
    if (this.length === this.buffer.length) {
      this.chunks.push(this.buffer);
      this.buffer = new Uint8Array(1 << 16);
      this.length = 0;
    }
    this.buffer[this.length++] = value;
  }

  write(code, size) {
    this.bits = (this.bits << size) | code;
    this.count += size;
    while (this.count >= 8) {
      const value = (this.bits >>> (this.count - 8)) & 0xff;
      this.byte(value);
      if (value === 0xff) this.byte(0); // byte stuffing
      this.count -= 8;
    }
    this.bits &= (1 << this.count) - 1;
  }

  flush() {
    if (this.count > 0) this.write((1 << (8 - this.count)) - 1, 8 - this.count);
    this.chunks.push(this.buffer.subarray(0, this.length));
    this.buffer = new Uint8Array(1 << 16);
    this.length = 0;
    return this.chunks;
  }
}

// Forward DCT of one 8×8 block in place, then quantised into `out` in zig-zag
// order; `divisors` holds the AAN-scaled quantisers (divisorsFor below).
//
// The DCT and the quantisers' scale factors are adapted from the Independent
// JPEG Group's software: jfdctflt.c (Copyright (C) 1994-1996, Thomas G.
// Lane), the Arai–Agui–Nakajima algorithm in floating point, and the
// floating-point path of jcdctmgr.c. Changed: rewritten in JavaScript, with
// the quantisation and the zig-zag order folded into the DCT's last loop.
// This software is based in part on the work of the Independent JPEG Group.
// The IJG's terms, from the "LEGAL ISSUES" section of its README:
//
//   In plain English:
//
//   1. We don't promise that this software works.  (But if you find any bugs,
//      please let us know!)
//   2. You can use this software for whatever you want.  You don't have to pay us.
//   3. You may not pretend that you wrote this software.  If you use it in a
//      program, you must acknowledge somewhere in your documentation that
//      you've used the IJG code.
//
//   In legalese:
//
//   The authors make NO WARRANTY or representation, either express or implied,
//   with respect to this software, its quality, accuracy, merchantability, or
//   fitness for a particular purpose.  This software is provided "AS IS", and you,
//   its user, assume the entire risk as to its quality and accuracy.
//
//   This software is copyright (C) 1991-2020, Thomas G. Lane, Guido Vollbeding.
//   All Rights Reserved except as specified below.
//
//   Permission is hereby granted to use, copy, modify, and distribute this
//   software (or portions thereof) for any purpose, without fee, subject to these
//   conditions:
//   (1) If any part of the source code for this software is distributed, then this
//   README file must be included, with this copyright and no-warranty notice
//   unaltered; and any additions, deletions, or changes to the original files
//   must be clearly indicated in accompanying documentation.
//   (2) If only executable code is distributed, then the accompanying
//   documentation must state that "this software is based in part on the work of
//   the Independent JPEG Group".
//   (3) Permission for use of this software is granted only if the user accepts
//   full responsibility for any undesirable consequences; the authors accept
//   NO LIABILITY for damages of any kind.
//
//   These conditions apply to any software derived from or based on the IJG code,
//   not just to the unmodified library.  If you use our work, you ought to
//   acknowledge us.
//
//   Permission is NOT granted for the use of any IJG author's name or company name
//   in advertising or publicity relating to this software or products derived from
//   it.  This software may be referred to only as "the Independent JPEG Group's
//   software".
//
//   We specifically permit and encourage the use of this software as the basis of
//   commercial products, provided that all warranty or liability claims are
//   assumed by the product vendor.
function fdctQuantize(block, divisors, out) {
  for (let i = 0; i < 64; i += 8) {
    const t0 = block[i] + block[i + 7];
    const t7 = block[i] - block[i + 7];
    const t1 = block[i + 1] + block[i + 6];
    const t6 = block[i + 1] - block[i + 6];
    const t2 = block[i + 2] + block[i + 5];
    const t5 = block[i + 2] - block[i + 5];
    const t3 = block[i + 3] + block[i + 4];
    const t4 = block[i + 3] - block[i + 4];
    let t10 = t0 + t3;
    const t13 = t0 - t3;
    let t11 = t1 + t2;
    let t12 = t1 - t2;
    block[i] = t10 + t11;
    block[i + 4] = t10 - t11;
    const z1 = (t12 + t13) * 0.707106781;
    block[i + 2] = t13 + z1;
    block[i + 6] = t13 - z1;
    t10 = t4 + t5;
    t11 = t5 + t6;
    t12 = t6 + t7;
    const z5 = (t10 - t12) * 0.382683433;
    const z2 = 0.5411961 * t10 + z5;
    const z4 = 1.306562965 * t12 + z5;
    const z3 = t11 * 0.707106781;
    const z11 = t7 + z3;
    const z13 = t7 - z3;
    block[i + 5] = z13 + z2;
    block[i + 3] = z13 - z2;
    block[i + 1] = z11 + z4;
    block[i + 7] = z11 - z4;
  }
  for (let i = 0; i < 8; i++) {
    const t0 = block[i] + block[i + 56];
    const t7 = block[i] - block[i + 56];
    const t1 = block[i + 8] + block[i + 48];
    const t6 = block[i + 8] - block[i + 48];
    const t2 = block[i + 16] + block[i + 40];
    const t5 = block[i + 16] - block[i + 40];
    const t3 = block[i + 24] + block[i + 32];
    const t4 = block[i + 24] - block[i + 32];
    let t10 = t0 + t3;
    const t13 = t0 - t3;
    let t11 = t1 + t2;
    let t12 = t1 - t2;
    block[i] = t10 + t11;
    block[i + 32] = t10 - t11;
    const z1 = (t12 + t13) * 0.707106781;
    block[i + 16] = t13 + z1;
    block[i + 48] = t13 - z1;
    t10 = t4 + t5;
    t11 = t5 + t6;
    t12 = t6 + t7;
    const z5 = (t10 - t12) * 0.382683433;
    const z2 = 0.5411961 * t10 + z5;
    const z4 = 1.306562965 * t12 + z5;
    const z3 = t11 * 0.707106781;
    const z11 = t7 + z3;
    const z13 = t7 - z3;
    block[i + 40] = z13 + z2;
    block[i + 24] = z13 - z2;
    block[i + 8] = z11 + z4;
    block[i + 56] = z11 - z4;
  }
  for (let k = 0; k < 64; k++) {
    const index = ZIGZAG[k];
    out[k] = Math.round(block[index] / divisors[index]);
  }
}

const AAN_SCALE = [1.0, 1.387039845, 1.306562965, 1.175875602, 1.0, 0.785694958, 0.5411961, 0.275899379];

// `table` in natural (row-major) order, like the Annex K listings above.
function divisorsFor(table) {
  const divisors = new Float64Array(64);
  for (let row = 0; row < 8; row++) {
    for (let col = 0; col < 8; col++) {
      divisors[row * 8 + col] = table[row * 8 + col] * AAN_SCALE[row] * AAN_SCALE[col] * 8;
    }
  }
  return divisors;
}

function magnitude(value) {
  let v = value < 0 ? -value : value;
  let size = 0;
  while (v) {
    size++;
    v >>= 1;
  }
  return size;
}

function encodeBlock(writer, coefficients, previousDc, dc, ac) {
  const diff = coefficients[0] - previousDc;
  const dcSize = magnitude(diff);
  writer.write(dc.codes[dcSize], dc.sizes[dcSize]);
  if (dcSize) writer.write(diff < 0 ? diff + (1 << dcSize) - 1 : diff, dcSize);
  let run = 0;
  for (let k = 1; k < 64; k++) {
    const value = coefficients[k];
    if (value === 0) {
      run++;
      continue;
    }
    while (run > 15) {
      writer.write(ac.codes[0xf0], ac.sizes[0xf0]);
      run -= 16;
    }
    const size = magnitude(value);
    const symbol = (run << 4) | size;
    writer.write(ac.codes[symbol], ac.sizes[symbol]);
    writer.write(value < 0 ? value + (1 << size) - 1 : value, size);
    run = 0;
  }
  if (run > 0) writer.write(ac.codes[0], ac.sizes[0]);
  return coefficients[0];
}

function segment(marker, body) {
  const out = new Uint8Array(4 + body.length);
  out[0] = 0xff;
  out[1] = marker;
  out[2] = (body.length + 2) >> 8;
  out[3] = (body.length + 2) & 0xff;
  out.set(body, 4);
  return out;
}

// APP1 "Exif" with one IFD0 entry: Orientation (0x0112) = `orientation`.
function exifOrientation(orientation) {
  return segment(
    0xe1,
    new Uint8Array([
      0x45, 0x78, 0x69, 0x66, 0, 0, // "Exif\0\0"
      0x4d, 0x4d, 0, 0x2a, 0, 0, 0, 8, // big-endian TIFF header, IFD0 at 8
      0, 1, // one entry
      0x01, 0x12, 0, 3, 0, 0, 0, 1, 0, orientation, 0, 0, // Orientation, SHORT, 1
      0, 0, 0, 0, // no next IFD
    ]),
  );
}

function headers(width, height, lumaTable, chromaTable, orientation) {
  // DQT lists a table in zig-zag order.
  const dqt = new Uint8Array(130);
  dqt[0] = 0;
  dqt[65] = 1;
  for (let k = 0; k < 64; k++) {
    dqt[1 + k] = lumaTable[ZIGZAG[k]];
    dqt[66 + k] = chromaTable[ZIGZAG[k]];
  }
  const sof = new Uint8Array([
    8, height >> 8, height & 0xff, width >> 8, width & 0xff, 3,
    1, 0x22, 0, // Y: 2×2 sampling, table 0
    2, 0x11, 1, // Cb
    3, 0x11, 1, // Cr
  ]);
  const tables = [
    [0x00, DC_LUMA_BITS, DC_LUMA_VALS],
    [0x10, AC_LUMA_BITS, AC_LUMA_VALS],
    [0x01, DC_CHROMA_BITS, DC_CHROMA_VALS],
    [0x11, AC_CHROMA_BITS, AC_CHROMA_VALS],
  ];
  const dht = [];
  for (const [id, bits, values] of tables) dht.push(id, ...bits, ...values);
  const sos = new Uint8Array([3, 1, 0x00, 2, 0x11, 3, 0x11, 0, 63, 0]);
  const parts = [new Uint8Array([0xff, 0xd8])];
  if (orientation) parts.push(exifOrientation(orientation));
  parts.push(segment(0xdb, dqt), segment(0xc0, sof), segment(0xc4, new Uint8Array(dht)), segment(0xda, sos));
  return parts;
}

// A deterministic generator: mulberry32.
function random(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Per column of a test photo `width` wide: the sines and cosines its colour
// fields need, so that a row costs additions and products only.
function photoColumns(width, imageWidth) {
  const columns = new Float32Array(width * 7);
  for (let x = 0; x < width; x++) {
    const u = x / imageWidth;
    const i = x * 7;
    columns[i] = Math.sin(u * 4.1);
    columns[i + 1] = Math.cos(u * 4.1);
    columns[i + 2] = Math.sin(u * 3.3);
    columns[i + 3] = Math.cos(u * 3.3);
    columns[i + 4] = Math.sin(u * 1.7);
    columns[i + 5] = Math.cos(u * 1.7);
    columns[i + 6] = u;
  }
  return columns;
}

const clamp = (value) => (value < 0 ? 0 : value > 255 ? 255 : value);

// The marker's share of the width and of the height: a red corner at the top
// left as stored, which a photo turned by its orientation shows at the top
// right (check/device-check.js looks for it there).
const MARKER = 1 / 6;

// RGB for rows y0 … y0+rows-1 of a test photo `height` high, into `rgb`
// (`width` pixels a row, the image's width rounded up to whole blocks).
function photoRows(width, height, y0, rows, rgb, columns, next) {
  for (let dy = 0; dy < rows; dy++) {
    const y = Math.min(y0 + dy, height - 1);
    const v = y / height;
    const marked = v < MARKER;
    // Large soft areas: sky, a slope, a few colour fields —
    // sin(a + b) = sin a · cos b + cos a · sin b, with a per column.
    const r1 = Math.cos(v * 2.3);
    const r2 = Math.sin(v * 2.3);
    const g1 = Math.cos(1.0 - v * 5.1);
    const g2 = Math.sin(1.0 - v * 5.1);
    const b1 = Math.cos(v * 3.7 + 2.0);
    const b2 = Math.sin(v * 3.7 + 2.0);
    // Edges and texture: stripes whose pitch changes down the image, like
    // foliage or fabric. sin(x·f + p), stepped by rotation along the row.
    const f = 0.05 + 0.3 * v;
    const cf = Math.cos(f);
    const sf = Math.sin(f);
    let s = Math.sin(20 * Math.sin(y * 0.002));
    let c = Math.cos(20 * Math.sin(y * 0.002));
    for (let x = 0; x < width; x++) {
      const k = x * 7;
      const stripe = s > 0.6 ? 28 : 0;
      // Sensor grain.
      const grain = (next() - 0.5) * 26;
      const i = (dy * width + x) * 3;
      rgb[i] = clamp(150 + 70 * (columns[k] * r1 + columns[k + 1] * r2) - 40 * v + stripe + grain);
      rgb[i + 1] = clamp(140 + 60 * (columns[k + 2] * g1 + columns[k + 3] * g2) + stripe * 0.8 + grain);
      rgb[i + 2] = clamp(
        120 + 80 * (columns[k + 4] * b1 + columns[k + 5] * b2) - 30 * columns[k + 6] + stripe * 0.5 + grain,
      );
      if (marked && columns[k + 6] < MARKER) {
        // The marker: red with the photo's grain, a colour the photo never has
        // (its green stays above 60).
        rgb[i] = clamp(215 + grain);
        rgb[i + 1] = clamp(35 + grain * 0.5);
        rgb[i + 2] = clamp(40 + grain * 0.5);
      }
      const sn = s * cf + c * sf;
      c = c * cf - s * sf;
      s = sn;
    }
  }
}

/**
 * A test photo as JPEG chunks (Uint8Arrays to concatenate, or to hand to a
 * Blob), `width` × `height` pixels, 4:2:0, at `quality`, with EXIF
 * `orientation` (0 for none). `onProgress(done)` gets the share done, 0–1.
 * Yields to the event loop every few strips, so the page stays responsive.
 */
export async function testPhoto({ width, height, quality = 90, orientation = 6, seed = 1, onProgress }) {
  const lumaTable = scaledTable(LUMA_QT, quality);
  const chromaTable = scaledTable(CHROMA_QT, quality);
  const lumaDivisors = divisorsFor(lumaTable);
  const chromaDivisors = divisorsFor(chromaTable);
  const dcLuma = huffmanCodes(DC_LUMA_BITS, DC_LUMA_VALS);
  const acLuma = huffmanCodes(AC_LUMA_BITS, AC_LUMA_VALS);
  const dcChroma = huffmanCodes(DC_CHROMA_BITS, DC_CHROMA_VALS);
  const acChroma = huffmanCodes(AC_CHROMA_BITS, AC_CHROMA_VALS);
  // The quantisation tables go into the file in zig-zag order.
  const writer = new BitWriter();
  const next = random(seed);
  const mcuCols = Math.ceil(width / 16);
  const rgb = new Float32Array(mcuCols * 16 * 16 * 3);
  const block = new Float64Array(64);
  const coefficients = new Int32Array(64);
  let dcY = 0;
  let dcCb = 0;
  let dcCr = 0;
  const stride = mcuCols * 16;
  const columns = photoColumns(stride, width);
  for (let y0 = 0; y0 < height; y0 += 16) {
    photoRows(stride, height, y0, 16, rgb, columns, next);
    for (let mx = 0; mx < mcuCols; mx++) {
      const x0 = mx * 16;
      // Four 8×8 luma blocks.
      for (let by = 0; by < 2; by++) {
        for (let bx = 0; bx < 2; bx++) {
          for (let yy = 0; yy < 8; yy++) {
            for (let xx = 0; xx < 8; xx++) {
              const i = ((by * 8 + yy) * stride + x0 + bx * 8 + xx) * 3;
              block[yy * 8 + xx] = 0.299 * rgb[i] + 0.587 * rgb[i + 1] + 0.114 * rgb[i + 2] - 128;
            }
          }
          fdctQuantize(block, lumaDivisors, coefficients);
          dcY = encodeBlock(writer, coefficients, dcY, dcLuma, acLuma);
        }
      }
      // One Cb and one Cr block: the mean of each 2×2 pixel square.
      for (const [component, dcPrevious] of [
        [1, dcCb],
        [2, dcCr],
      ]) {
        for (let yy = 0; yy < 8; yy++) {
          for (let xx = 0; xx < 8; xx++) {
            let sum = 0;
            for (let sy = 0; sy < 2; sy++) {
              for (let sx = 0; sx < 2; sx++) {
                const i = ((yy * 2 + sy) * stride + x0 + xx * 2 + sx) * 3;
                const r = rgb[i];
                const g = rgb[i + 1];
                const b = rgb[i + 2];
                sum +=
                  component === 1
                    ? -0.168736 * r - 0.331264 * g + 0.5 * b
                    : 0.5 * r - 0.418688 * g - 0.081312 * b;
              }
            }
            block[yy * 8 + xx] = sum / 4;
          }
        }
        fdctQuantize(block, chromaDivisors, coefficients);
        const dc = encodeBlock(writer, coefficients, dcPrevious, dcChroma, acChroma);
        if (component === 1) dcCb = dc;
        else dcCr = dc;
      }
    }
    if ((y0 / 16) % 16 === 15) {
      if (onProgress) onProgress(Math.min(1, (y0 + 16) / height));
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
  }
  const body = writer.flush();
  return [...headers(width, height, lumaTable, chromaTable, orientation), ...body, new Uint8Array([0xff, 0xd9])];
}
