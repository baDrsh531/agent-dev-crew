# Benchmark results

- provider: `openai_compatible`
- model: `E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`
- token budget per run: 400,000
- tool-call ceiling per agent: 40
- repetitions per task: 3
- concurrent runs: 1
- tasks passing every repetition: **3/4**
- total tokens: 3,375,310
- total cost: $0.0000
- total time: 3133s

A task passes when the hidden acceptance tests go green *and* the
pre-existing suite has not regressed. The crew never sees the hidden tests.

| task | passes | scores | hidden | tool calls | tokens | time |
|---|---|---|---|---|---|---|
| `jwt_auth` | 0/3 | PARTIAL, PARTIAL, PARTIAL | 13 (13–13)/13 | 49 (49–49) | 406,035 (405,596–406,079) | 246s (245–254) |
| `pagination` | 3/3 | PASS, PASS, PASS | 11 (11–11)/11 | 25 (23–26) | 187,565 (185,441–194,696) | 203s (202–286) |
| `search` | 3/3 | PASS, PASS, PASS | 12 (12–12)/12 | 34 (32–34) | 297,872 (262,298–312,160) | 195s (194–322) |
| `tag_validation` | 3/3 | PASS, PASS, PASS | 12 (12–12)/12 | 29 (29–31) | 243,510 (230,308–243,750) | 304s (294–387) |

Values are the median, with the observed range in brackets. A task
marked flaky produced different outcomes from identical inputs.

## Failures

### `jwt_auth` — partial
- run error: token budget exhausted (406079/400000)

### `jwt_auth` — partial
- run error: token budget exhausted (406035/400000)

### `jwt_auth` — partial
- run error: token budget exhausted (405596/400000)
