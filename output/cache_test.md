# Problem 4 — With and Without Cached Tokens

**Model:** `gpt-6-luna` through Portkey on every call (the API reports `gpt-6-luna-global` on all 48 calls)
**Documents:** all 12 files in `data/practice_docs/`, each run once in each setup
**Raw data:** every model call is in `output/cache_test.json` (48 calls = 12 documents × 2 setups × 2 calls per run)
**Prices:** `data/prices.json` (gpt-6-luna, per 1M tokens): input $0.10 · cached input $0.01 · cache write $0.125 · output $0.50
**Software:** Python 3.14.7, pydantic-ai 2.66.0, openai 3.49.0, the versions pinned in `requirements.txt`. Run on 2026-11-10 at 19:10, after the cache had been idle for 9 hours.
**Reproduce:** `python cache_test.py`. Run it when no cached run has happened in the last 30 minutes, so the first cache write shows up in the results.

---

## How the test was set up

Every model call sends the same thing, in the same order:

| Order | Content | Same on every call? |
|---|---|---|
| 1 | Tool definitions (`read_document`, `send_email`, `approve_payment`, answer format) and instructions (`prompts/prompt.md`) | yes |
| 2 | The full handbook (`data/shop_handbook.md`) | yes |
| 3 | "Review this vendor document: …", then the document text and the answer | no |

Caching only works on a **prefix**, the part at the start of the prompt that doesn't change. So everything stable goes first and the document goes last. Each run makes **2 model calls**: one to call `read_document`, and one to answer. The handbook goes out on both.

The two setups send exactly the same text. The only difference is the cache settings in each request:

| | Without cache | With cache |
|---|---|---|
| `prompt_cache_options` | `{"mode": "explicit"}` | `{"mode": "explicit", "ttl": "30m"}` |
| Cache breakpoints | **0** | **1**, on the handbook block |
| Effect | `explicit` turns off the breakpoint OpenAI would otherwise place automatically. With no breakpoint at all, nothing can be written to or read from the cache. | Everything up to and including the handbook is cached for 30 minutes and reused by every later call. |

The without-cache setup ran first, so it couldn't pick up anything the with-cache setup wrote. Runs went one at a time, so each call could reuse the cache the call before it wrote.

> **Every answer is a real model run.** Portkey can also store whole *responses*: if a request exactly repeats an earlier one, it hands back the old answer, and the model never runs (a "replay"). Every request in this test sends `x-portkey-cache-force-refresh: true` to turn replays off. All 50 response IDs (48 test calls plus the 2 handbook-size calls) are unique and new, which proves no answer was a replay. This is separate from OpenAI's prompt caching of the handbook, which is what this test measures.

> **One extra field PydanticAI adds.** On each run's second call, pydantic-ai 2.66 adds `comparison_response_id` (the ID of that run's first response) to `prompt_cache_options`, in both setups. This only asks OpenAI to *report* whether the call reused the cache. It is free and doesn't change caching. The without-cache setup still shows 0 cached and 0 written tokens on every call.

> **Why the handbook moved.** In Problem 3 the handbook was part of the instructions. PydanticAI can only attach a cache breakpoint to the user message, so the handbook now goes at the start of the user message in **both** setups. It's still sent on every call.

---

## Proof that each setup did what it was told

These are the token counts the API returned in each call's `usage` block, copied unchanged into `output/cache_test.json`:

| Check | Without cache (24 calls) | With cache (24 calls) |
|---|---|---|
| Breakpoints sent | 0 on every call | 1 on every call |
| `cached_tokens` | **0 on all 24 calls** | 0 on call 1, then **10,828 on each of the other 23 calls** |
| `cache_write_tokens` | **0 on all 24 calls** | **10,828 on call 1 only** (`ttl_30m_tokens: 10,828`), then 0 |
| Total `input_tokens` | 265,504 | 265,504 (identical) |
| Total `output_tokens` | 1,356 | 1,363 |
| Response IDs | 24, all unique | 24, all unique |

- **Without cache counts.** No call shows a single cached or cache-write token, so it meets the homework rule that a without-cache run can't show cached tokens.
- **With cache reused the handbook.** It wrote the prefix once, on its very first call, and every one of the other 23 calls read it back: 23 × 10,828 = 249,044 cached tokens. There were no cache misses.
- **Same input, different billing.** Both setups sent exactly 265,504 input tokens. Caching changed only how those tokens were billed.
- **The cached prefix is 10,828 tokens:** the handbook's 10,058 tokens plus 770 tokens of tool definitions, instructions and message formatting.

