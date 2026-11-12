"""Problem 6: run all 12 practice documents with each defense layer alone, all layers, and none.

    python defense_test.py

Configurations: none (Problem 3 agent), code only, design only, prompt only, all three.
Each configuration first runs one warm-up document (not scored) so its prompt prefix is
already cached, then runs the 12 practice documents one at a time.

Writes:
  output/defense_results.json  all layers on: same structure as attack_results.json, plus
                               tokens, dollars, flags, and removed hidden content per document
  output/defense_layers.json   every configuration, for the before/after table, what each
                               layer catches, and what each layer costs
"""

from __future__ import annotations

import json
import sys

import agent
from attack_test import KEY_PATH, PRACTICE_DIR, all_fresh, score_document, status_line, summarize
from models import Defenses
from tools import OUTPUT_DIR, ROOT, TRAP_LOG, now, read_json_list, redact

RESULTS = OUTPUT_DIR / "defense_results.json"
LAYERS = OUTPUT_DIR / "defense_layers.json"
WARM_UP = "data/practice_docs/p01_bluehen_quote.html"
CONFIGS = {
    "none": Defenses.none(),
    "code": Defenses(code=True, design=False, prompt=False),
    "design": Defenses(code=False, design=True, prompt=False),
    "prompt": Defenses(code=False, design=False, prompt=True),
    "all": Defenses.all(),
}


def run_config(name: str, defenses: Defenses, documents, key) -> list[dict]:
    print(f"\n== {name} ==")
    agent.run_with_retries(WARM_UP, quiet=True, defenses=defenses)  # warm the cache for this prompt prefix
    rows = []
    for path in documents:
        document = path.relative_to(ROOT).as_posix()
        before = len(read_json_list(TRAP_LOG))
        outcome = agent.run_with_retries(document, quiet=True, defenses=defenses)
        row = score_document(path, outcome, key[path.name], read_json_list(TRAP_LOG)[before:])
        t = outcome.usage.tokens
        row.update(
            defenses=defenses.label,
            tokens={"input": t.input_tokens, "cached": t.cached_tokens, "cache_write": t.cache_write_tokens,
                    "uncached_input": t.uncached_input_tokens, "output": t.output_tokens, "total": t.total_tokens,
                    "model_calls": t.requests},
            cost=outcome.usage.cost.model_dump(),
            flags=outcome.flags,
            removed_hidden_content=outcome.removed,
            alerts=outcome.alerts,
        )
        rows.append(row)
        print(status_line(row) + (f" | flags: {', '.join(sorted({f['check'] for f in outcome.flags}))}" if outcome.flags else ""))
    return rows


def per_doc_averages(rows: list[dict]) -> dict:
    n = len(rows)
    avg = lambda f: round(sum(f(r) for r in rows) / n, 2)
    return {
        "input_tokens": avg(lambda r: r["tokens"]["input"]),
        "cached_tokens": avg(lambda r: r["tokens"]["cached"]),
        "output_tokens": avg(lambda r: r["tokens"]["output"]),
        "model_calls": avg(lambda r: r["tokens"]["model_calls"]),
        "cost_usd": round(sum(r["cost"]["total_usd"] for r in rows) / n, 10),
    }


def main() -> None:
    documents = sorted(p for p in PRACTICE_DIR.iterdir() if p.is_file())
    if len(documents) != 12:
        sys.exit(f"Expected 12 practice documents, found {len(documents)}.")
    key = {row["file"]: row for row in json.loads(KEY_PATH.read_text(encoding="utf-8"))}
    usage_before = len(read_json_list(agent.USAGE_LOG))
    traps_at_start = len(read_json_list(TRAP_LOG))

    results = {name: run_config(name, defenses, documents, key) for name, defenses in CONFIGS.items()}

    all_rows = [r for rows in results.values() for r in rows]
    fresh = all_fresh(all_rows, read_json_list(agent.USAGE_LOG)[:usage_before])
    base = per_doc_averages(results["none"])
    layers = {}
    for name, rows in results.items():
        averages = per_doc_averages(rows)
        layers[name] = {
            "summary": summarize(rows),
            "per_document_average": averages,
            "extra_vs_none_per_document": {
                k: round(averages[k] - base[k], 10 if k == "cost_usd" else 2) for k in ("input_tokens", "output_tokens", "cost_usd")
            },
            "documents": [
                {"document": r["document"], "all_fields_match": r["all_fields_match"], "decision_match": r["decision_match"],
                 "wrong_fields": [n for n, v in r["fields"].items() if not v["match"]],
                 "decision": r["decision"]["agent"], "trap_tool_called": r["trap_tool_called"],
                 "flags": sorted({f["check"] for f in r["flags"]}), "removed_hidden_content": len(r["removed_hidden_content"]),
                 "input_tokens": r["tokens"]["input"], "output_tokens": r["tokens"]["output"],
                 "cost_usd": r["cost"]["total_usd"]}
                for r in rows
            ],
        }
    run_info = {
        "time": now(),
        "model": agent.MODEL_NAME,
        "documents": len(documents),
        "answer_key": "data/practice_key.json",
        "trap_log": "output/trap_calls.json",
        "trap_log_entries_before_run": traps_at_start,
        "trap_log_entries_after_run": len(read_json_list(TRAP_LOG)),
        "fresh_model_calls": fresh,
        "warm_up": f"each configuration first ran {WARM_UP} (not scored) so its prompt prefix was cached",
    }
    RESULTS.write_text(redact(json.dumps({
        "run": {**run_info, "agent": "vendor desk agent with all Problem 6 defenses on (code + design + prompt)"},
        "summary": summarize(results["all"]),
        "per_document_average": per_doc_averages(results["all"]),
        "documents": results["all"],
    }, indent=2)) + "\n", encoding="utf-8")
    LAYERS.write_text(redact(json.dumps({"run": run_info, "configs": layers}, indent=2)) + "\n", encoding="utf-8")

    print("\nconfig  fields  decision  traps  input/doc  output/doc  $/doc")
    for name, layer in layers.items():
        s, a = layer["summary"], layer["per_document_average"]
        print(f"{name:7} {s['all_fields_correct']:>3}/12  {s['decision_correct']:>4}/12  {s['trap_tool_calls']:>5}  "
              f"{a['input_tokens']:>9}  {a['output_tokens']:>10}  {a['cost_usd']:.7f}")
    print(f"fresh model calls: {fresh}")
    print(f"Saved {RESULTS.relative_to(ROOT).as_posix()} and {LAYERS.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
