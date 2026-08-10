# Benchmark results

- provider: `openai_compatible`
- model: `E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`
- token budget per run: 400,000
- tool-call ceiling per agent: 40
- repetitions per task: 3
- concurrent runs: 1
- tasks passing every repetition: **0/4**
- total tokens: 1,153,779
- total cost: $0.0000
- total time: 2376s

A task passes when the hidden acceptance tests go green *and* the
pre-existing suite has not regressed. The crew never sees the hidden tests.

| task | passes | scores | hidden | tool calls | tokens | time |
|---|---|---|---|---|---|---|
| `jwt_auth` | 1/3 ⚠︎ flaky | PASS, PARTIAL, FAIL | 2 (0–13)/13 | 55 (42–65) | 412,989 (322,781–418,009) | 504s (493–1,361) |
| `pagination` | 0/3 | FAIL, FAIL, FAIL | — | 0 (0–0) | 0 (0–0) | 2s (2–2) |
| `search` | 0/3 | FAIL, FAIL, FAIL | — | 0 (0–0) | 0 (0–0) | 2s (2–2) |
| `tag_validation` | 0/3 | FAIL, FAIL, FAIL | — | 0 (0–0) | 0 (0–0) | 2s (2–2) |

Values are the median, with the observed range in brackets. A task
marked flaky produced different outcomes from identical inputs.

## Failures

### `jwt_auth` — partial
- run error: token budget exhausted (418009/400000)
- hidden tests: 3 failed, 8 errors
```
- Asserti...
FAILED tests/test_acceptance_hidden.py::test_admin_purge_rejects_an_anonymous_caller
ERROR tests/test_acceptance_hidden.py::test_create_access_token_exists_with_the_agreed_signature
ERROR tests/test_acceptance_hidden.py::test_token_carries_sub_and_role_claims
ERROR tests/test_acceptance_hidden.py::test_reading_one_note_stays_public - F...
ERROR tests/test_acceptance_hidden.py::test_writing_with_a_valid_token_succeeds
ERROR tests/test_acceptance_hidden.py::test_patch_and_delete_require_a_token
ERROR tests/test_acceptance_hidden.py::test_an_expired_token_is_401 - Failed:...
ERROR tests/test_acceptance_hidden.py::test_admin_purge_forbids_a_non_admin_token
ERROR tests/test_acceptance_hidden.py::test_admin_purge_allows_an_admin_token
3 failed, 2 passed, 1 warning, 8 errors in 1.57s
```

### `jwt_auth` — fail
- run error: token budget exhausted (412989/400000)

### `pagination` — fail
- run error: could not put run bench-pa on its own branch agent/bench-pa-add-pagination-to-get-notes-accept-a-lim: 

### `pagination` — fail
- run error: could not put run bench-pa on its own branch agent/bench-pa-add-pagination-to-get-notes-accept-a-lim: 

### `pagination` — fail
- run error: could not put run bench-pa on its own branch agent/bench-pa-add-pagination-to-get-notes-accept-a-lim: 

### `search` — fail
- run error: could not put run bench-se on its own branch agent/bench-se-add-a-search-endpoint-get-notes-search-i: 

### `search` — fail
- run error: could not put run bench-se on its own branch agent/bench-se-add-a-search-endpoint-get-notes-search-i: 

### `search` — fail
- run error: could not put run bench-se on its own branch agent/bench-se-add-a-search-endpoint-get-notes-search-i: 

### `tag_validation` — fail
- run error: could not put run bench-ta on its own branch agent/bench-ta-tighten-validation-of-the-tags-field-on: 

### `tag_validation` — fail
- run error: could not put run bench-ta on its own branch agent/bench-ta-tighten-validation-of-the-tags-field-on: 

### `tag_validation` — fail
- run error: could not put run bench-ta on its own branch agent/bench-ta-tighten-validation-of-the-tags-field-on: 
