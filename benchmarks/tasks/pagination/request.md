Add pagination to `GET /notes`.

- Accept a `limit` query parameter, defaulting to 20.
- Accept an `offset` query parameter, defaulting to 0.
- A `limit` above 100 must be **silently capped to 100**, not rejected.
- A `limit` of zero or negative, or a negative `offset`, must return HTTP 422.
- The existing `tag` filter must keep working, and filtering must happen
  **before** pagination is applied.
- Notes must stay ordered by ascending id.
