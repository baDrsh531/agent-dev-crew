Add JWT bearer authentication to the API.

**Access rules**

- `GET /health`, `GET /notes` and `GET /notes/{id}` stay public.
- `POST /notes`, `PATCH /notes/{id}` and `DELETE /notes/{id}` require a valid
  bearer token. Without one, or with an invalid or expired one, return HTTP 401.
- `DELETE /admin/notes` additionally requires the token to carry the `admin`
  role. A valid non-admin token must get HTTP 403, not 401.

**Token contract** — the benchmark mints tokens with this exact interface, so it
must exist as written:

- Module `app/auth.py`.
- `create_access_token(subject: str, role: str = "user", expires_in: int = 3600) -> str`
  returns a signed JWT whose `sub` claim is `subject` and whose `role` claim is
  `role`, expiring `expires_in` seconds from now.
- Tokens are signed with HS256 using the secret from the `JWT_SECRET`
  environment variable, defaulting to `"dev-secret"` when it is unset.

**Existing tests**

The current suite writes notes without any token, so it will start failing the
moment the routes are protected. Update those tests to authenticate — that
migration is part of the work, not an accident — and leave the whole suite
green. Do not weaken a test to make it pass: a test that asserted a write
succeeds must still assert that, with a token.

Install `pyjwt` if you need it.
