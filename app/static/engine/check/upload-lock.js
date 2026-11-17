// SPDX-License-Identifier: AGPL-3.0-or-later
// The device check's self-test of the upload lock: one request that this
// page's CSP must refuse. The only engine file allowed a network call, and
// only this one (tests/test_engine_code.py): it shows the user, instead of
// asking them to trust it, that the page cannot send their photos anywhere.

/**
 * Resolves to true when the browser refused the request because of the
 * page's CSP (it reports a connect-src violation it enforced), false
 * otherwise — and false whenever an answer came back, since then the
 * request left: a policy that only reports, one a proxy added say, refuses
 * nothing. Offline, a refused request reports no violation: run it while
 * online.
 */
export function uploadLockActive() {
  return new Promise((resolve) => {
    let refused = false;
    const listener = (event) => {
      const directive = event.effectiveDirective || event.violatedDirective;
      if (directive === "connect-src" && event.disposition !== "report") refused = true;
    };
    document.addEventListener("securitypolicyviolation", listener);
    const settle = (answered) =>
      // The violation event can come after the promise settles.
      setTimeout(() => {
        document.removeEventListener("securitypolicyviolation", listener);
        resolve(refused && !answered);
      }, 250);
    // A GET of a public file: were the lock missing, this request and nothing
    // more would leave the phone.
    fetch("/robots.txt", { cache: "no-store" }).then(
      () => settle(true),
      () => settle(false),
    );
  });
}
