# Benchmark results

- provider: `openai_compatible`
- model: `E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`
- token budget per run: 1,200,000
- tool-call ceiling per agent: 80
- tasks passed: **3/4**
- total tokens: 1,494,789
- total cost: $0.0000
- total time: 987s

A task passes when the hidden acceptance tests go green *and* the
pre-existing suite has not regressed. The crew never sees the hidden tests.

| task | score | status | hidden | own suite | repairs | tools | tokens | time |
|---|---|---|---|---|---:|---:|---:|---:|
| `jwt_auth` | **PASS** | succeeded | 13/13 | 17 passed | 0 | 61 | 545,411 | 304s |
| `pagination` | **PARTIAL** | succeeded | 3/11 | 18 passed | 0 | 42 | 292,336 | 226s |
| `search` | **PASS** | succeeded | 12/12 | 17 passed | 0 | 33 | 198,393 | 165s |
| `tag_validation` | **PASS** | succeeded | 12/12 | 24 passed | 0 | 45 | 458,649 | 292s |

## Failures

### `pagination` — partial
- hidden tests: 8 failed, 0 errors
```
o/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_acceptance_hidden.py::test_default_limit_is_20 - AssertionE...
FAILED tests/test_acceptance_hidden.py::test_fewer_notes_than_the_limit_returns_all
FAILED tests/test_acceptance_hidden.py::test_explicit_limit_is_honoured - Ass...
FAILED tests/test_acceptance_hidden.py::test_limit_above_100_is_capped_not_rejected
FAILED tests/test_acceptance_hidden.py::test_offset_skips_notes - TypeError: ...
FAILED tests/test_acceptance_hidden.py::test_offset_beyond_the_end_returns_empty
FAILED tests/test_acceptance_hidden.py::test_tag_filter_is_applied_before_pagination
FAILED tests/test_acceptance_hidden.py::test_results_stay_ordered_by_id - Typ...
8 failed, 3 passed, 1 warning in 3.66s
```
