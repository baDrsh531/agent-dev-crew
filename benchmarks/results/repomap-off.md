# Benchmark results

- provider: `openai_compatible`
- model: `E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`
- token budget per run: 400,000
- tool-call ceiling per agent: 40
- repetitions per task: 3
- concurrent runs: 1
- tasks passing every repetition: **2/4**
- total tokens: 3,790,052
- total cost: $0.0000
- total time: 4183s

A task passes when the hidden acceptance tests go green *and* the
pre-existing suite has not regressed. The crew never sees the hidden tests.

| task | passes | scores | hidden | tool calls | tokens | time |
|---|---|---|---|---|---|---|
| `jwt_auth` | 3/3 | PASS, PASS, PASS | 13 (13–13)/13 | 47 (40–48) | 330,633 (290,066–336,565) | 256s (250–281) |
| `pagination` | 3/3 | PASS, PASS, PASS | 11 (11–11)/11 | 31 (30–31) | 233,825 (227,397–239,447) | 225s (223–231) |
| `search` | 2/3 ⚠︎ flaky | PARTIAL, PASS, PASS | 12 (12–12)/12 | 40 (35–49) | 293,568 (235,871–407,570) | 201s (157–289) |
| `tag_validation` | 1/3 ⚠︎ flaky | PASS, REGRESSION, PARTIAL | 12 (8–12)/12 | 41 (34–41) | 403,746 (367,694–423,670) | 661s (583–826) |

Values are the median, with the observed range in brackets. A task
marked flaky produced different outcomes from identical inputs.

## Failures

### `search` — partial
- run error: token budget exhausted (407570/400000)

### `tag_validation` — regression
- run error: token budget exhausted (423670/400000)
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
4 failed, 8 passed, 1 warning in 1.39s
```

### `tag_validation` — partial
- run error: token budget exhausted (403746/400000)
