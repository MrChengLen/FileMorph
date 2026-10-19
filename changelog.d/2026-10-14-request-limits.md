### Security — Request size limits count the bytes that arrive

The request size limit now counts the body as it arrives, not only the
`Content-Length` header. It is `MAX_UPLOAD_SIZE_MB` (default 100 MB) per
request on the file endpoints (`/convert`, `/compress`, the PDF tools and
the AI routes), and 1 MB on every other endpoint: the account, keys,
billing, contact and Stripe webhook routes, whose JSON bodies are a few KB.
A body past its limit gets `413` ("File too large. Maximum size: N MB" on
the file endpoints, "Request too large. Maximum size: 1 MB" elsewhere); a
`Content-Length` above the limit is refused before anything is read.

The Stripe webhook refuses a request without a `stripe-signature` header
before reading its body.

The limits live in `app/core/request_limits.py`, a pure ASGI middleware
that replaces the `limit_upload_size` HTTP middleware. Its `413` answers
carry the CORS and security headers like any route's response.
