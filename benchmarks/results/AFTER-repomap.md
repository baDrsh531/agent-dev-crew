# Benchmark results

- provider: `openai_compatible`
- model: `E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`
- token budget per run: 1,200,000
- tool-call ceiling per agent: 80
- tasks passed: **3/4**
- total tokens: 2,358,223
- total cost: $0.0000
- total time: 2222s

A task passes when the hidden acceptance tests go green *and* the
pre-existing suite has not regressed. The crew never sees the hidden tests.

| task | score | status | hidden | own suite | repairs | tools | tokens | time |
|---|---|---|---|---|---:|---:|---:|---:|
| `jwt_auth` | **PASS** | succeeded | 13/13 | 13 passed | 2 | 103 | 997,460 | 808s |
| `pagination` | **PASS** | succeeded | 11/11 | 21 passed | 0 | 30 | 246,602 | 240s |
| `search` | **REGRESSION** | escalated | 9/12 | 13 passed, 2 failed | 2 | 70 | 827,396 | 896s |
| `tag_validation` | **PASS** | succeeded | 12/12 | 18 passed | 0 | 37 | 286,765 | 276s |

## Failures

### `search` — regression
- run error: QA still failing after 2 repair iterations (limit 2). A human should look at the findings.
- hidden tests: 3 failed, 0 errors
```
ary ===============================
..\..\.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\atm-view\Desktop\mine\multi agent\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_acceptance_hidden.py::test_blank_q_returns_422[] - Assertio...
FAILED tests/test_acceptance_hidden.py::test_blank_q_returns_422[   ] - Asser...
FAILED tests/test_acceptance_hidden.py::test_blank_q_returns_422[\t] - Assert...
3 failed, 9 passed, 1 warning in 1.56s
```
