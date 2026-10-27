### Security — dnspython 2.9.0: excessive CPU on crafted DNS messages fixed

dnspython, which email-validator pulls in, moves from 2.8.0 to 2.9.0. That
fixes CVE-2026-114605 (GHSA-45c3-73f7-pv4m, high): a crafted DNS message
could make its name decompression use excessive CPU. Not reachable here:
FileMorph checks email addresses with Pydantic's `EmailStr`, which skips
email-validator's DNS lookups, and no other dependency uses dnspython. The
new version is a floor in `requirements.txt`, so a later re-lock cannot fall
back below it; nothing else in the lockfile moved.
