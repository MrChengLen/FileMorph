### Fixed — no sign-in links where an instance has no accounts

A Community Edition instance has no database and so no accounts, yet its
navigation offered "Sign In" and the home page's developer section "Get API
Key →". Both led to forms that could only fail: the account API answers 503
there, and the forgot-password form even reported an email it never sent.
Where an instance has no accounts:

- The navigation has no Sign In link, on desktop and mobile.
- The developer section links "How to get an API key ↗" instead of the sign-up
  form: the self-hosting guide's API Key management section, since keys come
  from the instance's key file there.
- The account pages (`/login`, `/register`, `/forgot-password`,
  `/reset-password`, `/verify-email`, `/dashboard`, `/account-deleted`,
  `/cockpit`) answer 404, as `/pricing` does where the pricing page is off.

The developer section's curl example now targets the instance itself
(`APP_BASE_URL`) instead of filemorph.io, since a key from an instance's key
file is valid only there. Copied as it was, the example sent the file to
filemorph.io.

Instances with accounts, such as filemorph.io, are unchanged.
`docs/self-hosting.md` and `docs/installation.md` describe the behaviour.