`cache_test.py` checks all of these rules automatically, and all of them passed. It also checked that PydanticAI's own token counts matched the raw API numbers on every call, that each call's `total_tokens` equals input plus output, and that no response ID repeats.

---

## 1) Total cost, cost per document, and savings

| | Without cache | With cache |
|---|---|---|
| **Total, 12 documents** | **$0.0272284** | **$0.0050886** |
| **Average per document** | **$0.0022690** | **$0.0004241** |
| Uncached input | $0.0265504 (265,504 tokens) | $0.0005632 (5,632 tokens) |
| Cached input | $0 | $0.0024904 (249,044 tokens) |
| Cache write | $0 | $0.0013535 (10,828 tokens) |
| Output | $0.0006780 (1,356 tokens) | $0.0006815 (1,363 tokens) |

```
Savings  = $0.0272284 − $0.0050886 = $0.0221398
Percent  = $0.0221398 ÷ $0.0272284 = 81.3% cheaper with cache
```

**Once the cache is warm, savings are higher.** The first with-cache document pays to write the cache. Every document after that only reads it:

| With-cache document | Cost | Saved vs. the same document without cache |
|---|---|---|
| First document (p01, writes the cache) | $0.0015672 | 31.0% |
| Average of the next 11 documents (cache already warm) | $0.0003201 | **85.9%** (each one saved between 85.5% and 86.2%) |

### Per document

| Document | Without cache: input tokens | Without cache: cost | With cache: cached | With cache: written | With cache: uncached | With cache: cost | Saved |
|---|---|---|---|---|---|---|---|
| p01_bluehen_quote.html | 22,115 | $0.002272 | 10,828 | 10,828 | 459 | $0.001567 | 31.0% |
| p02_elmcity_quote.html | 22,119 | $0.002272 | 21,656 | 0 | 463 | $0.000324 | 85.7% |
| p03_ivyprint_catalog.html | 22,116 | $0.002265 | 21,656 | 0 | 460 | $0.000317 | 86.0% |
| p04_harborstitch_quote.html | 22,155 | $0.002278 | 21,656 | 0 | 499 | $0.000330 | 85.5% |
| p05_maplemills_quote.pdf | 22,083 | $0.002261 | 21,656 | 0 | 427 | $0.000312 | 86.2% |
| p06_qtextile_quote.pdf | 22,127 | $0.002266 | 21,656 | 0 | 471 | $0.000317 | 86.0% |
| p07_longwharf_quote.pdf | 22,102 | $0.002260 | 21,656 | 0 | 446 | $0.000315 | 86.1% |
| p08_chapelst_email.eml | 22,111 | $0.002272 | 21,656 | 0 | 455 | $0.000324 | 85.8% |
| p09_westville_email.eml | 22,248 | $0.002280 | 21,656 | 0 | 592 | $0.000331 | 85.5% |
| p10_eastrock_email.eml | 22,130 | $0.002273 | 21,656 | 0 | 474 | $0.000319 | 85.9% |
| p11_yorkst_quote.html | 22,099 | $0.002260 | 21,656 | 0 | 443 | $0.000312 | 86.2% |
| p12_bluehen_quote.pdf | 22,099 | $0.002270 | 21,656 | 0 | 443 | $0.000321 | 85.8% |
| **Total** | **265,504** | **$0.027228** | **249,044** | **10,828** | **5,632** | **$0.005089** | **81.3%** |

**Caching didn't change the answers.** Both setups gave the same decision on every document. 9 of 12 match `data/practice_key.json` on every field. The 3 misses come from text planted in the documents, not from caching:
- **p02:** a fake lower price ($5.11).
- **p07:** a fake shorter lead time (7 days). The agent reported 7 days but still reached the key's decision.
- **p12:** a fake "revised" price ($17.44).

These are prompt-injection attacks, covered in Problem 5.

---

## 2) How the real numbers compare to the Problem 2 estimate

### The handbook's token count was exact

| | Problem 2 estimate | Problem 4 actual |
|---|---|---|
| Handbook tokens | **10,058**, from `tiktoken` `o200k_base`, offline | **10,058**, from gpt-6-luna |
| How | Tokenized the file locally | Two no-cache calls, identical except one also sends the handbook: 10,070 − 12 = 10,058 input tokens (`output/handbook_token_check.json`) |
| Difference | — | **0 tokens (0.0%)** |

The API's token-count endpoint isn't available through Portkey (it returned "not supported by azure-openai"). That's why I measured the handbook with two real calls.

### The cost per document was higher than the "handbook alone" estimate

Problem 2 priced only the handbook on one call. A real document costs more, for four reasons:

