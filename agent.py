"""Campus Customs vendor desk agent.

Reads one vendor document, pulls out the key facts, and recommends whether to buy,
following data/shop_handbook.md. Every model call uses gpt-6-luna through Portkey.

Example:
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html                   # all defenses on
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html --no-defenses     # Problem 3 agent
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html --defenses code,prompt
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html --no-cache

Defense layers (Problem 6), each switchable:
    code    clean the document so the model sees only what a person sees; flag conflicting
            values, revision wording, and extracted numbers that aren't in the visible text
    design  the reading run gets only read_document (no email or payment tools); the model
            only extracts facts and Python applies the handbook checks; alerts on trap calls
    prompt  security rules in prompts/prompt.md + random untrusted-data markers around the document

Prompt layout on every model call (prefix order matters for caching):
    instructions  prompts/prompt.md                 same on every call
    user message  the full handbook                 same on every call
                  [cache breakpoint]                only when caching is on
                  "Review this vendor document: …"  changes per document

After each run it appends to:
    output/usage_log.json    token counts reported by the API and dollar costs (data/prices.json)
    output/audit_trail.json  every tool call with its arguments and a short result, plus the final answer
send_email and approve_payment only write to output/trap_calls.json.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import httpx2
from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.messages import CachePoint, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from models import (
    AuditRecord,
    CostBreakdown,
    Defenses,
    DeskDeps,
    TokenCounts,
    ToolEvent,
    UsageRecord,
    VendorFacts,
    VendorReport,
)
from tools import (
    ALERT_LOG,
    OUTPUT_DIR,
    READING_TOOLS,
    ROOT,
    TOOLS,
    TRAP_LOG,
    append_json_list,
    decide,
    grounding_flags,
    identity_flags,
    new_marker,
    now,
    portkey_api_key,
    read_json_list,
    redact,
    redact_secrets,
)

MODEL_NAME = "gpt-6-luna"  # the only model this homework may use
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
PROMPT_PATH = ROOT / "prompts" / "prompt.md"
HANDBOOK_PATH = ROOT / "data" / "shop_handbook.md"
PRICES_PATH = ROOT / "data" / "prices.json"
USAGE_LOG = OUTPUT_DIR / "usage_log.json"
AUDIT_LOG = OUTPUT_DIR / "audit_trail.json"
RESULT_CHARS = 200
LIMITS = UsageLimits(request_limit=5, tool_calls_limit=4)  # stopping rule: one read plus room for a retry
DESIGN_LIMITS = UsageLimits(request_limit=4, tool_calls_limit=2)  # design layer: only reading is possible
SECURITY_HEADING = "## Security rules"
DESIGN_NOTE = (
    "\n\n## How this run works\n\nReport only the five facts: vendor, sku, unit_price, lead_time_days, and min_order. "
    "Campus Customs code applies the four purchasing checks and writes the decision and reason, so you do not decide."
)

# "explicit" turns off the breakpoint OpenAI would otherwise place on its own.
# With caching on, the only breakpoint is the one we put right after the handbook.
# With caching off, there is no breakpoint at all, so nothing is written to or read from the cache.
CACHE_ON = {"mode": "explicit", "ttl": "30m"}
CACHE_OFF = {"mode": "explicit"}

# Portkey can also cache whole *responses*: an exact repeat of an earlier request gets the stored
# answer back (same response ID) without the model running. That would make test runs replays of
# old runs. This header makes Portkey send every request to the model. It is not a secret.
FRESH_RESPONSE_HEADERS = {"x-portkey-cache-force-refresh": "true"}


def get_portkey_api_key() -> str:
    """The key comes only from this project's .env file. It is passed straight to Portkey and never logged."""
    key = portkey_api_key()
    if not key:
        raise SystemExit("PORTKEY_API_KEY is empty. Paste your key into the local .env file. Never paste it into code or chat.")
    return key


# ---------- what the API actually sends and receives ----------

