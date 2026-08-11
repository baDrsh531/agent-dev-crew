# Benchmark results

- provider: `openai_compatible`
- model: `E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`
- token budget per run: 400,000
- tool-call ceiling per agent: 40
- repetitions per task: 3
- concurrent runs: 1
- tasks passing every repetition: **3/4**
- total tokens: 3,392,329
- total cost: $0.0000
- total time: 3682s

A task passes when the hidden acceptance tests go green *and* the
pre-existing suite has not regressed. The crew never sees the hidden tests.

| task | passes | scores | hidden | tool calls | tokens | time |
|---|---|---|---|---|---|---|
| `jwt_auth` | 0/3 | PARTIAL, PARTIAL, PARTIAL | 13 (13–13)/13 | 49 (49–52) | 408,356 (405,947–426,715) | 403s (286–458) |
| `pagination` | 3/3 | PASS, PASS, PASS | 11 (11–11)/11 | 27 (27–28) | 205,562 (200,694–211,039) | 215s (202–297) |
| `search` | 3/3 | PASS, PASS, PASS | 12 (12–12)/12 | 32 (32–33) | 270,514 (268,461–291,087) | 191s (180–295) |
| `tag_validation` | 3/3 | PASS, PASS, PASS | 12 (12–12)/12 | 29 (27–29) | 241,069 (221,342–241,543) | 375s (373–408) |

Values are the median, with the observed range in brackets. A task
marked flaky produced different outcomes from identical inputs.

## Failures

### `jwt_auth` — partial
- run error: token budget exhausted (426715/400000)

### `jwt_auth` — partial
- run error: token budget exhausted (408356/400000)

### `jwt_auth` — partial
- run error: token budget exhausted (405947/400000)