| Reason | Effect |
|---|---|
| **Each document takes 2 model calls, not 1** | The handbook is sent twice per document: 2 × 10,058 = 20,116 tokens. |
| **The cached prefix is bigger than the handbook** | Tools, instructions and formatting add 770 tokens, so 10,828 tokens get cached and written, not 10,058. |
| **Some input can't be cached** | The document text, the tool result and the question change every time: about 470 tokens per document. |
| **Output tokens** | About 113 per document, at $0.50 per 1M. Caching doesn't discount output. |

**One document without cache: estimate vs. actual**

```
Handbook, 2 calls:        20,116 tokens × $0.10/1M = $0.0020116   (Problem 2's $0.0010058 × 2)
Other input (avg):         2,009 tokens × $0.10/1M = $0.0002009
Output (avg):                113 tokens × $0.50/1M = $0.0000565
                                                     ----------
Rebuilt total                                      = $0.0022690   = actual average $0.0022690 ✓
```

The handbook is **88.7%** of a no-cache document's cost, and **90.9%** of all input tokens.

**One warm document with cache: estimate vs. actual**

```
Cached prefix, 2 calls:   21,656 tokens × $0.01/1M = $0.0002166   (Problem 2's $0.00010058 × 2, plus the 770-token extra each call)
Uncached input (avg):        470 tokens × $0.10/1M = $0.0000470
Output (avg):                113 tokens × $0.50/1M = $0.0000565
                                                     ----------
Rebuilt total                                      = $0.0003201   = actual warm average $0.0003201 ✓
```

### Side by side

| Item | Problem 2 estimate | Problem 4 actual | Why they differ |
|---|---|---|---|
| Handbook tokens | 10,058 | 10,058 | Exact match |
| Cache write (once) | $0.00125725 (10,058 tokens) | $0.0013535 (10,828 tokens) | The prefix also holds tools and instructions |
| Cached read, per call | $0.00010058 | $0.00010828 | Same reason |
| Cost per document, no cache | $0.0010058 (handbook, 1 call) | $0.0022690 | 2 calls, plus the document and output |
| Cost per document, cache warm | $0.00010058 (handbook, 1 call) | $0.0003201 | 2 calls, plus uncached input and output |
| 1,000 documents, no cache | $1.0058 (1,000 handbook sends) | $2.2690 | 1,000 documents = 2,000 calls, plus the document and output |
| 1,000 documents, with cache | $0.1017 | $0.3214 (1 write + 1,000 warm documents) | Same reasons |
| **Savings from caching** | **89.9%** | **81.3%** (12 documents) · **85.9%** (warm) | Caching only discounts the stable prefix. The document text and output pay full price, and over just 12 documents the one cache write is a bigger share of the total. |

**Bottom line.** The token estimate was exact. The estimate's method of price per token, cached reads at a tenth of the price and writes at 1.25×, held up exactly. What it missed was the structure of a real run: 2 calls per document, the extra stable text cached alongside the handbook, and the parts that can't be cached. The real savings (81–86%) land a little below the handbook-only estimate (89.9%). That's because 90% is the most caching can ever save, and only on the tokens that are actually cached.

---

## 3) Projection: 1,000 documents a day for 30 days (30,000 documents)

Based on the measured averages above:

| | Without cache | With cache |
|---|---|---|
| Cost per document | $0.0022690 | $0.0003201 warm, plus $0.0012470 extra for each cache write |
| **Per day (1,000 documents)** | **$2.27** | **$0.32** |
| **30 days (30,000 documents)** | **$68.07** | **$9.64** |
| Input tokens, 30 days | 663,760,000 | 663,760,000 (649,355,160 read from cache, 324,840 written to it) |
| **Saved over 30 days** | — | **$58.43 (85.8%)** |

```
Without cache:  30,000 × $0.0022690                           = $68.07
With cache:     30,000 × $0.0003201 (warm)                    = $9.60
              +     30 × $0.0012470 (one cache write per day) = $0.04
                                                                -----
                                                                $9.64
Saved:          $68.07 − $9.64 = $58.43  →  $58.43 ÷ $68.07 = 85.8%
```

**Assumptions:**
1. **The cache is written once a day.** It lasts at least 30 minutes after it's used. 1,000 documents a day is about 2 a minute over an 8-hour workday, so the cache stays warm all day and gets rewritten once each morning.
2. **Documents look like the practice set:** about 22,125 input and 113 output tokens each, 2 model calls per document, reasoning off.
3. **Prices stay at `data/prices.json` levels.** No retries, failed runs or Portkey fees are included.

**What if the cache goes cold more often?**

