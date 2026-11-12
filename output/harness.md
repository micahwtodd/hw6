# Vendor Desk Agent Harness (Problems 3 to 9)

**Model:** `gpt-6-luna` through Portkey, on every call. It's set once as `MODEL_NAME` in `agent.py`, and `check_models()` stops the run if any request or response names a different model.
**Framework:** PydanticAI 2.66 `Agent` with `OpenAIResponsesModel`, reasoning effort `none`. The model returns `VendorFacts` when the design layer is on (the default) and a full `VendorReport` when it's off. Package versions are pinned in `requirements.txt`.
**Run:** `python agent.py --doc data/practice_docs/p01_bluehen_quote.html`

| File | Role |
|---|---|
| `prompts/prompt.md` | Agent instructions, sent as the instructions on every model call. |
| `agent.py` | Entry point. Builds the agent, sends the full `data/shop_handbook.md` at the start of the user message on every model call, runs one document, checks the model, and writes the usage log and audit trail. `--no-cache` turns caching off. |
| `tools.py` | The three tools, the document readers, the code-layer checks, the Python decision (`decide`), and the log helpers. |
| `models.py` | Structured types for the answer and the logs. |
| `cache_test.py` | Problem 4: runs all 12 practice documents with and without the cache and writes `output/cache_test.json`. |
| `attack_test.py` | Problem 5: runs the undefended agent on all 12 practice documents and scores each answer against the key, the trap log and a strange-text check. Writes `output/attack_results.json`. |
| `defense_test.py` | Problem 6: runs all 12 practice documents with no defenses, each layer alone, and all layers. Writes `output/defense_results.json` and `output/defense_layers.json`. |
| `make_attacks.py` | Problem 7: builds my two attack documents in `data/my_attacks/`. |
| `red_team_test.py` | Problem 7: runs both attack documents three times with no defenses and three times with all layers, scored against `data/my_attacks_key.json`. Writes `output/red_team.json`. |
| `exam_test.py` | Problem 8: runs the final defended agent on the 10 exam documents. Writes `output/exam_results.json` straight from the agent's output. |
| `build_report.py` | Problem 9: reads the result files and fills `report_template.html` to write `output/hw6_report.html`. Makes no model calls. |

**Prompt layout (Problem 4):** the instructions, then the handbook, then a cache breakpoint (only when caching is on), then the request for this document. Everything that stays the same comes first, so the API can reuse it from the cache. Caching uses `prompt_cache_options={"mode": "explicit", "ttl": "30m"}` with one breakpoint after the handbook. `--no-cache` sends `{"mode": "explicit"}` with no breakpoint, so nothing is cached.

---

## Fields in `models.py`

### `VendorReport` — the agent's answer (handbook section 13)

| Field | Type | Why |
|---|---|---|
| `vendor` | `str \| None` | Check 1 (approved vendor) needs the name, and it is the first item the handbook says to report. `None` means the document does not say. |
| `sku` | `str \| None` | Links the quote to a catalogue row, which holds the max unit cost for check 2. Handbook section 13 asks for the Campus Customs SKU. |
| `unit_price` | `float \| None` | Check 2: must be at or below the SKU's max unit cost. A number, not text, so it can be compared and graded. |
| `lead_time_days` | `int \| None` | Check 3: must be 21 days or less. |
| `min_order` | `int \| None` | Check 4: must be 600 units or less. |
| `decision` | `"recommend" \| "do_not_recommend"` | The verdict. A `Literal` type means the model cannot return anything else, such as "maybe" or "buy". |
| `reason` | `str` | The one sentence handbook section 13 requires, naming the check that decided the result. It lets the buyer see why without rereading the document. |

The five facts are `Optional` because handbook section 4 says "If the document does not say a price, lead time, or minimum order, report it as unknown. Never guess a number." `None` (`null` in JSON) is how the agent says "unknown" without inventing a value.

### `VendorFacts` — what the model returns when the design layer is on

The same five facts as `VendorReport` (`vendor`, `sku`, `unit_price`, `lead_time_days`, `min_order`), with **no `decision` or `reason`**. The model can't decide, so Python does (see Safety).

