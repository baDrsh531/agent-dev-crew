# Comparison

Overall: **mixed**

A difference is only called real when the two observed ranges do not
overlap. With a handful of repetitions, anything weaker is noise.

| task | metric | before | after | change | verdict |
|---|---|---|---|---:|---|
| `jwt_auth` | tokens | 305,398 (285,401–315,206) | 406,691 (402,461–407,902) | +33% | worse |
| `jwt_auth` | tool_calls | 44 (40–45) | 49 (47–51) | +11% | worse |
| `pagination` | tokens | 242,343 (231,486–246,894) | 195,884 (195,267–199,094) | -19% | better |
| `pagination` | tool_calls | 31 (30–34) | 26 (24–28) | -16% | better |
| `search` | tokens | 400,940 (270,747–406,610) | 267,938 (213,890–282,494) | -33% | indistinguishable |
| `search` | tool_calls | 52 (36–53) | 32 (28–33) | -38% | better |
| `tag_validation` | tokens | 401,278 (381,281–475,712) | 241,058 (235,297–241,191) | -40% | better |
| `tag_validation` | tool_calls | 38 (35–38) | 29 (29–29) | -24% | better |