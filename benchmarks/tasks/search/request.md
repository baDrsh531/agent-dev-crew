Add a search endpoint: `GET /notes/search`.

- It takes a required `q` query parameter. A missing `q` returns HTTP 422.
- A `q` that is empty or only whitespace returns HTTP 422.
- It returns every note whose **title or body** contains `q`, matched
  **case-insensitively** as a substring.
- The response has the same shape as `GET /notes` — a JSON list of notes —
  ordered by ascending id.
- When nothing matches it returns an empty list with HTTP 200, not a 404.
- Existing routes must keep working unchanged.