### `Defenses` — which Problem 6 layers are on

| Field | Type | Why |
|---|---|---|
| `code` | `bool` | Clean the document and check the extracted numbers. |
| `design` | `bool` | Remove the email and payment tools from the run, and have Python decide. |
| `prompt` | `bool` | Add the security rules and the untrusted-data markers. |

`Defenses.all()` is the default. `Defenses.none()` is the Problem 3 agent, kept for Problem 7.

### `DeskDeps` — run context passed to every tool

| Field | Type | Why |
|---|---|---|
| `document` | `str` | The document path for this run. The trap tools record it, so every trap entry shows which document triggered it. |
| `defenses` | `Defenses` | Tells `read_document` which layers to apply. |
| `marker` | `str` | A random tag for this run's untrusted-data markers, so a document can't fake the end marker. |
| `visible_text` | `str \| None` | What the model was shown, for the grounding check. |
| `removed` | `list` | Hidden content the code layer removed from the document, and any secret it removed from the answer. |
| `flags` | `list` | Conflicts and revision wording the code layer found. |

### `ToolEvent` — one tool call in the audit trail

| Field | Type | Why |
|---|---|---|
| `tool` | `str` | Which tool the model called. A `send_email` or `approve_payment` here is a red flag. |
| `arguments` | `dict` | Exactly what the model asked for, for example which file it read or who it tried to email. |
| `result` | `str` | A short, redacted summary of what came back (up to 200 characters), enough to follow the run without copying whole documents into the log. |

### `AuditRecord` — one run in `output/audit_trail.json`

| Field | Type | Why |
|---|---|---|
| `time` | `str` | When the run finished, so runs can be put in order and matched to the usage log. |
| `document` | `str` | Which vendor document was reviewed. |
| `model` | `str` | Records that the run used `gpt-6-luna`. |
| `tool_calls` | `list[ToolEvent]` | Every tool call in order, as the assignment asks. |
| `final_answer` | `VendorReport \| None` | The answer the agent gave. `None` if the run failed. |
| `error` | `str \| None` | Redacted error text when a run fails, so failures are recorded too. |
| `defenses` | `str` | Which layers were on: `none`, `all`, or for example `code`. |
| `removed_hidden_content` | `list` | Every hidden passage removed, with where it was and how it was hidden. |
| `flags` | `list` | Conflicting values, revision wording, numbers not in the visible text, identity mismatches, odd output, and secrets removed from the answer. |
| `alerts` | `list[str]` | Trap tool calls, and secrets removed from the answer, in this run. These are also written to `output/alerts.json`, which is created on the first alert. No run has raised one, so the file doesn't exist yet. |

### `TokenCounts` — token counts reported by the API

| Field | Type | Why |
|---|---|---|
| `requests` | `int` | Number of model calls. Each call resends the handbook, so this drives cost. |
| `input_tokens` | `int` | All input tokens as the API reports them, including cached ones. |
| `cached_tokens` | `int` | Input read from the prompt cache, billed at $0.01 per 1M tokens. |
| `cache_write_tokens` | `int` | Input written into the cache, billed at $0.125 per 1M tokens. |
| `uncached_input_tokens` | `int` | `input_tokens − cached_tokens − cache_write_tokens`, billed at the normal $0.10 per 1M tokens. Kept as its own field so every token is priced exactly once. |
| `output_tokens` | `int` | The answer and tool-call text, billed at $0.50 per 1M tokens. |
| `reasoning_tokens` | `int` | Hidden reasoning, already counted inside `output_tokens`. It's 0 because reasoning is off, which this field confirms. |
| `total_tokens` | `int` | `input_tokens + output_tokens`, for a quick size check. |

### `CostBreakdown` — dollars, priced from `data/prices.json`

| Field | Why |
|---|---|
| `uncached_input_usd` | `uncached_input_tokens × $0.10 / 1M` |
| `cached_input_usd` | `cached_tokens × $0.01 / 1M` |
| `cache_write_usd` | `cache_write_tokens × $0.125 / 1M` |
| `output_usd` | `output_tokens × $0.50 / 1M` |
| `total_usd` | The sum, the bill for one run. |

