### Changed — limit messages name the free way past a limit instead of an upgrade

A request that hits a tier limit no longer hears "upgrade your plan": the hosted
service has no paid plan to upgrade to. Callers without an account are pointed
to a free account, as before, and now also for batches ("Register free to send
up to 10 files per request"), for target sizes above the output cap and for the
`/compress` output cap. Everyone else is pointed to self-hosting FileMorph
("Self-host FileMorph for larger files" / "for a higher cap" / "for larger
batches"). This covers the file-size, output-cap, target-size and batch-size
messages of `/convert`, `/compress` and the PDF tools, single and batch, plus
the monthly-quota 429 ("Wait until the reset, or self-host FileMorph without a
monthly limit") and the concurrency 429. The AI routes keep their wording.

- A file that is too large inside a batch now names the next step as well.
  Every route builds this message the same way.
- Web interface: the three texts for "file too large", "result too large" and
  "target size above the limit" name self-hosting for everyone and the free
  account for visitors without one. The page doesn't know the caller's tier.
  They no longer claim a conversion worked when it stopped at the cap.
  The link next to them reads "Costs and limits" ("Kosten und Grenzen") where no
  plan can be booked; with Stripe configured it stays "See plans and limits".
- The 2 GB target-size ceiling on `/pdf/compress` gets its own text, since
  neither an account nor self-hosting lifts it.
- The German texts use the informal "du" like the rest of the site (the three
  old ones were formal).
- `docs/api-usage-guide.md` and `docs/api-reference.md` quote the new messages.
