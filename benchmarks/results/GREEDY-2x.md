# Benchmark results

- provider: `openai_compatible`
- model: `E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`
- token budget per run: 1,200,000
- tool-call ceiling per agent: 80
- repetitions per task: 2
- tasks passing every repetition: **4/4**
- total tokens: 2,497,497
- total cost: $0.0000
- total time: 2991s

A task passes when the hidden acceptance tests go green *and* the
pre-existing suite has not regressed. The crew never sees the hidden tests.

| task | passes | scores | hidden | tool calls | tokens | time |
|---|---|---|---|---|---|---|
| `jwt_auth` | 2/2 | PASS, PASS | 13 (13–13)/13 | 46 (45–46) | 302,584 (300,895–304,273) | 253s (228–277) |
| `pagination` | 2/2 | PASS, PASS | 11 (11–11)/11 | 32 (30–33) | 229,321 (223,920–234,722) | 278s (222–334) |
| `search` | 2/2 | PASS, PASS | 12 (12–12)/12 | 34 (34–35) | 211,542 (201,503–221,580) | 213s (194–232) |
| `tag_validation` | 2/2 | PASS, PASS | 12 (12–12)/12 | 50 (43–57) | 505,302 (428,737–581,867) | 751s (715–786) |

Values are the median, with the observed range in brackets. A task
marked flaky produced different outcomes from identical inputs.