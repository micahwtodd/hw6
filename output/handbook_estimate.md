# Problem 2 — Handbook Size and Cost Estimate

**File measured:** `data/shop_handbook.md`
**Model:** `gpt-6-luna` (via Portkey)
**Prices:** `data/prices.json`

> These are **estimates** made before any API call. Problem 4 checks them against the real `usage` numbers the API returns.

---

## 1. Token count

| Measure | Value |
|---|---|
| **Estimated tokens (o200k_base tokenizer)** | **10,058** |
| Cross-check: cl100k_base tokenizer (older GPT-4) | 10,184 |
| Characters (with `\n` line endings) | 28,903 |
| Words | 6,127 |
| Lines | 338 |

### How I got it

1. I read `data/shop_handbook.md` as UTF-8 text in Python.
2. I tokenized it with OpenAI's open-source tokenizer library, `tiktoken`, using the `o200k_base` encoding:

   ```python
   import tiktoken
   text = open("data/shop_handbook.md", encoding="utf-8").read()
   enc = tiktoken.get_encoding("o200k_base")
   print(len(enc.encode(text)))   # 10058
   ```

**Why `o200k_base`:** `tiktoken` has no mapping for `gpt-6-luna`, and asking it for one raises a "could not map" error. `o200k_base` is the tokenizer `tiktoken` uses for OpenAI's GPT-4o and GPT-5 families, so it's the closest public stand-in. The real gpt-6 tokenizer may count slightly differently. Problem 4 will show the exact number.

**A rule of thumb would have been well off.** "1 token ≈ 4 characters" gives 28,903 ÷ 4 ≈ **7,226**, about 28% too low. The handbook is mostly tables: pipes (`|`), SKU codes like `CC-HD-001`, and prices like `$29.48` all break into many small tokens. That's why I counted with a real tokenizer instead of estimating.

---

## 2. Prices used (from `data/prices.json`)

| gpt-6-luna rate | $ per 1M tokens | $ per token |
|---|---|---|
| Input (normal) | $0.10 | $0.0000001 |
| Cached input (read from cache) | $0.01 | $0.00000001 |
| Cache write (first time into the cache) | $0.125 | $0.000000125 |
| Output | $0.50 | $0.0000005 |

Formula: **cost = tokens × (price per 1M ÷ 1,000,000)**

The handbook is **input** only, so the output price doesn't apply to it. Output depends on the agent's answer, not the handbook.

---

## 3. Cost of the handbook alone — ONE call

### a) Without caching (normal input)

```
10,058 tokens × $0.10 / 1,000,000
= 10,058 × $0.0000001
= $0.0010058
≈ $0.0010 per call  (about one-tenth of a cent)
```

### b) With caching — the first call (cache write)

The first call has to write the handbook into the cache. That costs 1.25× the normal input price.

```
10,058 tokens × $0.125 / 1,000,000
= 10,058 × $0.000000125
= $0.00125725
≈ $0.0013 per call
```

### c) With caching — every later call (cache hit)

```
10,058 tokens × $0.01 / 1,000,000
= 10,058 × $0.00000001
= $0.00010058
≈ $0.0001 per call  (10× cheaper than normal input)
```

---

## 4. Cost of the handbook alone — 1,000 calls

### a) Without caching

```
1,000 calls × $0.0010058
= $1.0058
≈ $1.01
```

### b) With caching (1 cache write + 999 cache hits)

```
Call 1 (write):    1 × $0.00125725   = $0.00125725
Calls 2–1000 (hit): 999 × $0.00010058 = $0.10047942
                                       -----------
Total                                  = $0.10173667
                                       ≈ $0.10
```

### c) Savings from caching

```
Saved:   $1.0058 − $0.10173667 = $0.90406333  ≈ $0.90
Percent: $0.90406333 ÷ $1.0058 = 0.8989       ≈ 89.9% cheaper
```

---

## 5. Summary

| Scenario | 1 call | 1,000 calls |
|---|---|---|
| **No caching** | $0.0010058 | **$1.0058** (≈ $1.01) |
| **Caching: first call (write)** | $0.00125725 | — |
| **Caching: later call (hit)** | $0.00010058 | — |
| **Caching: 1 write + 999 hits** | — | **$0.1017** (≈ $0.10) |
| **Savings from caching** | — | **$0.9041 (≈ 89.9%)** |

**Takeaway:** Caching makes the first call about 25% more expensive. From the second call on, the handbook costs a tenth as much. Over 1,000 calls, caching cuts the handbook's cost from about $1.01 to about $0.10.

---

## 6. Assumptions and caveats (to check in Problem 4)

1. **Tokenizer.** The 10,058 count comes from `o200k_base`, not gpt-6-luna's own tokenizer, which isn't public. Expect the real count to be close but not identical.
2. **Message overhead.** The API wraps every message in a few formatting tokens. So the `input_tokens` you see for "handbook only" will run a few tokens above 10,058.
3. **Handbook only.** These numbers leave out the agent's instructions, the vendor document, tool definitions and the output. A real call costs more.
4. **Cache lifetime.** The math assumes the handbook stays cached across all 1,000 calls. If the cache expires between calls (lecture 11's example used a 30-minute TTL), each expiry costs another 1.25× write, and the savings shrink.
5. **Exact prefix.** A cache hit only happens if the handbook text is **identical, byte for byte, and at the start of the prompt** on every call. Anything that changes before it, like a timestamp or the vendor document, breaks the cache.
   - The `cached_tokens` the API reports may also not match 10,058 exactly. Providers count the formatting tokens and may cache in fixed-size blocks. Small gaps like that are expected in Problem 4.
6. **Line endings.** The file on disk uses Windows line endings: all 338 lines end in `\r\n`, for 29,241 bytes. Python's normal text mode converts them to `\n`, giving 28,903 characters and **10,058 tokens**, and that's the version I counted. If the agent reads the file in a way that keeps the `\r\n` endings, such as binary mode or `newline=""`, the handbook is **10,069 tokens** (11 more). The agent should read it the normal way so the count stays at 10,058.
