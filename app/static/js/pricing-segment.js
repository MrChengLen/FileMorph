// SPDX-License-Identifier: AGPL-3.0-or-later
// Pricing-page audience toggle: "For developers & SaaS" <-> "For public sector
// & compliance". CSP-safe — no inline handlers, wired via addEventListener.
// Mirrors the Convert/Compress mode toggle pattern in app.js. With JS off both
// panels stay visible (panel-gov has the `hidden` class only after JS runs is
// not the case here — it ships hidden in markup; the no-JS fallback is that the
// always-visible comparison table below still shows every tier).
document.addEventListener("DOMContentLoaded", () => {
  const segDev = document.getElementById("seg-dev");
  const segGov = document.getElementById("seg-gov");
  const panelDev = document.getElementById("panel-dev");
  const panelGov = document.getElementById("panel-gov");
  if (!segDev || !segGov || !panelDev || !panelGov) return;

  function show(which) {
    const dev = which === "dev";
    panelDev.classList.toggle("hidden", !dev);
    panelGov.classList.toggle("hidden", dev);
    segDev.setAttribute("aria-pressed", dev ? "true" : "false");
    segGov.setAttribute("aria-pressed", dev ? "false" : "true");
    segDev.classList.toggle("bg-brand", dev);
    segDev.classList.toggle("text-white", dev);
    segDev.classList.toggle("text-gray-400", !dev);
    segGov.classList.toggle("bg-brand", !dev);
    segGov.classList.toggle("text-white", !dev);
    segGov.classList.toggle("text-gray-400", dev);
  }

  segDev.addEventListener("click", () => show("dev"));
  segGov.addEventListener("click", () => show("gov"));
});
