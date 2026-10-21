### Security — certifi 2026.10.19: its CA bundle drops the compromised emSign root

certifi is raised from 2026.7.22 to 2026.10.19 (GHSA-6q48-6c7w-9gw2,
critical). Earlier versions trust the emSign ECC Root CA - G3, below which
eight intermediate CAs had their private keys compromised: whoever holds one
of those keys and sits on the network path could pose as any host to a client
that trusts the bundle. `requirements.txt` now sets `certifi>=2026.10.19`. A
re-lock keeps existing pins, so this floor is what moves certifi past the
advisory and keeps it there; no other dependency changes.

This fixes certifi itself. Its only user in FileMorph is `requests`, which
comes in through the Stripe SDK, and the Stripe SDK checked certificates
against its own CA file, which still contains this root; the entry above
points the SDK at certifi's bundle.
