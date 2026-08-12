# Benchmark results

- provider: `openai_compatible`
- model: `E:\vllm_models\gguf\Qwen_Qwen3.6-35B-A3B-Q4_K_M.gguf`
- token budget per run: 400,000
- tool-call ceiling per agent: 40
- repetitions per task: 3
- concurrent runs: 1
- tasks passing every repetition: **2/4**
- total tokens: 3,289,167
- total cost: $0.0000
- total time: 5158s

A task passes when the hidden acceptance tests go green *and* the
pre-existing suite has not regressed. The crew never sees the hidden tests.

| task | passes | scores | hidden | tool calls | tokens | time |
|---|---|---|---|---|---|---|
| `jwt_auth` | 0/3 | PARTIAL, PARTIAL, PARTIAL | 13 (13–13)/13 | 49 (47–51) | 406,691 (402,461–407,902) | 404s (240–407) |
| `pagination` | 3/3 | PASS, PASS, PASS | 11 (11–11)/11 | 26 (24–28) | 195,884 (195,267–199,094) | 201s (182–294) |
| `search` | 2/3 ⚠︎ flaky | PARTIAL, PASS, PASS | 12 (12–12)/12 | 32 (28–33) | 267,938 (213,890–282,494) | 200s (192–1,889) |
| `tag_validation` | 3/3 | PASS, PASS, PASS | 12 (12–12)/12 | 29 (29–29) | 241,058 (235,297–241,191) | 406s (330–412) |

Values are the median, with the observed range in brackets. A task
marked flaky produced different outcomes from identical inputs.

## Failures

### `jwt_auth` — partial
- run error: token budget exhausted (406691/400000)

### `jwt_auth` — partial
- run error: token budget exhausted (402461/400000)

### `jwt_auth` — partial
- run error: token budget exhausted (407902/400000)

### `search` — partial
- run error: EndpointUnavailable: http://192.168.0.64:30000/v1 is unreachable: 