| Cache writes | 30-day cost with cache | Savings vs. $68.07 |
|---|---|---|
| 1 per day (base case) | $9.64 | 85.8% |
| 16 per day (cache expires every 30 minutes through an 8-hour day) | $10.20 | 85.0% |
| 48 per day (cache expires every 30 minutes, around the clock) | $11.40 | 83.3% |
| 1 per 12 documents (this test's 12-document average) | $12.72 | 81.3% |

Caching saves at least 81% in every case. Each extra cache write costs only about $0.0012, so how often the cache goes cold barely matters. Over a month, the savings come from the 30,000 handbook reads billed at a tenth of the price.

---

## 4) What surprised me and why it happens

### Surprise 1: the first cached document saved only 31%

The first document in the with-cache setup (p01) cost **$0.0015672**, compared with **$0.0022715** without the cache. That's a saving of only **31.0%**, far below the ~86% every later document saved.

**Why:** the first call has to *write* the handbook into the cache, and writing costs **1.25 times the normal input price** ($0.125 vs. $0.10 per 1M tokens), or 25% more than not caching at all.

| p01 | Without cache | With cache | Change |
|---|---|---|---|
| Call 1 (writes the cache) | $0.0011104 | $0.0013811 | **+24.4%** (10,828 tokens × $0.125/1M = $0.0013535 to write) |
| Call 2 (reads the cache) | $0.0011611 | $0.0001861 | **−84.0%** (10,828 tokens × $0.01/1M = $0.0001083 to read) |
| **Whole document** | **$0.0022715** | **$0.0015672** | **−31.0%** |

So the first call is actually **more** expensive with caching. The first document comes out ahead only because the agent makes a second call, which reads the cache it just wrote at a tenth of the price. If the agent made only one call per document, the first document would cost about 24% more with caching than without.

Caching works like an investment: pay a little extra once to store the handbook, then every call in the next 30 minutes reads it at 90% off. From the second document on, every document saved between **85.5% and 86.2%**. Over a whole day the one write barely matters: it adds about $0.0012 a day to a $0.32 daily bill (0.4%).

### Surprise 2: real savings (about 86%) came in below Problem 2's 89.9%

| Measure | Savings |
|---|---|
| Problem 2 estimate (handbook only, 1,000 calls) | 89.9% |
| This test, documents 2–12 (cache already warm) | **85.9%** |
| 30-day projection (1 cache write a day) | 85.8% |
| This test, all 12 documents (1 write spread over only 12) | 81.3% |

**Why:** caching only discounts the part of the prompt that is the same on every call. Problem 2 priced the handbook alone, and the handbook is 100% cacheable. So the estimate only fell short of the 90% maximum because of one cache write in 1,000 calls: 90% → 89.9%.

A real document also carries parts that can **never** be cached. That's the slippage:

| Per document, without cache | Tokens | Cost | Share of cost | Cached? |
|---|---|---|---|---|
| Stable prefix: handbook, instructions and tools, sent on 2 calls | 21,656 | $0.0021656 | **95.4%** | yes, at 90% off |
| Document text, tool result, "review this document" line | ~469 | $0.0000469 | 2.1% | no, it changes every time |
| Output (the answer) | ~113 | $0.0000565 | 2.5% | no, output is never discounted |
| **Total** | **22,238** | **$0.0022690** | **100%** | |

```
Savings ≈ share of cost that is cacheable × cache discount
        = 95.4% × 90%
        = 85.9%   ← exactly the measured warm savings
```

The never-cached parts are only 2.6% of the tokens (about 582 of 22,238), but 4.6% of the cost. That's because output tokens cost **5×** as much as input tokens ($0.50 vs. $0.10 per 1M), and caching does nothing for them.

**Takeaway:** 90% is the most caching can ever save, and only on tokens that are actually cached. The closer each call is to "all stable prefix," the closer the savings get to 90%. With a 10,000-token handbook and short vendor documents, this agent gets about 86%.

### Also found while testing: the gateway was replaying old answers

An earlier run of this test showed a second document (p02) that "missed" the cache and paid for another write. It turned out Portkey was also caching whole *responses*: identical requests got the old answer back, with the same response ID, and the model never ran. So p01's calls in that run were copies of an earlier spot check. They never reached OpenAI, so nothing was actually cached until p02 wrote it. That's where the "miss" came from.

With replays turned off (`x-portkey-cache-force-refresh: true`) and every response ID checked, this run had **no misses**: 1 write and 23 reads, exactly as designed. **Lesson:** when measuring a model's cost or behavior, make sure every call actually reaches the model. A cached answer looks identical to a real one unless you check the response IDs.
