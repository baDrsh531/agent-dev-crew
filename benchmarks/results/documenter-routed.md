# Benchmark results

- provider: `openai_compatible`
- model: `E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`
- token budget per run: 400,000
- tool-call ceiling per agent: 40
- repetitions per task: 3
- concurrent runs: 1
- tasks passing every repetition: **3/4**
- total tokens: 3,490,080
- total cost: $0.0000
- total time: 4072s

A task passes when the hidden acceptance tests go green *and* the
pre-existing suite has not regressed. The crew never sees the hidden tests.

| task | passes | scores | hidden | tool calls | tokens | time |
|---|---|---|---|---|---|---|
| `jwt_auth` | 0/3 | PARTIAL, PARTIAL, PARTIAL | 13 (13–13)/13 | 49 (47–50) | 405,908 (400,502–410,055) | 410s (252–426) |
| `pagination` | 3/3 | PASS, PASS, PASS | 11 (11–11)/11 | 27 (27–27) | 214,291 (207,704–283,907) | 321s (307–536) |
| `search` | 3/3 | PASS, PASS, PASS | 12 (12–12)/12 | 32 (32–34) | 280,047 (279,620–288,426) | 292s (219–298) |
| `tag_validation` | 3/3 | PASS, PASS, PASS | 12 (12–12)/12 | 29 (28–65) | 233,977 (231,734–253,909) | 359s (285–369) |

Values are the median, with the observed range in brackets. A task
marked flaky produced different outcomes from identical inputs.

## Failures

### `jwt_auth` — partial
- run error: token budget exhausted (405908/400000)

### `jwt_auth` — partial
- run error: token budget exhausted (410055/400000)

### `jwt_auth` — partial
- run error: token budget exhausted (400502/400000)
