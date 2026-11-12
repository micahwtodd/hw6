"""Problem 4: run all twelve practice documents with and without the prompt cache.

    python cache_test.py

1. Measures the handbook's real token count with two tiny no-cache calls (with and without it).
2. Runs every practice document WITHOUT cache: no breakpoint and implicit caching off.
3. Runs every practice document WITH cache: one breakpoint right after the handbook.
4. Saves every model call to output/cache_test.json and checks that the API's numbers prove each setup.

The without-cache setup runs first, so it can never read anything the with-cache setup wrote.
Runs go one at a time so each call can reuse the cache the previous call wrote.

Run it when no cached agent run has happened in the last 30 minutes. Otherwise the cache is still
warm, and the first with-cache call reads the handbook instead of writing it, so the cost of the
first cache write would not show up in the results.
"""

from __future__ import annotations

import json
import sys

import agent
from models import CacheTestCall
from tools import OUTPUT_DIR, ROOT, now, redact

PRACTICE_DIR = ROOT / "data" / "practice_docs"
KEY_PATH = ROOT / "data" / "practice_key.json"
CACHE_TEST = OUTPUT_DIR / "cache_test.json"
HANDBOOK_CHECK = OUTPUT_DIR / "handbook_token_check.json"
SETUPS = (("without_cache", False), ("with_cache", True))
ANSWER_FIELDS = ("vendor", "sku", "unit_price", "lead_time_days", "min_order", "decision")


def measure_handbook() -> dict:
    """Two no-cache calls that differ only by the handbook. The input_tokens difference is the handbook."""
    from openai import OpenAI

    client = OpenAI(
        base_url=agent.PORTKEY_BASE_URL,
        api_key=agent.get_portkey_api_key(),
        default_headers=agent.FRESH_RESPONSE_HEADERS,  # no replayed responses
    )
    handbook = agent.HANDBOOK_PATH.read_text(encoding="utf-8").strip()
    question = "Reply with the word OK."
    results = {}
    for label, parts in (("with_handbook", [handbook, question]), ("without_handbook", [question])):
        response = client.responses.create(
            model=agent.MODEL_NAME,
            input=[{"role": "user", "content": [{"type": "input_text", "text": text} for text in parts]}],
            prompt_cache_options=agent.CACHE_OFF,
            reasoning={"effort": "none"},
            max_output_tokens=16,
        )
        if not str(response.model).startswith(agent.MODEL_NAME):
            raise RuntimeError(f"Unexpected model: {response.model}")
        results[label] = {"model": response.model, "response_id": response.id, "api_usage": response.usage.model_dump()}
    with_hb = results["with_handbook"]["api_usage"]
    without_hb = results["without_handbook"]["api_usage"]
    for usage in (with_hb, without_hb):
        details = usage.get("input_tokens_details") or {}
        if details.get("cached_tokens") or details.get("cache_write_tokens"):
            raise RuntimeError("The handbook size check touched the cache, so its counts cannot be trusted.")
    record = {
        "time": now(),
        "method": "Two no-cache gpt-6-luna calls, identical except one also sends the handbook "
                  "as its own text block, exactly as the agent sends it. Difference in input_tokens = handbook.",
        "handbook_tokens_measured": with_hb["input_tokens"] - without_hb["input_tokens"],
        "calls": results,
        "costs_usd": {
            label: agent.price(agent.counts_from_api(data["api_usage"])).model_dump()
            for label, data in results.items()
        },
    }
    HANDBOOK_CHECK.write_text(redact(json.dumps(record, indent=2)) + "\n", encoding="utf-8")
    return record


def answer_matches(report, expected: dict) -> list[str]:
    """Fields where the agent's answer differs from data/practice_key.json."""
    wrong = []
    for name in ANSWER_FIELDS:
        got, want = getattr(report, name), expected[name]
        if isinstance(want, float) and got is not None:
            same = abs(float(got) - want) < 0.005
        else:
            same = got == want
        if not same:
            wrong.append(f"{name}: got {got!r}, key {want!r}")
    return wrong


def cache_misses(calls: list[CacheTestCall]) -> list[str]:
    """With-cache calls after the first write that had to write the cache again instead of reading it.

    Prompt caching is best-effort: a call can land on a server that doesn't have the cached prefix yet.
    A miss is not a setup failure (the breakpoint was still sent), but it costs a full cache write.
    """
    with_cache = [c for c in calls if c.setup == "with_cache"]
    return [
        f"with_cache {c.document} call {c.call}: cache miss, wrote {c.tokens.cache_write_tokens:,} tokens again"
        for c in with_cache[1:]
        if c.tokens.cached_tokens == 0
    ]


