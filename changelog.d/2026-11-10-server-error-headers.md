### Fixed — a server error keeps its page's security headers

The 500 of an unhandled error used to go out without any of the security headers —
Content-Security-Policy, `X-Frame-Options`, `X-Content-Type-Options`,
`Permissions-Policy` — because Starlette sends it from outside the middleware
that sets them. The error handler now sets them itself, with the CSP profile
the failing page had chosen.
