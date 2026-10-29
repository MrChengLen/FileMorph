// SPDX-License-Identifier: AGPL-3.0-or-later
// FM_announce(text) reads a short status of the tools ("Processing…", "Your
// file is ready…") to screen-reader users through the page's polite live
// region (#fm-live in base.html). Only text that is already on the screen is
// passed in. The text is set after a short pause, so the same message twice is
// announced twice, and it is cleared after a few seconds, so no stale "done"
// is left for the next run. FM_announce('') empties the region at once (the
// error paths call it, so a pending "Processing…" can't follow the error).
(function () {
  let setTimer = null;
  let clearTimer = null;
  window.FM_announce = function (text) {
    const region = document.getElementById('fm-live');
    if (!region) return;
    clearTimeout(setTimer);
    clearTimeout(clearTimer);
    region.textContent = '';
    if (!text) return;
    setTimer = setTimeout(function () {
      region.textContent = text.trim();
      clearTimer = setTimeout(function () { region.textContent = ''; }, 8000);
    }, 50);
  };
})();
