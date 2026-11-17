// SPDX-License-Identifier: AGPL-3.0-or-later
// A worker that compresses one file (ops/compress.js) off the page's thread.
// The page starts one per file and ends it afterwards, which also hands its
// memory back. Message in: `{ file, options }`; out: `{ ok: true, result }`
// or `{ ok: false, code, detail }`.

import { compress } from "./compress.js";

self.onmessage = async (event) => {
  const { file, options } = event.data;
  try {
    self.postMessage({ ok: true, result: await compress(file, options) });
  } catch (error) {
    // The engine's code and the cause it knows of, or a browser error's name
    // (a DOMException's numeric legacy code is not one); the page checks
    // what it records.
    const code = typeof error?.code === "string" ? error.code : error?.name || "worker-failed";
    self.postMessage({ ok: false, code, detail: error?.detail || "" });
  }
};
