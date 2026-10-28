// SPDX-License-Identifier: AGPL-3.0-or-later
// Engine files are cached as immutable: a browser that has one never asks
// again, not even for new headers. This fingerprint of the delivery headers
// (CSP, type, caching) is part of the tree hash in every engine URL, so a new
// fingerprint gives every engine file a new URL and its new headers reach
// every browser. tests/test_engine_delivery.py says when it is due, and the
// value.
export const DELIVERY = "3e8812542112";