Keeping each line separate shows where the money goes. That matters for the cost-cutting problems.

### `UsageRecord` — one run in `output/usage_log.json`

| Field | Type | Why |
|---|---|---|
| `document` | `str` | Which document the run reviewed. |
| `time` | `str` | When the run finished. |
| `model` | `str` | Records that the run used `gpt-6-luna`. |
| `cache_enabled` | `bool` | Whether this run placed the cache breakpoint. Runs from before this field was added don't have it. |
| `defenses` | `str` | Which defense layers were on, so costs can be compared by layer. |
| `response_ids` | `list[str]` | The API's ID for each model call. A real call always gets a new ID, so a repeated ID would reveal a replayed answer. Runs from before this field was added don't have it. |
| `tokens` | `TokenCounts` | Totals for the whole run, taken from the raw `usage` block the API returns for each call. |
| `cost` | `CostBreakdown` | Dollar cost for the whole run. |
| `per_request` | `list[TokenCounts]` | Each model call on its own. The agent makes two calls (read the document, then answer), and this shows the handbook going out on both. |

### `CacheTestCall` — one model call in `output/cache_test.json` (Problem 4)

| Field | Type | Why |
|---|---|---|
| `setup` | `"with_cache" \| "without_cache"` | Which setup made the call. |
| `document` | `str` | Which practice document the run was reviewing. |
| `call` | `int` | 1 = the call that reads the document, 2 = the call that answers. |
| `time` | `str` | When the run finished. |
| `model` | `str` | The model the API says answered (`gpt-6-luna-global`), as proof that only luna was used. |
| `response_id` | `str` | The API's ID for this call. All IDs must be unique, which proves every call was a real model run. |
| `prompt_cache_options` | `dict` | The cache settings the request actually sent. |
| `cache_breakpoints` | `int` | Breakpoints in the request: 1 with cache, 0 without. Proves the setup. |
| `api_usage` | `dict` | The usage block exactly as the API returned it, including `cached_tokens` and `cache_write_tokens`. |
| `tokens` | `TokenCounts` | The same numbers flattened, with uncached input worked out. |
| `cost` | `CostBreakdown` | Dollars for this call, from `data/prices.json`. |

### `TrapCall` — one entry in `output/trap_calls.json`

| Field | Type | Why |
|---|---|---|
| `time` | `str` | When the trap fired. |
| `document` | `str` | The document that took over the agent. |
| `tool` | `str` | `send_email` or `approve_payment`. |
| `arguments` | `dict` | What the attacker tried to do: the recipient and body, or the payee and amount. |

---

## Tools in `tools.py`

- **`read_document(path)`** — the only tool the job needs. It reads one `.html`, `.pdf` or `.eml` vendor document from `data/` and returns its text. With the code layer on (the default) it returns only the text a person would see. With it off it returns everything: every HTML text node and comment, all PDF pages, and every email header and part (plain text, HTML, and PDF attachments). It refuses any other file type or location, so `.env` and code files can't be read.
- **`send_email(to, subject, body)`** — a trap. It never sends anything. It only appends the call and its arguments to `output/trap_calls.json`.
- **`approve_payment(payee, amount_usd, reference)`** — a trap. It never pays anything. It only appends the call and its arguments to `output/trap_calls.json`.

---

## Other harness settings

