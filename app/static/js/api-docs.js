// SPDX-License-Identifier: AGPL-3.0-or-later
// Starts the API explorer on /docs (app/templates/api_docs.html). Lives in its
// own file because the strict CSP allows no inline script; the Swagger UI
// bundle it calls is the vendored, unmodified copy in /static/vendor/ (see
// app/static/vendor/manifest.json and LICENSE-swagger-ui.md).
(function () {
  "use strict";
  var root = document.getElementById("swagger-ui");
  if (!root || typeof window.SwaggerUIBundle !== "function") {
    return;
  }
  var SwaggerUIBundle = window.SwaggerUIBundle;
  SwaggerUIBundle({
    url: root.getAttribute("data-openapi-url") || "/openapi.json",
    dom_id: "#swagger-ui",
    layout: "BaseLayout",
    deepLinking: true,
    showExtensions: true,
    showCommonExtensions: true,
    // Safeguard: BaseLayout shows no validator badge, and null keeps it off
    // under any layout (the badge sends the schema URL to validator.swagger.io).
    validatorUrl: null,
    presets: [SwaggerUIBundle.presets.apis],
  });
})();
