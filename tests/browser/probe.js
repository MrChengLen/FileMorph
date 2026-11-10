// SPDX-License-Identifier: AGPL-3.0-or-later
// The probe page's script (tests/browser/probe.py): one way per channel to
// send data to the server, each aimed at /__bt/hit/<channel>. The tests call
// window.fmProbe.run(channel) and then ask the server's recorder what
// arrived; the browser's own account is the list of CSP violations it
// reported (securitypolicyviolation events), kept in window.fmProbe.violations.
(() => {
  "use strict";

  const violations = [];
  document.addEventListener("securitypolicyviolation", (event) => {
    violations.push({
      directive: event.effectiveDirective || event.violatedDirective,
      blocked: event.blockedURI,
    });
  });

  // Every probe carries the test's tag in its path, so that a test finds its
  // own requests in the recorder and none of an earlier one.
  const target = (channel, tag) => new URL(`/__bt/hit/${channel}-${tag}`, location.href).href;

  // Each resolves once the browser has sent the request or refused it — the
  // beacon and the form post as soon as they are handed over, before they are
  // sent. A refusal may show up as an exception, an error event or nothing at
  // all, depending on the browser: the tests go by the recorder and the
  // violation reports, never by this outcome.
  const channels = {
    fetch: (tag) => fetch(target("fetch", tag), { method: "POST", body: "probe" }),
    xhr: (tag) =>
      new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", target("xhr", tag));
        xhr.onload = resolve;
        xhr.onerror = () => reject(new Error("xhr error"));
        xhr.send("probe");
      }),
    beacon: (tag) => {
      if (!navigator.sendBeacon(target("beacon", tag), "probe")) {
        throw new Error("sendBeacon returned false");
      }
    },
    websocket: (tag) =>
      new Promise((resolve, reject) => {
        const socket = new WebSocket(target("websocket", tag).replace(/^http/, "ws"));
        socket.onopen = () => {
          socket.close();
          resolve();
        };
        socket.onclose = () => reject(new Error("websocket closed"));
        socket.onerror = () => reject(new Error("websocket error"));
      }),
    eventsource: (tag) =>
      new Promise((resolve, reject) => {
        const source = new EventSource(target("eventsource", tag));
        source.onopen = () => {
          source.close();
          resolve();
        };
        source.onerror = () => {
          source.close();
          reject(new Error("eventsource error"));
        };
      }),
    // The hit answers 204, so a form post that goes through leaves the page
    // where it is.
    form: (tag) => {
      const form = document.getElementById("form-probe");
      form.action = target("form", tag);
      form.submit();
    },
    // Allowed under every profile (img-src 'self'): proves that the page ran
    // and that the recorder sees what the browser sends.
    image: (tag) =>
      new Promise((resolve) => {
        const image = new Image();
        image.onload = resolve;
        image.onerror = resolve;
        image.src = target("image", tag);
      }),
  };

  const settle = (promise, ms) =>
    Promise.race([promise, new Promise((resolve) => setTimeout(resolve, ms))]);

  window.fmProbe = {
    violations,
    async run(channel, tag) {
      try {
        await settle(
          Promise.resolve().then(() => channels[channel](tag)),
          3000,
        );
        return { threw: null };
      } catch (error) {
        return { threw: String(error) };
      }
    },
    // A module from the engine mount, imported as the engine's pages will
    // import theirs: the names it exports.
    async engine(url) {
      const module = await import(url);
      return Object.keys(module);
    },
  };
})();