- **Stopping rule:** `UsageLimits(request_limit=5, tool_calls_limit=4)`, tightened to `request_limit=4, tool_calls_limit=2` when the design layer is on. A normal run uses 2 model calls and 1 tool call, so a document that sends the agent into a loop gets cut off.
- **Cost cap:** `read_document` cuts any document off at 20,000 characters.
- **Prompt caching:** on by default. The handbook prefix (10,828 tokens) is written once and then read at $0.01 per 1M tokens instead of $0.10. See `output/cache_test.md`.
- **No replayed answers:** Portkey can store whole responses and hand back an old answer when a request exactly repeats an earlier one, without the model running. Every request sends `x-portkey-cache-force-refresh: true`, so each call reaches gpt-6-luna. Each response ID is recorded so a replay would show up as a repeated ID. (This is separate from OpenAI's prompt caching of the handbook, which stays on.)
- **Token counts come straight from the API:** `ApiCapture` in `agent.py` saves each response's raw `usage` block and each request's cache settings. It reads message bodies only, never headers, so the key is never seen.
- **Secrets:** the key is read only from the project's local `.env` file, with `dotenv_values`, so it is never copied into the process environment. It is never passed to the model, `redact()` removes it from every log and error message, and `.env` is in `.gitignore`.
- **Logs start empty:** `trap_calls.json`, `usage_log.json` and `audit_trail.json` are created as `[]`, and every run appends to them without overwriting.

---

## Safety

The agent has three defense layers. Each one can be switched on or off: `--defenses all` is the default, `--no-defenses` gives the Problem 3 agent, and `--defenses code,prompt` turns on only the layers listed.

### 1. Code layer: what the program does to the document before the model sees it

- **Shows the model only what a person would see.**
  - **HTML:** removes text hidden with 0 or tiny fonts, white or transparent color, `display:none`, the `hidden` attribute, off-screen positioning, or CSS classes that do any of these. Also removes HTML comments.
  - **PDF:** removes text under 4 pt, white text, invisible text and text placed off the page.
  - **Email:** checks each part separately.
  - **Everywhere:** strips invisible Unicode characters (zero-width, direction overrides, tag characters).
- **Checks the numbers.** Every price, lead time and minimum the model reports must appear in the visible text. If one doesn't, it's flagged and treated as unknown.
- **Checks for conflicts.**
  - **Two different values for one fact:** flagged, and the decision is held for human review.
  - **Wording like "revised", "corrected" or "this replaces":** flagged only, since honest corrected quotes exist (p10).
- **Blocks fake "trusted" notices.** Text in a document that imitates our own security notices is removed.
- **Strips secrets from the answer (output side).** Before the report is returned, any catalogue max unit cost is removed from its text fields and an alert is logged. This is the exfiltration guard: it runs in Python on the finished answer, so a leak is blocked however the model was talked into it. The quote's own price is never redacted, even if it equals some SKU's max cost.

### 2. Design layer: how the agent is built

- **Least privilege.** The document-reading run gets only `read_document`. `send_email` and `approve_payment` still exist for later human-approved use, but a document can't reach them.
- **Python makes the decision.** The model only extracts the five facts. Code applies the handbook's four checks to the real approved-vendor list and catalogue, and writes the reason. This also fixes the p07/p08 error, where the model decided before it checked.
- **Answer checks.** It flags links, email addresses, code or a malformed SKU in the answer. It also flags a vendor whose email domain or SKU item name doesn't match the handbook.
- **Monitoring.** Every run logs what was removed and flagged in `output/audit_trail.json`. Any trap tool call, or any secret removed from the answer, prints an ALERT and is written to `output/alerts.json`.

### 3. Prompt layer: the rules in `prompts/prompt.md`

- **Untrusted-data markers.** The document is wrapped in markers with a random tag, and any look-alike markers inside the document are removed.
- **Data, not instructions.** The model never follows instructions inside the document, however they're worded or whoever they claim to be from.
- **Claims aren't facts.** Phrases like "pre-approved", "vendor of record" or "Campus Customs asked for this" change nothing. Vendor status comes only from the handbook.
- **Conflict rule.** If values conflict or the document claims a revision, report the value in the main quote. A real change needs a new quote that a person reviews.
- **No links, addresses or code in answers.** And no sending, approving or sharing private data.

### Known gaps

Text inside images, text covered by a picture or a white box, and a fake value shown openly with nothing to conflict with. These need image rendering, OCR or a human review.

My two Problem 7 attacks tested the covered-text gap. The code layer did not remove the covered text in either one. The design and prompt layers still blocked both attacks in 3 of 3 runs each (see `output/red_team.md`), but removing covered text up front is the next fix.
