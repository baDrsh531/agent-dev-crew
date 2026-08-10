Tighten validation of the `tags` field on notes.

- A note may carry at most 10 tags. More than 10 returns HTTP 422.
- A tag that is empty or whitespace-only is rejected with HTTP 422.
- A tag longer than 30 characters is rejected with HTTP 422.
- Duplicate tags are **not** an error: they are silently de-duplicated,
  preserving the order of first appearance.
- The rules apply to both `POST /notes` and `PATCH /notes/{id}`.
- Everything else about notes is unchanged.
