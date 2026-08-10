# Benchmark results

- provider: `openai_compatible`
- model: `E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`
- token budget per run: 400,000
- tool-call ceiling per agent: 40
- repetitions per task: 3
- concurrent runs: 1
- tasks passing every repetition: **1/4**
- total tokens: 4,055,296
- total cost: $0.0000
- total time: 4092s

A task passes when the hidden acceptance tests go green *and* the
pre-existing suite has not regressed. The crew never sees the hidden tests.

| task | passes | scores | hidden | tool calls | tokens | time |
|---|---|---|---|---|---|---|
| `jwt_auth` | 2/3 ⚠︎ flaky | PARTIAL, PASS, PASS | 13 (13–13)/13 | 51 (49–54) | 346,589 (333,560–405,599) | 330s (308–391) |
| `pagination` | 3/3 | PASS, PASS, PASS | 11 (11–11)/11 | 40 (39–40) | 248,552 (246,939–264,726) | 224s (214–315) |
| `search` | 2/3 ⚠︎ flaky | PARTIAL, PASS, PASS | 12 (12–12)/12 | 50 (46–54) | 320,878 (265,808–404,498) | 216s (203–223) |
| `tag_validation` | 0/3 ⚠︎ flaky | REGRESSION, PARTIAL, FAIL | 8 (0–12)/12 | 47 (44–51) | 406,698 (402,260–409,189) | 509s (429–730) |

Values are the median, with the observed range in brackets. A task
marked flaky produced different outcomes from identical inputs.

## Failures

### `jwt_auth` — partial
- run error: token budget exhausted (405599/400000)

### `search` — partial
- run error: token budget exhausted (404498/400000)

### `tag_validation` — regression
- run error: token budget exhausted (402260/400000)
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
4 failed, 8 passed, 1 warning in 1.65s
```

### `tag_validation` — partial
- run error: token budget exhausted (406698/400000)

### `tag_validation` — fail
- run error: token budget exhausted (409189/400000)