def verify(calls: list[CacheTestCall], cross_checks: list[str]) -> list[str]:
    """Every check the token counts must pass for each setup to count. Returns the failures."""
    problems = list(cross_checks)
    without = [c for c in calls if c.setup == "without_cache"]
    with_cache = [c for c in calls if c.setup == "with_cache"]
    for c in without:
        if c.tokens.cached_tokens or c.tokens.cache_write_tokens:
            problems.append(f"without_cache {c.document} call {c.call}: cached={c.tokens.cached_tokens}, "
                            f"written={c.tokens.cache_write_tokens} (must both be 0)")
        if c.cache_breakpoints:
            problems.append(f"without_cache {c.document} call {c.call}: sent a cache breakpoint")
    for c in with_cache:
        if c.cache_breakpoints != 1:
            problems.append(f"with_cache {c.document} call {c.call}: sent {c.cache_breakpoints} breakpoints (expected 1)")
    if with_cache and with_cache[0].tokens.cache_write_tokens == 0 and with_cache[0].tokens.cached_tokens == 0:
        problems.append("with_cache: the first call neither wrote nor read the cache")
    hits = [c for c in with_cache[1:] if c.tokens.cached_tokens]
    if with_cache and len(hits) < (len(with_cache) - 1) / 2:
        problems.append(f"with_cache: only {len(hits)} of {len(with_cache) - 1} later calls read the cache")
    ids = [c.response_id for c in calls]
    if None in ids or len(set(ids)) != len(ids):
        problems.append("response IDs are missing or repeated, so some calls may be replays, not real model runs")
    for c in calls:
        if c.tokens.uncached_input_tokens < 0:
            problems.append(f"{c.setup} {c.document} call {c.call}: negative uncached input")
        if c.tokens.total_tokens != c.tokens.input_tokens + c.tokens.output_tokens:
            problems.append(f"{c.setup} {c.document} call {c.call}: total_tokens is not input + output")
    return problems


def main() -> None:
    documents = sorted(p.relative_to(ROOT).as_posix() for p in PRACTICE_DIR.iterdir() if p.is_file())
    if len(documents) != 12:
        sys.exit(f"Expected 12 practice documents, found {len(documents)}.")
    key = {row["file"]: row for row in json.loads(KEY_PATH.read_text(encoding="utf-8"))}

    print("Measuring the handbook with two no-cache calls...")
    handbook = measure_handbook()
    print(f"  handbook = {handbook['handbook_tokens_measured']:,} tokens (gpt-6-luna, from the API)\n")

    calls: list[CacheTestCall] = []
    cross_checks: list[str] = []
    answers: dict[str, list[str]] = {}
    for setup, cache in SETUPS:
        print(f"== {setup} ==")
        for document in documents:
            # Problem 4 measured the Problem 3 agent, so the Problem 6 defenses stay off here.
            outcome = agent.run_with_retries(document, cache=cache, quiet=True, defenses=agent.Defenses.none())
            if len(outcome.calls) != len(outcome.pydantic_ai_per_request):
                cross_checks.append(f"{setup} {document}: captured {len(outcome.calls)} API calls, "
                                    f"PydanticAI saw {len(outcome.pydantic_ai_per_request)}")
            for number, (raw, theirs) in enumerate(zip(outcome.calls, outcome.pydantic_ai_per_request), start=1):
                tokens = agent.counts_from_api(raw["usage"])
                for name in ("input_tokens", "cached_tokens", "cache_write_tokens", "output_tokens"):
                    if getattr(tokens, name) != getattr(theirs, name):
                        cross_checks.append(f"{setup} {document} call {number}: {name} raw "
                                            f"{getattr(tokens, name)} vs PydanticAI {getattr(theirs, name)}")
                calls.append(
                    CacheTestCall(
                        setup=setup, document=document, call=number, time=outcome.usage.time,
                        model=raw["response_model"], response_id=raw.get("response_id"),
                        prompt_cache_options=raw["prompt_cache_options"],
                        cache_breakpoints=raw["cache_breakpoints"], api_usage=raw["usage"],
                        tokens=tokens, cost=agent.price(tokens),
                    )
                )
            wrong = answer_matches(outcome.report, key[document.rsplit("/", 1)[-1]])
            answers[f"{setup} {document}"] = wrong
            t = outcome.usage.tokens
            print(f"  {document.rsplit('/', 1)[-1]:28} in {t.input_tokens:>6,}  cached {t.cached_tokens:>6,}  "
                  f"written {t.cache_write_tokens:>6,}  out {t.output_tokens:>4}  ${outcome.usage.cost.total_usd:.6f}  "
                  f"{outcome.report.decision:17} {'ok' if not wrong else 'DIFFERS: ' + '; '.join(wrong)}")
        print()

    CACHE_TEST.write_text(
        redact(json.dumps([c.model_dump() for c in calls], indent=2)) + "\n", encoding="utf-8"
    )
    print(f"Saved {len(calls)} model calls to {CACHE_TEST.relative_to(ROOT).as_posix()}\n")

    problems = verify(calls, cross_checks)
    print("CHECKS:", "all passed" if not problems else f"{len(problems)} problem(s)")
    for problem in problems:
        print("  -", problem)
    misses = cache_misses(calls)
    print(f"CACHE MISSES (best-effort caching, not a setup failure): {len(misses) or 'none'}")
    for miss in misses:
        print("  -", miss)
    wrong_runs = {run: diff for run, diff in answers.items() if diff}
    print(f"ANSWERS vs practice_key.json: {24 - len(wrong_runs)}/24 runs match on every field")


if __name__ == "__main__":
    main()
