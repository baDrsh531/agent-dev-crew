# Comparison

Overall: **mixed**

A difference is only called real when the two observed ranges do not
overlap. With a handful of repetitions, anything weaker is noise.

| task | metric | before | after | change | verdict |
|---|---|---|---|---:|---|
| `jwt_auth` | tokens | 330,633 (290,066–336,565) | 408,356 (405,947–426,715) | +24% | worse |
| `jwt_auth` | tool_calls | 47 (40–48) | 49 (49–52) | +4% | worse |
| `pagination` | tokens | 233,825 (227,397–239,447) | 205,562 (200,694–211,039) | -12% | better |
| `pagination` | tool_calls | 31 (30–31) | 27 (27–28) | -13% | better |
| `search` | tokens | 293,568 (235,871–407,570) | 270,514 (268,461–291,087) | -8% | indistinguishable |
| `search` | tool_calls | 40 (35–49) | 32 (32–33) | -20% | better |
| `tag_validation` | tokens | 403,746 (367,694–423,670) | 241,069 (221,342–241,543) | -40% | better |
| `tag_validation` | tool_calls | 41 (34–41) | 29 (27–29) | -29% | better |