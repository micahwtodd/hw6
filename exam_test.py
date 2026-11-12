"""Problem 8: run the final defended agent (all three layers) on every exam document.

    python exam_test.py

Writes output/exam_results.json straight from the agent's output - one entry per file in
data/exam_docs/, with no hand edits. Token counts and cost come from the API usage block.
"""

from __future__ import annotations

import json
import sys

import agent
from tools import OUTPUT_DIR, ROOT, TRAP_LOG, read_json_list, redact

EXAM_DIR = ROOT / "data" / "exam_docs"
RESULTS = OUTPUT_DIR / "exam_results.json"


def main() -> None:
    documents = sorted(p for p in EXAM_DIR.iterdir() if p.is_file())
    if len(documents) != 10:
        sys.exit(f"Expected 10 exam documents, found {len(documents)}.")
    earlier_ids = {rid for row in read_json_list(agent.USAGE_LOG) for rid in row.get("response_ids", [])}

    entries, response_ids = [], []
    for path in documents:
        before = len(read_json_list(TRAP_LOG))
        outcome = agent.run_with_retries(path.relative_to(ROOT).as_posix(), quiet=True,
                                         defenses=agent.Defenses.all())
        traps = read_json_list(TRAP_LOG)[before:]
        report, usage = outcome.report, outcome.usage
        entries.append({
            "file": path.name,
            "vendor": report.vendor,
            "sku": report.sku,
            "unit_price": report.unit_price,
            "lead_time_days": report.lead_time_days,
            "min_order": report.min_order,
            "decision": report.decision,
            "reason": report.reason,
            "trap_tool_called": bool(traps),
            "input_tokens": usage.tokens.input_tokens,
            "cached_tokens": usage.tokens.cached_tokens,
            "output_tokens": usage.tokens.output_tokens,
            "cost_usd": usage.cost.total_usd,
        })
        response_ids += usage.response_ids
        flags = sorted({f["check"] for f in outcome.flags})
        print(f"  {path.name:18} {report.decision:17} traps={bool(traps)}"
              + (f" | flags: {', '.join(flags)}" if flags else ""))

    RESULTS.write_text(redact(json.dumps(entries, indent=2)) + "\n", encoding="utf-8")
    fresh = bool(response_ids) and "" not in response_ids and len(set(response_ids)) == len(response_ids) \
        and not (set(response_ids) & earlier_ids)
    print(f"\nfresh model calls: {fresh} | trap calls: {sum(e['trap_tool_called'] for e in entries)} | "
          f"total cost: ${sum(e['cost_usd'] for e in entries):.6f}")
    print(f"Saved {RESULTS.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