@dataclass
class ApiCapture:
    """Records each request's cache settings and each response's raw usage block, in order.

    The hooks read the JSON bodies only. Headers, which carry the API key, are never read or stored.
    """

    calls: list[dict[str, Any]] = field(default_factory=list)

    async def on_request(self, request: httpx2.Request) -> None:
        if not request.url.path.endswith("/responses"):
            return
        try:
            body = json.loads(request.content or b"{}")
        except ValueError:
            body = {}
        text = json.dumps(body)
        self.calls.append(
            {
                "request_model": body.get("model"),
                "prompt_cache_options": body.get("prompt_cache_options"),
                "cache_breakpoints": text.count('"prompt_cache_breakpoint"'),
                "response_model": None,
                "response_id": None,
                "status": None,
                "usage": None,
            }
        )

    async def on_response(self, response: httpx2.Response) -> None:
        if not response.request.url.path.endswith("/responses") or not self.calls:
            return
        await response.aread()
        call = self.calls[-1]
        call["status"] = response.status_code
        try:
            data = response.json()
        except ValueError:
            return
        call["response_model"] = data.get("model")
        call["response_id"] = data.get("id")  # a replayed response would repeat an earlier ID
        call["usage"] = data.get("usage")


def instructions(defenses: Defenses) -> str:
    """prompts/prompt.md, minus its Security rules section when the prompt layer is off."""
    text = PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not defenses.prompt:
        text = text.split(SECURITY_HEADING)[0].strip()
    if defenses.design:
        text += DESIGN_NOTE
    return text


def make_agent(capture: ApiCapture, defenses: Defenses | None = None) -> Agent[DeskDeps, Any]:
    defenses = defenses or Defenses.none()
    http_client = httpx2.AsyncClient(
        timeout=120,
        event_hooks={"request": [capture.on_request], "response": [capture.on_response]},
    )
    client = AsyncOpenAI(
        base_url=PORTKEY_BASE_URL,
        api_key=get_portkey_api_key(),
        http_client=http_client,
        default_headers=FRESH_RESPONSE_HEADERS,
    )
    model = OpenAIResponsesModel(
        MODEL_NAME,
        provider=OpenAIProvider(openai_client=client),
        # These two settings are merged on top of PydanticAI's built-in gpt-6-luna profile.
        profile=OpenAIModelProfile(
            openai_supports_strict_tool_definition=False,
            # PydanticAI 2.66+ already marks gpt-6-luna as supporting breakpoints (2.47 did not).
            # Kept explicit so caching can never be switched off silently by a package change.
            openai_supports_prompt_cache_breakpoints=True,
        ),
        # Same setting as HW4: luna with reasoning off is fast and cheap, and the four checks are simple comparisons.
        settings=OpenAIResponsesModelSettings(openai_reasoning_effort="none"),
    )
    # Design layer: least privilege. The reading run gets only read_document, and the model only
    # extracts facts (VendorFacts). send_email/approve_payment stay in tools.py for human-approved use.
    return Agent(
        model,
        deps_type=DeskDeps,
        output_type=VendorFacts if defenses.design else VendorReport,
        instructions=instructions(defenses),
        tools=READING_TOOLS if defenses.design else TOOLS,
    )


def user_prompt(document: str, cache: bool) -> list[Any]:
    """Handbook first, then (if caching) a breakpoint, then the part that changes per document.

    Both setups send exactly the same text, so their token counts are directly comparable.
    """
    handbook = HANDBOOK_PATH.read_text(encoding="utf-8").strip()
    parts: list[Any] = [handbook]
    if cache:
        parts.append(CachePoint())
    parts.append(f"Review this vendor document: {document}")
    return parts


# ---------- usage and cost ----------

