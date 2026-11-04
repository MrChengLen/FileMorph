### Fixed — a signed-in conversion no longer holds a database connection while it runs

Resolving the caller of a conversion, compression, PDF or AI request (a
sign-in token, or an API key looked up in the database) read the account in
the request's database session and left that read transaction open until
the response was done. Each such request, while it converted and while it
waited for a free conversion slot, kept one pooled database connection
"idle in transaction", with a lock on the accounts table. Enough of them at
once could use up the connection pool, so that sign-ins and other database
requests had to wait, and a change to the accounts table had to wait for
all of them. The lookups now end their read transaction before the route
runs, as the routes that call Stripe or send mail already did.
