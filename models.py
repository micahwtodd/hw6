"""Structured types for the Campus Customs vendor desk agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

Decision = Literal["recommend", "do_not_recommend"]


@dataclass(frozen=True)
class Defenses:
    """Which Problem 6 defense layers are switched on. Defenses.none() is the Problem 3 agent."""

    code: bool = True    # clean the document before the model sees it, then check the extracted numbers
    design: bool = True  # no email/payment tools in the reading run; Python makes the decision
    prompt: bool = True  # security rules in prompts/prompt.md + untrusted-data markers around the document

    @classmethod
    def all(cls) -> "Defenses":
        return cls(True, True, True)

    @classmethod
    def none(cls) -> "Defenses":
        return cls(False, False, False)

    @property
    def label(self) -> str:
        on = [name for name in ("code", "design", "prompt") if getattr(self, name)]
        return "all" if len(on) == 3 else "none" if not on else "+".join(on)


@dataclass
class DeskDeps:
    """Run context passed to every tool."""

    document: str  # path of the one vendor document for this run, relative to the homework folder
    defenses: Defenses = field(default_factory=Defenses.none)
    marker: str = ""  # random per-run tag for the untrusted-data markers (prompt layer)
    visible_text: str | None = None  # what read_document returned, for the grounding check
    removed: list[dict[str, str]] = field(default_factory=list)  # hidden content the code layer removed
    flags: list[dict[str, Any]] = field(default_factory=list)  # problems the code layer found


class VendorReport(BaseModel):
    """The agent's final answer for one vendor document (handbook section 13)."""

    vendor: str | None = Field(
        description="Vendor name exactly as the document gives it. null if the document does not say."
    )
    sku: str | None = Field(
        description="Campus Customs SKU, such as CC-HD-006. null if it cannot be found in the document or matched to the catalogue."
    )
    unit_price: float | None = Field(
        description="Quoted price per unit in US dollars, as a number. null if the document does not say."
    )
    lead_time_days: int | None = Field(
        description="Lead time in days as the document states it. null if the document does not say."
    )
    min_order: int | None = Field(
        description="Minimum order in units. null if the document does not say."
    )
    decision: Decision = Field(
        description="recommend only if all four handbook purchasing checks pass, otherwise do_not_recommend."
    )
    reason: str = Field(
        description="One sentence that names the purchasing check that decided the result."
    )


class VendorFacts(BaseModel):
    """Design layer: the model only extracts facts. Python applies the handbook checks and writes the decision."""

    vendor: str | None = Field(
        description="Vendor name exactly as the document gives it. null if the document does not say."
    )
    sku: str | None = Field(
        description="Campus Customs SKU, such as CC-HD-006. null if it cannot be found in the document or matched to the catalogue."
    )
    unit_price: float | None = Field(
        description="Quoted price per unit in US dollars, as a number. null if the document does not say."
    )
    lead_time_days: int | None = Field(
        description="Lead time in days as the document states it. null if the document does not say."
    )
    min_order: int | None = Field(
        description="Minimum order in units. null if the document does not say."
    )


class ToolEvent(BaseModel):
    """One tool call in a run, written to output/audit_trail.json."""

    tool: str = Field(description="Tool name the model called.")
    arguments: dict[str, Any] = Field(description="Arguments the model passed to the tool.")
    result: str = Field(description="Short, redacted summary of what the tool returned.")


class AuditRecord(BaseModel):
    """One agent run, appended to output/audit_trail.json."""

    time: str = Field(description="When the run finished (local time, ISO 8601).")
    document: str = Field(description="Vendor document the agent was given.")
    model: str = Field(description="Model used for every call in the run.")
    tool_calls: list[ToolEvent] = Field(description="Every tool call in order.")
    final_answer: VendorReport | None = Field(description="The agent's answer. null if the run failed.")
    error: str | None = Field(default=None, description="Redacted error text if the run failed.")
    defenses: str = Field(default="none", description="Defense layers on for this run: none, all, or e.g. code+prompt.")
    removed_hidden_content: list[dict[str, str]] = Field(
        default_factory=list, description="Hidden text the code layer removed before the model saw the document."
    )
    flags: list[dict[str, Any]] = Field(
        default_factory=list, description="Problems found: conflicts, revision wording, unverified numbers, odd output."
    )
    alerts: list[str] = Field(default_factory=list, description="Trap tool calls, and secrets removed from the answer, in this run (should always be empty).")


class TokenCounts(BaseModel):
    """Token counts reported by the API, summed or for one request."""

    requests: int = Field(description="Number of model calls.")
    input_tokens: int = Field(description="All input tokens, including cached and cache-write tokens.")
    cached_tokens: int = Field(description="Input tokens read from the prompt cache.")
    cache_write_tokens: int = Field(description="Input tokens written to the prompt cache.")
    uncached_input_tokens: int = Field(description="input_tokens - cached_tokens - cache_write_tokens.")
    output_tokens: int = Field(description="All output tokens, including reasoning tokens.")
    reasoning_tokens: int = Field(description="Hidden reasoning tokens, already counted in output_tokens.")
    total_tokens: int = Field(description="input_tokens + output_tokens.")


class CostBreakdown(BaseModel):
    """Dollar cost of a run, priced from data/prices.json."""

    uncached_input_usd: float
    cached_input_usd: float
    cache_write_usd: float
    output_usd: float
    total_usd: float


class UsageRecord(BaseModel):
    """One agent run, appended to output/usage_log.json."""

    document: str = Field(description="Vendor document the agent was given.")
    time: str = Field(description="When the run finished (local time, ISO 8601).")
    model: str = Field(description="Model used for every call in the run.")
    cache_enabled: bool = Field(description="True when a cache breakpoint was placed after the handbook.")
    defenses: str = Field(default="none", description="Defense layers on for this run: none, all, or e.g. code+prompt.")
    response_ids: list[str] = Field(
        default_factory=list,
        description="API response ID of each model call. Every real call gets a new ID; a replay repeats an old one.",
    )
    tokens: TokenCounts = Field(description="Token counts for the whole run.")
    cost: CostBreakdown = Field(description="Dollar cost for the whole run.")
    per_request: list[TokenCounts] = Field(description="Token counts for each model call in the run.")


class CacheTestCall(BaseModel):
    """One model call in the Problem 4 cache test, written to output/cache_test.json."""

    setup: Literal["with_cache", "without_cache"] = Field(description="Which setup made the call.")
    document: str = Field(description="Vendor document the run was reviewing.")
    call: int = Field(description="Position of this call in its run: 1 reads the document, 2 answers.")
    time: str = Field(description="When the run finished (local time, ISO 8601).")
    model: str = Field(description="Model name the API says answered the call.")
    response_id: str | None = Field(default=None, description="API response ID. Unique per real model call.")
    prompt_cache_options: dict[str, Any] | None = Field(description="Cache settings the request sent.")
    cache_breakpoints: int = Field(description="Cache breakpoints in the request: 1 with cache, 0 without.")
    api_usage: dict[str, Any] = Field(description="The usage block exactly as the API returned it.")
    tokens: TokenCounts = Field(description="The same counts, flattened, with uncached input worked out.")
    cost: CostBreakdown = Field(description="Dollars for this call, from data/prices.json.")


class TrapCall(BaseModel):
    """A call to send_email or approve_payment, appended to output/trap_calls.json."""

    time: str = Field(description="When the trap tool was called.")
    document: str = Field(description="Vendor document the agent was reading when it was called.")
    tool: str = Field(description="send_email or approve_payment.")
    arguments: dict[str, Any] = Field(description="Exactly what the model asked the tool to do.")
