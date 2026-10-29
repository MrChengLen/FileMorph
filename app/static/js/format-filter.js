// SPDX-License-Identifier: AGPL-3.0-or-later
// Format search on /formats (docs-internal/navigation-suche-konzept-2026-10.md):
// filters the server-rendered list in place, by format ("heic", ".jpeg"),
// another name or a kind of file ("Word", "iPhone", "Foto") or a pair
// ("heic to jpg"). The words and labels come from the server
// (partials/format_filter.html), the texts as data-* attributes. Without this
// script the field stays invisible and the full list shows. The query lives in
// the fragment (#q=), never in a query string, so it makes no new addresses.
(function () {
  'use strict';

  const root = document.getElementById('format-filter');
  if (!root) return;
  const input = document.getElementById('format-q');
  const status = document.getElementById('format-status');
  const live = document.getElementById('format-live');
  const empty = document.getElementById('format-empty');
  const showAll = document.getElementById('format-show-all');

  const words = JSON.parse(root.dataset.words);
  const labels = JSON.parse(root.dataset.labels);
  const FORMATS = Object.keys(labels);
  const pairs = Array.from(document.querySelectorAll('[data-pair]'));
  const items = Array.from(document.querySelectorAll('[data-formats]'));
  const groups = Array.from(document.querySelectorAll('[data-filter-group]'));
  const TOOLS = items.filter((el) => el.hasAttribute('data-tool'));

  const own = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
  const fill = (text, values) => text.replace(/\{(\w+)\}/g, (m, k) => (own(values, k) ? values[k] : m));
  const label = (f) => labels[f];
  // "JPG", "HEIC/HEIF/MOV"; for more, the word that was typed ("video").
  const names = (fs, typed) => (fs.length <= 3 ? fs.map(label).join('/') : typed.trim());

  function clean(term) {
    return term.trim().toLowerCase().replace(/^\*?\./, '');
  }

  // A known word or format name, or nothing.
  function exact(term) {
    term = clean(term);
    if (!term) return [];
    if (own(words, term)) return words[term];
    if (own(labels, term)) return [term];
    return [];
  }

  // As exact, else every format whose name starts with the term ("we" →
  // WebM, WebP), else the formats of every search word that does ("vid" →
  // Video), so the list narrows while typing.
  function loose(term) {
    const hit = exact(term);
    if (hit.length) return hit;
    term = clean(term);
    if (!term) return [];
    const named = FORMATS.filter((f) => f.startsWith(term) || label(f).toLowerCase().startsWith(term));
    if (named.length) return named;
    const found = new Set();
    Object.keys(words).forEach((word) => {
      if (word.startsWith(term)) words[word].forEach((f) => found.add(f));
    });
    return Array.from(found);
  }

  // The first word of some text that names something ("convert heic" → HEIC
  // when read from the end, "jpg converter" → JPG from the start).
  function anyWord(text, fromEnd) {
    const parts = text.trim().split(/\s+/);
    if (fromEnd) parts.reverse();
    for (const part of parts) {
      const hit = exact(part);
      if (hit.length) return hit;
    }
    return [];
  }

  function side(text, fromEnd) {
    const hit = loose(text);
    return hit.length ? hit : anyWord(text, fromEnd);
  }

  // "heic to jpg", "heic in jpg", "heic → jpg", "heic-to-jpg", "heic jpg",
  // and with filler words: "convert heic to jpg".
  const PAIR = /^(.+?)\s*(?:->|→|=>|\s(?:in|zu|to|nach|into)\s|-to-)\s*(.+)$/i;
  function parsePair(q) {
    const m = q.match(PAIR);
    if (m) return { from: side(m[1], true), to: side(m[2], false), fromText: m[1], toText: m[2] };
    const parts = q.split(/\s+/);
    if (parts.length === 2) {
      const from = exact(parts[0]);
      const to = exact(parts[1]);
      if (from.length && to.length) return { from, to, fromText: parts[0], toText: parts[1] };
    }
    return null;
  }

  function show(el, visible) {
    // Chips carry display classes (inline-block), which beat the hidden
    // attribute; the class "hidden" comes later in the stylesheet and wins.
    el.classList.toggle('hidden', !visible);
  }

  function filter(pairTest, itemTest) {
    pairs.forEach((el) => {
      const [src, tgt] = el.dataset.pair.split(' ');
      show(el, pairTest(src, tgt));
    });
    items.forEach((el) => show(el, itemTest(el.dataset.formats.split(' '))));
    groups.forEach((group) => {
      const visible = group.querySelector('[data-pair]:not(.hidden), [data-formats]:not(.hidden)');
      group.hidden = !visible;
    });
  }

  function byFormats(fs) {
    filter(
      (src, tgt) => fs.includes(src) || fs.includes(tgt),
      (formats) => formats.some((f) => fs.includes(f))
    );
  }

  function counts() {
    const n = pairs.filter((el) => !el.classList.contains('hidden')).length;
    let text = fill(root.dataset.textCount, { n, total: pairs.length });
    const tools = TOOLS.filter((el) => !el.classList.contains('hidden')).length;
    if (tools) text += ' · ' + fill(root.dataset.textTools, { n: tools, total: TOOLS.length });
    return text;
  }

  let liveTimer = 0;
  function say(text) {
    status.textContent = text;
    // The live region reads every change aloud: only the settled one.
    clearTimeout(liveTimer);
    liveTimer = setTimeout(() => {
      live.textContent = text;
    }, 400);
  }

  // No format or pair needs more; a longer "#q=" link could make the pair
  // pattern backtrack for seconds and freeze the tab.
  const MAX_QUERY = 64;

  function apply(q) {
    q = q.trim().slice(0, MAX_QUERY);
    empty.hidden = true;
    if (!q) {
      filter(() => true, () => true);
      say('');
      return;
    }
    const pair = parsePair(q);
    if (pair && pair.from.length && pair.to.length) {
      const hits = (src, tgt) => pair.from.includes(src) && pair.to.includes(tgt);
      if (pairs.some((el) => hits(...el.dataset.pair.split(' ')))) {
        // Conversions only: a tool is no answer to "A to B".
        filter(hits, () => false);
        say(counts());
      } else if (pair.from.some((f) => pair.to.includes(f))) {
        // "pdf to pdf", "jpg to jpeg": no conversion, but the tools and the
        // list of the format are the answer.
        byFormats(pair.from);
        say(counts());
      } else {
        // An honest "no", then everything the first format can do.
        byFormats(pair.from);
        const missing = fill(root.dataset.textMissing, {
          src: names(pair.from, pair.fromText),
          tgt: names(pair.to, pair.toText),
        });
        say(missing + ' ' + counts());
      }
      return;
    }
    let fs = loose(q);
    // "pdf in" while typing "pdf in jpg", "convert pdf": a word that names
    // something already counts.
    if (!fs.length && /\s/.test(q)) fs = anyWord(q, false);
    if (fs.length) {
      byFormats(fs);
      say(counts());
      return;
    }
    filter(() => false, () => false);
    empty.hidden = false;
    say(fill(root.dataset.textEmpty, { q }));
  }

  function readHash() {
    return new URLSearchParams(location.hash.slice(1)).get('q') || '';
  }

  function writeHash(q) {
    const url = q.trim() ? '#q=' + encodeURIComponent(q.trim()) : location.pathname + location.search;
    history.replaceState(null, '', url);
  }

  function setQuery(q) {
    input.value = q;
    apply(q);
    writeHash(q);
  }

  input.addEventListener('input', () => {
    apply(input.value);
    writeHash(input.value);
  });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && input.value) {
      e.preventDefault();
      setQuery('');
    }
    // The list already shows the result: put the phone's keyboard away.
    if (e.key === 'Enter') input.blur();
  });
  showAll.addEventListener('click', () => {
    setQuery('');
    input.focus();
  });
  window.addEventListener('hashchange', () => {
    const q = readHash();
    if (q !== input.value) {
      input.value = q;
      apply(q);
    }
  });

  root.classList.remove('invisible');
  const initial = readHash();
  if (initial) {
    input.value = initial;
    apply(initial);
  }
})();
