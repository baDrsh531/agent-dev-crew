# Comparison

Overall: **worse**

A difference is only called real when the two observed ranges do not
overlap. With a handful of repetitions, anything weaker is noise.

| task | metric | before | after | change | verdict |
|---|---|---|---|---:|---|
| `jwt_auth` | tokens | 406,035 (405,596–406,079) | 405,908 (400,502–410,055) | -0% | indistinguishable |
| `jwt_auth` | tool_calls | 49 (49–49) | 49 (47–50) | +0% | indistinguishable |
| `pagination` | tokens | 187,565 (185,441–194,696) | 214,291 (207,704–283,907) | +14% | worse |
| `pagination` | tool_calls | 25 (23–26) | 27 (27–27) | +8% | worse |
| `search` | tokens | 297,872 (262,298–312,160) | 280,047 (279,620–288,426) | -6% | indistinguishable |
| `search` | tool_calls | 34 (32–34) | 32 (32–34) | -6% | indistinguishable |
| `tag_validation` | tokens | 243,510 (230,308–243,750) | 233,977 (231,734–253,909) | -4% | indistinguishable |
| `tag_validation` | tool_calls | 29 (29–31) | 29 (28–65) | +0% | indistinguishable |