# Comparison

Overall: **mixed**

A difference is only called real when the two observed ranges do not
overlap. With a handful of repetitions, anything weaker is noise.

| task | metric | before | after | change | verdict |
|---|---|---|---|---:|---|
| `jwt_auth` | tokens | 355,416 (310,768–400,063) | 407,686 (402,016–413,357) | +15% | worse |
| `jwt_auth` | tool_calls | 45 (39–51) | 43 (43–43) | -4% | indistinguishable |
| `pagination` | tokens | 154,158 (105,188–203,129) | 227,213 (215,463–238,963) | +47% | worse |
| `pagination` | tool_calls | 25 (23–27) | 32 (28–35) | +26% | worse |
| `search` | tokens | 240,308 (231,953–248,662) | 251,258 (188,324–314,191) | +5% | indistinguishable |
| `search` | tool_calls | 37 (36–38) | 38 (36–39) | +1% | indistinguishable |
| `tag_validation` | tokens | 423,858 (421,347–426,370) | 413,783 (410,054–417,512) | -2% | better |
| `tag_validation` | tool_calls | 39 (38–40) | 40 (39–40) | +1% | indistinguishable |