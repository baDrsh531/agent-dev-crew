# Benchmark results

- provider: `openai_compatible`
- model: `E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`
- token budget per run: 400,000
- tool-call ceiling per agent: 40
- repetitions per task: 2
- concurrent runs: 1
- tasks passing every repetition: **1/4**
- total tokens: 2,347,480
- total cost: $0.0000
- total time: 3393s

A task passes when the hidden acceptance tests go green *and* the
pre-existing suite has not regressed. The crew never sees the hidden tests.

| task | passes | scores | hidden | tool calls | tokens | time |
|---|---|---|---|---|---|---|
| `jwt_auth` | 1/2 ⚠︎ flaky | PASS, PARTIAL | 13 (13–13)/13 | 45 (39–51) | 355,416 (310,768–400,063) | 276s (170–383) |
| `pagination` | 1/2 ⚠︎ flaky | PASS, PARTIAL | 11 (11–11)/11 | 25 (23–27) | 154,158 (105,188–203,129) | 159s (108–210) |
| `search` | 2/2 | PASS, PASS | 12 (12–12)/12 | 37 (36–38) | 240,308 (231,953–248,662) | 213s (201–225) |
| `tag_validation` | 0/2 | REGRESSION, REGRESSION | 7 (6–8)/12 | 39 (38–40) | 423,858 (421,347–426,370) | 1,048s (882–1,214) |

Values are the median, with the observed range in brackets. A task
marked flaky produced different outcomes from identical inputs.

## Failures

### `jwt_auth` — partial
- run error: token budget exhausted (400063/400000)

### `pagination` — partial
- run error: EndpointUnavailable: http://192.168.0.64:30000/v1 is unreachable: Server disconnected without sending a response.

### `tag_validation` — regression
- run error: QA still failing after 2 repair iterations (limit 2). A human should look at the findings.
- hidden tests: 6 failed, 0 errors
```
` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_acceptance_hidden.py::test_ten_tags_are_accepted - pydantic...
FAILED tests/test_acceptance_hidden.py::test_tag_of_exactly_30_characters_is_accepted
FAILED tests/test_acceptance_hidden.py::test_duplicates_are_deduplicated_not_rejected
FAILED tests/test_acceptance_hidden.py::test_patch_enforces_the_same_rules - ...
FAILED tests/test_acceptance_hidden.py::test_patch_deduplicates_too - pydanti...
FAILED tests/test_acceptance_hidden.py::test_notes_without_tags_still_work - ...
6 failed, 6 passed, 1 warning in 2.24s
```

### `tag_validation` — regression
- run error: token budget exhausted (426370/400000)
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
4 failed, 8 passed, 1 warning in 1.32s
```