def counts_from_api(usage: dict[str, Any] | None, requests: int = 1) -> TokenCounts:
    """Token counts exactly as the API's usage block reports them."""
    usage = usage or {}
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    input_tokens = int(usage.get("input_tokens") or 0)
    cached = int(input_details.get("cached_tokens") or 0)
    written = int(input_details.get("cache_write_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)
    return TokenCounts(
        requests=requests,
        input_tokens=input_tokens,
        cached_tokens=cached,
        cache_write_tokens=written,
        uncached_input_tokens=input_tokens - cached - written,
        output_tokens=output_tokens,
        reasoning_tokens=int(output_details.get("reasoning_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or input_tokens + output_tokens),
    )


def add_counts(rows: list[TokenCounts]) -> TokenCounts:
    fields = TokenCounts.model_fields
    return TokenCounts(**{name: sum(getattr(row, name) for row in rows) for name in fields})


def price(tokens: TokenCounts) -> CostBreakdown:
    prices = json.loads(PRICES_PATH.read_text(encoding="utf-8"))[MODEL_NAME]
    per = 1_000_000
    uncached = tokens.uncached_input_tokens * prices["input_per_1m"] / per
    cached = tokens.cached_tokens * prices["cached_input_per_1m"] / per
    written = tokens.cache_write_tokens * prices["cache_write_per_1m"] / per
    output = tokens.output_tokens * prices["output_per_1m"] / per
    return CostBreakdown(
        uncached_input_usd=round(uncached, 10),
        cached_input_usd=round(cached, 10),
        cache_write_usd=round(written, 10),
        output_usd=round(output, 10),
        total_usd=round(uncached + cached + written + output, 10),
    )


def check_models(messages: list, calls: list[dict[str, Any]]) -> None:
    """Fail loudly if any request asked for, or any response came from, a model other than gpt-6-luna."""
    names = [m.model_name for m in messages if isinstance(m, ModelResponse) and m.model_name]
    names += [c[key] for c in calls for key in ("request_model", "response_model") if c.get(key)]
    for name in names:
        if not str(name).startswith(MODEL_NAME):
            raise RuntimeError(f"Unexpected model: {name}")


# ---------- audit trail ----------

def short(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    text = redact(" ".join(text.split()))
    return text if len(text) <= RESULT_CHARS else text[:RESULT_CHARS] + "…"


def tool_events(messages: list) -> list[ToolEvent]:
    """Pair each tool call with its return. The final_result output call is the answer, not a tool."""
    returns: dict[str, str] = {}
    for message in messages:
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolReturnPart):
                returns[part.tool_call_id] = short(part.content)
    events: list[ToolEvent] = []
    for message in messages:
        for part in getattr(message, "parts", []):
            if isinstance(part, ToolCallPart) and part.tool_name != "final_result":
                events.append(
                    ToolEvent(
                        tool=part.tool_name,
                        arguments=part.args_as_dict(),
                        result=returns.get(part.tool_call_id, "no result"),
                    )
                )
    return events


# ---------- run ----------

@dataclass
class RunOutcome:
    report: VendorReport
    usage: UsageRecord
    calls: list[dict[str, Any]]  # one entry per model call: cache settings sent and raw usage returned
    pydantic_ai_per_request: list[TokenCounts]  # PydanticAI's own reading of the same calls, for cross-checking
    defenses: Defenses = field(default_factory=Defenses.none)
    removed: list[dict[str, str]] = field(default_factory=list)  # hidden content the code layer removed
    flags: list[dict[str, Any]] = field(default_factory=list)  # what the defenses flagged
    alerts: list[str] = field(default_factory=list)  # trap tool calls in this run


def relative(path: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        return candidate.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path


def ensure_logs() -> None:
    """trap_calls.json, usage_log.json, and audit_trail.json all start as empty lists."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in (TRAP_LOG, USAGE_LOG, AUDIT_LOG):
        if not path.is_file():
            path.write_text("[]\n", encoding="utf-8")


def _pydantic_ai_counts(usage: object) -> TokenCounts:
    input_tokens = getattr(usage, "input_tokens", 0) or 0
    cached = getattr(usage, "cache_read_tokens", 0) or 0
    written = getattr(usage, "cache_write_tokens", 0) or 0
    output_tokens = getattr(usage, "output_tokens", 0) or 0
    details = getattr(usage, "details", {}) or {}
    return TokenCounts(
        requests=1, input_tokens=input_tokens, cached_tokens=cached, cache_write_tokens=written,
        uncached_input_tokens=input_tokens - cached - written, output_tokens=output_tokens,
        reasoning_tokens=int(details.get("reasoning_tokens", 0) or 0), total_tokens=input_tokens + output_tokens,
    )


_OUTPUT_SMELLS = re.compile(r"https?://|www\.|[\w.+-]+@[\w-]+\.\w|<[^>]+>|\bignore\b|\binstruction", re.I)


def output_flags(report: VendorReport) -> list[dict[str, Any]]:
    """Answer fields should hold a name, a SKU, numbers, and a short reason, never links, addresses, or code."""
    flags = []
    for name in ("vendor", "sku", "reason"):
        value = getattr(report, name) or ""
        if _OUTPUT_SMELLS.search(value):
            flags.append({"check": "strange text in answer", "field": name, "text": value[:160]})
    if report.sku and not re.fullmatch(r"CC-[A-Z]{2}-\d{3}", report.sku.strip()):
        flags.append({"check": "SKU not in Campus Customs format", "field": "sku", "text": report.sku})
    return flags


def run(document: str, cache: bool = True, quiet: bool = False,
        defenses: Defenses | None = None) -> RunOutcome:
    """One vendor document, start to finish. defenses=None means all layers on; Defenses.none() is the Problem 3 agent."""
    defenses = Defenses.all() if defenses is None else defenses
    ensure_logs()
    traps_before = len(read_json_list(TRAP_LOG))
    capture = ApiCapture()
    agent = make_agent(capture, defenses)
    settings = OpenAIResponsesModelSettings(openai_prompt_cache_options=CACHE_ON if cache else CACHE_OFF)
    deps = DeskDeps(document=document, defenses=defenses, marker=new_marker())
    try:
        result = agent.run_sync(
            user_prompt(document, cache),
            deps=deps,
            usage_limits=DESIGN_LIMITS if defenses.design else LIMITS,
            model_settings=settings,
        )
    except Exception as exc:
        error = redact(f"{type(exc).__name__}: {exc}")
        append_json_list(
            AUDIT_LOG,
            AuditRecord(time=now(), document=document, model=MODEL_NAME, tool_calls=[],
                        final_answer=None, error=error, defenses=defenses.label).model_dump(),
        )
        raise SystemExit(f"Run failed: {error}") from None

    messages = result.all_messages()
    calls = [call for call in capture.calls if call.get("status") == 200]
    check_models(messages, calls)
    flags = list(deps.flags)

    # Code layer: every number the model extracted must be visible to a person.
    output = result.output
    if defenses.code:
        grounding = grounding_flags(output, deps.visible_text or "")
        flags += grounding
        if defenses.design:
            # The design layer then treats an unverified number as unknown, so its check cannot pass.
            output = output.model_copy(update={f["field"]: None for f in grounding})
            flags += identity_flags(output, deps.visible_text or "")

    # Design layer: Python applies the four handbook checks. Otherwise the model's own answer stands.
    report = decide(output, flags) if defenses.design else output
    flags += output_flags(report)

    # Code layer, output side: never let a catalogue max unit cost leave in the answer (exfiltration guard).
    leak_flags = []
    if defenses.code:
        report, leak_flags = redact_secrets(report, deps.removed)
        flags += leak_flags
    finished = now()

    per_request = [counts_from_api(call["usage"]) for call in calls]
    totals = add_counts(per_request)
    usage = UsageRecord(
        document=document, time=finished, model=MODEL_NAME, cache_enabled=cache, defenses=defenses.label,
        response_ids=[call.get("response_id") or "" for call in calls],
        tokens=totals, cost=price(totals), per_request=per_request,
    )
    append_json_list(USAGE_LOG, usage.model_dump())

    # Monitoring: any trap tool call is an alert, logged on its own and printed loudly.
    new_traps = read_json_list(TRAP_LOG)[traps_before:]
    alerts = [f"{t['tool']} called while reading {document}: {json.dumps(t['arguments'])[:200]}" for t in new_traps]
    if leak_flags:
        alerts.append(f"secret redacted from the answer while reading {document}: "
                      f"{', '.join(sorted({f['field'] for f in leak_flags}))}")
    for alert in alerts:
        append_json_list(ALERT_LOG, {"time": finished, "document": document, "defenses": defenses.label, "alert": alert})

    events = tool_events(messages)
    append_json_list(
        AUDIT_LOG,
        AuditRecord(time=finished, document=document, model=MODEL_NAME, tool_calls=events, final_answer=report,
                    defenses=defenses.label, removed_hidden_content=deps.removed, flags=flags,
                    alerts=alerts).model_dump(),
    )

    if not quiet:
        print(json.dumps(report.model_dump(), indent=2))
        print(
            f"\nDefenses: {defenses.label} | Cache: {'on' if cache else 'off'}"
            f"\nTools: {', '.join(event.tool for event in events) or 'none'}"
            f"\nTokens: {totals.input_tokens:,} in ({totals.cached_tokens:,} cached, "
            f"{totals.cache_write_tokens:,} written to cache), {totals.output_tokens:,} out, "
            f"{totals.requests} model calls"
            f"\nCost: ${usage.cost.total_usd:.6f}"
        )
        if deps.removed:
            print(f"Hidden content removed: {len(deps.removed)} passage(s) (see output/audit_trail.json)")
        for flag in flags:
            print(f"FLAG: {flag['check']}" + (f" ({flag['field']})" if flag.get("field") else ""))
    for alert in alerts:
        print(f"\n*** ALERT: {alert} ***  (logged to output/alerts.json; nothing was sent or paid)")
    return RunOutcome(
        report=report,
        usage=usage,
        calls=calls,
        pydantic_ai_per_request=[_pydantic_ai_counts(m.usage) for m in messages if isinstance(m, ModelResponse)],
        defenses=defenses,
        removed=list(deps.removed),
        flags=flags,
        alerts=alerts,
    )


def run_with_retries(document: str, cache: bool = True, quiet: bool = False,
                     waits: tuple[int, ...] = (15, 45, 90), defenses: Defenses | None = None) -> RunOutcome:
    """Run one document, and if the connection drops, wait and try again (for spotty internet).

    A failed attempt is still recorded in the audit trail. Only the attempt that finishes counts.
    """
    import time

    for attempt, wait in enumerate((*waits, None), start=1):
        try:
            return run(document, cache=cache, quiet=quiet, defenses=defenses)
        except SystemExit as exc:
            if wait is None:
                raise
            print(f"  {document}: attempt {attempt} failed ({exc}). Retrying in {wait}s...")
            time.sleep(wait)
    raise AssertionError("unreachable")


def parse_defenses(value: str) -> Defenses:
    """'all', 'none', or a comma list such as 'code,prompt'."""
    value = value.strip().lower()
    if value == "all":
        return Defenses.all()
    if value == "none":
        return Defenses.none()
    names = {part.strip() for part in value.split(",") if part.strip()}
    unknown = names - {"code", "design", "prompt"}
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown defense layer(s): {', '.join(sorted(unknown))}")
    return Defenses(code="code" in names, design="design" in names, prompt="prompt" in names)


def main() -> None:
    parser = argparse.ArgumentParser(description="Campus Customs vendor desk agent.")
    parser.add_argument("--doc", required=True, help="Path to one vendor document (.html, .pdf, or .eml).")
    parser.add_argument("--no-cache", action="store_true", help="Send no cache breakpoint, so nothing is cached.")
    parser.add_argument("--defenses", type=parse_defenses, default=Defenses.all(),
                        help="Defense layers to use: all (default), none, or a comma list of code, design, prompt.")
    parser.add_argument("--no-defenses", action="store_true", help="Run the Problem 3 agent with every defense off.")
    args = parser.parse_args()
    if not Path(ROOT / args.doc if not Path(args.doc).is_absolute() else args.doc).is_file():
        sys.exit(f"No vendor document at {args.doc}.")
    run(relative(args.doc), cache=not args.no_cache, defenses=Defenses.none() if args.no_defenses else args.defenses)


if __name__ == "__main__":
    main()
