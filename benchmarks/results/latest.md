# Benchmark results

- provider: `openai_compatible`
- model: `E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`
- token budget per run: 400,000
- tool-call ceiling per agent: 40
- repetitions per task: 2
- concurrent runs: 1
- tasks passing every repetition: **1/4**
- total tokens: 2,599,880
- total cost: $0.0000
- total time: 3380s

A task passes when the hidden acceptance tests go green *and* the
pre-existing suite has not regressed. The crew never sees the hidden tests.

| task | passes | scores | hidden | tool calls | tokens | time |
|---|---|---|---|---|---|---|
| `jwt_auth` | 0/2 | PARTIAL, PARTIAL | 5 (5–5)/13 | 43 (43–43) | 407,686 (402,016–413,357) | 374s (334–413) |
| `pagination` | 2/2 | PASS, PASS | 11 (11–11)/11 | 32 (28–35) | 227,213 (215,463–238,963) | 217s (214–220) |
| `search` | 1/2 ⚠︎ flaky | PASS, PARTIAL | 12 (12–12)/12 | 38 (36–39) | 251,258 (188,324–314,191) | 350s (193–506) |
| `tag_validation` | 0/2 | REGRESSION, REGRESSION | 8 (8–8)/12 | 40 (39–40) | 413,783 (410,054–417,512) | 749s (649–849) |

Values are the median, with the observed range in brackets. A task
marked flaky produced different outcomes from identical inputs.

## Failures

### `jwt_auth` — partial
- run error: token budget exhausted (402016/400000)
- hidden tests: 3 failed, 5 errors
```
e-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_acceptance_hidden.py::test_create_access_token_exists_with_the_agreed_signature
FAILED tests/test_acceptance_hidden.py::test_token_carries_sub_and_role_claims
FAILED tests/test_acceptance_hidden.py::test_an_expired_token_is_401 - TypeEr...
ERROR tests/test_acceptance_hidden.py::test_reading_one_note_stays_public - T...
ERROR tests/test_acceptance_hidden.py::test_writing_with_a_valid_token_succeeds
ERROR tests/test_acceptance_hidden.py::test_patch_and_delete_require_a_token
ERROR tests/test_acceptance_hidden.py::test_admin_purge_forbids_a_non_admin_token
ERROR tests/test_acceptance_hidden.py::test_admin_purge_allows_an_admin_token
3 failed, 5 passed, 1 warning, 5 errors in 4.47s
```

### `jwt_auth` — partial
- run error: token budget exhausted (413357/400000)
- hidden tests: 3 failed, 5 errors
```
e-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_acceptance_hidden.py::test_create_access_token_exists_with_the_agreed_signature
FAILED tests/test_acceptance_hidden.py::test_token_carries_sub_and_role_claims
FAILED tests/test_acceptance_hidden.py::test_an_expired_token_is_401 - TypeEr...
ERROR tests/test_acceptance_hidden.py::test_reading_one_note_stays_public - T...
ERROR tests/test_acceptance_hidden.py::test_writing_with_a_valid_token_succeeds
ERROR tests/test_acceptance_hidden.py::test_patch_and_delete_require_a_token
ERROR tests/test_acceptance_hidden.py::test_admin_purge_forbids_a_non_admin_token
ERROR tests/test_acceptance_hidden.py::test_admin_purge_allows_an_admin_token
3 failed, 5 passed, 1 warning, 5 errors in 1.76s
```

### `search` — partial
- run error: Documentation Writer produced an artifact that does not match the DocsBundle schema: 1 validation error for DocsBundle
  Invalid JSON: EOF while parsing a string at line 4 column 11555 [type=json_invalid, input_value='{\n  "changelog_entry": ...ttp\\nGET /notes/search', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/json_invalid

### `tag_validation` — regression
- run error: token budget exhausted (410054/400000)
- hidden tests: 4 failed, 0 errors
```
tclient.py:1
  C:\Users\atm-view\Desktop\mine\multi agent\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_acceptance_hidden.py::test_patch_enforces_the_same_rules - ...
FAILED tests/test_acceptance_hidden.py::test_patch_deduplicates_too - pydanti...
FAILED tests/test_acceptance_hidden.py::test_notes_without_tags_still_work - ...
FAILED tests/test_acceptance_hidden.py::test_existing_behaviour_is_unchanged
4 failed, 8 passed, 1 warning in 2.08s
```

### `tag_validation` — regression
- run error: token budget exhausted (417512/400000)
- hidden tests: 4 failed, 0 errors
```
tclient.py:1
  C:\Users\atm-view\Desktop\mine\multi agent\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_acceptance_hidden.py::test_patch_enforces_the_same_rules - ...
FAILED tests/test_acceptance_hidden.py::test_patch_deduplicates_too - pydanti...
FAILED tests/test_acceptance_hidden.py::test_notes_without_tags_still_work - ...
FAILED tests/test_acceptance_hidden.py::test_existing_behaviour_is_unchanged
4 failed, 8 passed, 1 warning in 2.23s
```
