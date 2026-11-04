### Fixed — a signed-in conversion no longer holds a database connection while it runs

Resolving the signed-in caller of a conversion, compression, PDF or AI
request read the account in the request's database session and left that
read transaction open until the response was done: while the request waited
for a conversion slot, converted and sent its result, it kept one pooled
database connection "idle in transaction", with a lock on the accounts
table. A key from the key file did the same on an instance with accounts.
Enough of them at once could use up the connection pool, so that sign-ins
and other database requests had to wait, and a migration that alters the
accounts table had to wait for all of them. The lookups now end their read
transaction before the route runs, as the password-reset and
online-cancellation routes already did.
