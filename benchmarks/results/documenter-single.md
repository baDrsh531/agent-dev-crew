# Benchmark results

- provider: `openai_compatible`
- model: `E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`
- token budget per run: 400,000
- tool-call ceiling per agent: 40
- repetitions per task: 3
- concurrent runs: 1
- tasks passing every repetition: **2/4**
- total tokens: 3,048,923
- total cost: $0.0000
- total time: 3154s

A task passes when the hidden acceptance tests go green *and* the
pre-existing suite has not regressed. The crew never sees the hidden tests.

| task | passes | scores | hidden | tool calls | tokens | time |
|---|---|---|---|---|---|---|
| `jwt_auth` | 0/3 | PARTIAL, PARTIAL, PARTIAL | 13 (13–13)/13 | 49 (46–50) | 406,996 (405,712–455,356) | 399s (233–551) |
| `pagination` | 3/3 | PASS, PASS, PASS | 11 (11–11)/11 | 27 (26–28) | 198,496 (196,399–200,627) | 192s (187–198) |
| `search` | 3/3 | PASS, PASS, PASS | 12 (12–12)/12 | 32 (32–32) | 270,822 (265,524–279,792) | 244s (205–291) |
| `tag_validation` | 1/3 ⚠︎ flaky | PARTIAL, PARTIAL, PASS | 12 (4–12)/12 | 22 (4–27) | 135,634 (1,713–231,852) | 202s (39–414) |

Values are the median, with the observed range in brackets. A task
marked flaky produced different outcomes from identical inputs.

## Failures

### `jwt_auth` — partial
- run error: token budget exhausted (455356/400000)

### `jwt_auth` — partial
- run error: token budget exhausted (405712/400000)

### `jwt_auth` — partial
- run error: token budget exhausted (406996/400000)

### `tag_validation` — partial
- run error: EndpointUnavailable: http://192.168.0.64:30000/v1 is unreachable: Server disconnected without sending a response.

### `tag_validation` — partial
- run error: EndpointUnavailable: http://192.168.0.64:30000/v1 is unreachable: All connection attempts failed
- hidden tests: 8 failed, 0 errors
```
capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_acceptance_hidden.py::test_eleven_tags_are_rejected - Asser...
FAILED tests/test_acceptance_hidden.py::test_blank_tags_are_rejected[] - Asse...
FAILED tests/test_acceptance_hidden.py::test_blank_tags_are_rejected[   ] - A...
FAILED tests/test_acceptance_hidden.py::test_blank_tags_are_rejected[\t] - As...
FAILED tests/test_acceptance_hidden.py::test_tag_longer_than_30_characters_is_rejected
FAILED tests/test_acceptance_hidden.py::test_duplicates_are_deduplicated_not_rejected
FAILED tests/test_acceptance_hidden.py::test_patch_enforces_the_same_rules - ...
FAILED tests/test_acceptance_hidden.py::test_patch_deduplicates_too - Asserti...
8 failed, 4 passed, 1 warning in 17.74s
```
