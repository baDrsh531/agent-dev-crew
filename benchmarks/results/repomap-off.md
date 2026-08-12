# Benchmark results

- provider: `openai_compatible`
- model: `E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`
- token budget per run: 400,000
- tool-call ceiling per agent: 40
- repetitions per task: 3
- concurrent runs: 1
- tasks passing every repetition: **2/4**
- total tokens: 3,963,296
- total cost: $0.0000
- total time: 4758s

A task passes when the hidden acceptance tests go green *and* the
pre-existing suite has not regressed. The crew never sees the hidden tests.

| task | passes | scores | hidden | tool calls | tokens | time |
|---|---|---|---|---|---|---|
| `jwt_auth` | 3/3 | PASS, PASS, PASS | 13 (13–13)/13 | 44 (40–45) | 305,398 (285,401–315,206) | 261s (227–266) |
| `pagination` | 3/3 | PASS, PASS, PASS | 11 (11–11)/11 | 31 (30–34) | 242,343 (231,486–246,894) | 278s (244–306) |
| `search` | 1/3 ⚠︎ flaky | PASS, PARTIAL, PARTIAL | 12 (12–12)/12 | 52 (36–53) | 400,940 (270,747–406,610) | 233s (206–233) |
| `tag_validation` | 0/3 | REGRESSION, REGRESSION, REGRESSION | 8 (8–12)/12 | 38 (35–38) | 401,278 (381,281–475,712) | 744s (727–1,033) |

Values are the median, with the observed range in brackets. A task
marked flaky produced different outcomes from identical inputs.

## Failures

### `search` — partial
- run error: token budget exhausted (406610/400000)

### `search` — partial
- run error: token budget exhausted (400940/400000)

### `tag_validation` — regression
- run error: QA Engineer produced an artifact that does not match the QAReport schema: 1 validation error for QAReport
  Invalid JSON: EOF while parsing a string at line 26 column 58433 [type=json_invalid, input_value='{\n  "verdict": "fail",\...r` with `mode=\'after\'', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/json_invalid
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
4 failed, 8 passed, 1 warning in 2.18s
```

### `tag_validation` — regression
- run error: QA still failing after 2 repair iterations (limit 2). A human should look at the findings.
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
4 failed, 8 passed, 1 warning in 1.84s
```

### `tag_validation` — regression
- run error: token budget exhausted (401278/400000)
