### Fixed — Password reset finds the account in any letter case; long passwords work again; password checks run in a worker thread

- **Forgot password** (`/api/v1/auth/forgot-password`) finds the account by
  its address, ignoring letter case, and sends the reset email after the
  response. The online cancellation (`/api/v1/billing/cancellation`)
  compares addresses the same way.
- **Passwords longer than 72 bytes** work again for registration, password
  reset and sign-in. bcrypt reads only the first 72 bytes; since bcrypt 5 it
  refuses longer input, so registration and reset with such a password
  failed with a `500`. FileMorph now passes bcrypt the first 72 bytes
  itself, which gives the same hash as before.
- **Sign-in, registration, password reset and account deletion** hash or
  check passwords in a worker thread, so a password check no longer holds
  up other requests.
