// SPDX-License-Identifier: AGPL-3.0-or-later
// Pricing-page audience switch: "For developers & SaaS" <-> "For public sector
// & compliance". CSP-safe — no inline handlers, wired via addEventListener.
// The switch is the segmented component (_components/segmented.html): its look
// follows aria-pressed alone, so this script sets aria-pressed and shows one
// panel, and never touches classes. panel-gov ships hidden in the markup;
// without JS the comparison table below still lists every tier.
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
  }

  segDev.addEventListener("click", () => show("dev"));
  segGov.addEventListener("click", () => show("gov"));
});
