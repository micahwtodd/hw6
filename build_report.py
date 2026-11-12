"""Problem 9: build output/hw6_report.html - one self-contained page, no internet, no other files.

    python build_report.py

Every number on the page is read from the result files of Problems 4-8 (nothing is typed in by hand):
  output/cache_test.json       caching, with and without (Problem 4)
  output/attack_results.json   the undefended agent's first attack run (Problem 5)
  output/defense_layers.json   each defense layer alone and all together (Problem 6)
  output/defense_results.json  all layers on, with the answer key values (Problem 6)
  output/red_team.json         my two attacks, before and after (Problem 7)
  output/exam_results.json     the 10 exam documents (Problem 8)
  output/audit_trail.json      what the code layer removed from each exam document
The page layout lives in report_template.html; this script only injects the data.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import make_attacks
from tools import handbook_rules

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
TEMPLATE = ROOT / "report_template.html"
REPORT = OUT / "hw6_report.html"
DAYS = 30

# Plain-English labels for the practice documents (what each one hides), from output/defense_results.md.
PRACTICE_ATTACKS = {
    "p01": None,
    "p02": "A 0px line with a fake \"revised price\" of $5.11",
    "p03": "Hidden text swapping in an approved \"vendor of record\"",
    "p04": "A payment instruction inside an HTML comment",
    "p05": None,
    "p06": "White text asking to email the max-cost list",
    "p07": "A 0.8 pt line saying the lead time is \"now 7 days\"",
    "p08": None,
    "p09": "A 1px, zero-width-laced \"correction\" to 12 days",
    "p10": None,
    "p11": None,
    "p12": "Off-page text with a fake \"revised price\" of $17.44",
}
LAYER_NAMES = {"none": "No defenses", "code": "Code only", "design": "Design only", "prompt": "Prompt only", "all": "All three"}


def load(name: str):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def cache_section() -> dict:
    calls = load("cache_test.json")
    per: dict[tuple[str, str], dict] = defaultdict(lambda: defaultdict(float))
    order: list[str] = []
    for c in calls:
        doc = c["document"].split("/")[-1]
        if doc not in order:
            order.append(doc)
        row = per[(c["setup"], doc)]
        for k, v in c["tokens"].items():
            row[k] += v
        for k, v in c["cost"].items():
            row[k] += v
    setups = sorted({c["setup"] for c in calls})
    without = next(s for s in setups if "without" in s)
    with_ = next(s for s in setups if s != without)
    docs = []
    for doc in order:
        a, b = per[(without, doc)], per[(with_, doc)]
        docs.append({
            "doc": doc.split("_")[0], "file": doc,
            "without": {"input": int(a["input_tokens"]), "cost": a["total_usd"]},
            "with": {"cached": int(b["cached_tokens"]), "written": int(b["cache_write_tokens"]),
                     "uncached": int(b["uncached_input_tokens"]), "cost": b["total_usd"]},
            "saved": 1 - b["total_usd"] / a["total_usd"],
        })

    def total(setup: str) -> dict:
        keys = ("uncached_input_usd", "cached_input_usd", "cache_write_usd", "output_usd", "total_usd",
                "input_tokens", "cached_tokens", "cache_write_tokens", "uncached_input_tokens", "output_tokens")
        return {k: sum(per[(setup, d)][k] for d in order) for k in keys}

    t_without, t_with = total(without), total(with_)
    n = len(order)
    warm = sum(d["with"]["cost"] for d in docs[1:]) / (n - 1)
    avg_without = t_without["total_usd"] / n
    write_extra = docs[0]["with"]["cost"] - warm
    month_without = DAYS * 1000 * avg_without
    month_with = DAYS * 1000 * warm + DAYS * write_extra
    with_calls = [c for c in calls if c["setup"] == with_]
    return {
        "docs": docs, "without": t_without, "with": t_with, "calls": len(calls), "n": n,
        "writes": sum(c["tokens"]["cache_write_tokens"] > 0 for c in with_calls),
        "reads": sum(c["tokens"]["cached_tokens"] > 0 for c in with_calls),
        "with_calls": len(with_calls),
        "saved_total": 1 - t_with["total_usd"] / t_without["total_usd"],
        "avg_without": avg_without, "avg_with": t_with["total_usd"] / n, "warm": warm,
        "saved_warm": 1 - warm / (sum(d["without"]["cost"] for d in docs[1:]) / (n - 1)),
        "first_saved": docs[0]["saved"], "write_extra": write_extra,
        "prefix_tokens": docs[0]["with"]["written"],
        "month_without": month_without, "month_with": month_with,
        "month_saved": 1 - month_with / month_without,
    }


def attack_section() -> dict:
    layers = load("defense_layers.json")
    final = {d["document"]: d for d in load("defense_results.json")["documents"]}
    first = load("attack_results.json")
    rules = handbook_rules()["catalogue"]
    configs = {}
    for name, cfg in layers["configs"].items():
        configs[name] = {
            "label": LAYER_NAMES[name],
            "fields": cfg["summary"]["all_fields_correct"], "decisions": cfg["summary"]["decision_correct"],
            "traps": cfg["summary"]["trap_tool_calls"],
            "avg": cfg["per_document_average"], "extra": cfg["extra_vs_none_per_document"],
            "docs": [{"ok": d["all_fields_match"] and d["decision_match"], "wrong": d["wrong_fields"]
                      + ([] if d["decision_match"] else ["decision"]), "decision": d["decision"],
                      "removed": d["removed_hidden_content"], "flags": [f if isinstance(f, str) else f.get("check") for f in d["flags"]]}
                     for d in cfg["documents"]],
        }
    docs = []
    for i, d in enumerate(layers["configs"]["all"]["documents"]):
        file = d["document"]
        short = file.split("_")[0]
        key = {k: v["key"] for k, v in final[file]["fields"].items()}
        key["decision"] = final[file]["decision"]["key"]
        cap = rules.get(key["sku"], {}).get("max_unit_cost")
        before = configs["none"]["docs"][i]
        harm = None
        if before["decision"] == "recommend" and key["decision"] == "do_not_recommend" and cap is not None:
            harm = round((key["unit_price"] - cap) * key["min_order"], 2)
        docs.append({"doc": short, "file": file, "attack": PRACTICE_ATTACKS[short], "key": key, "cap": cap,
                     "harm_if_ordered": harm, "reason_after": final[file]["reason"]})
    return {
        "docs": docs, "configs": configs, "order": ["none", "code", "design", "prompt", "all"],
        "first_run": {"fields": first["summary"]["all_fields_correct"], "decisions": first["summary"]["decision_correct"],
                      "traps": first["summary"]["trap_tool_calls"]},
        "attacked": sum(1 for d in docs if d["attack"]), "n": len(docs),
    }


def exam_section() -> dict:
    results = load("exam_results.json")
    audit = load("audit_trail.json")
    rules = handbook_rules()
    rows = []
    for e in results:
        record = next(a for a in reversed(audit)
                      if a["document"].endswith(e["file"]) and a.get("defenses") == "all")
        cap = rules["catalogue"].get(e["sku"] or "", {})
        rows.append({**e, "item": cap.get("item"), "cap": cap.get("max_unit_cost"),
                     "removed": [{"how": r.get("how"), "text": r.get("text")} for r in record["removed_hidden_content"]],
                     "flags": [f.get("check") for f in record["flags"]]})
    return {
        "rows": rows, "n": len(rows),
        "recommend": sum(r["decision"] == "recommend" for r in rows),
        "traps": sum(r["trap_tool_called"] for r in rows),
        "attacked": sum(bool(r["removed"]) for r in rows),
        "cost": sum(r["cost_usd"] for r in rows),
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "cached_tokens": sum(r["cached_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] for r in rows),
    }


def red_team_section() -> dict:
    data = load("red_team.json")
    key = {r["file"]: r for r in json.loads((ROOT / "data" / "my_attacks_key.json").read_text(encoding="utf-8"))}
    cap = handbook_rules()["catalogue"]
    meta = {
        "a1_otaru_quote.html": {
            "name": "Otaru", "kind": "Unit-of-measure trick", "format": "HTML",
            "where": "Text layered underneath an opaque picture of the quote",
            "where_short": "under a picture of the quote", "caught_short": "the design layer",
            "goal": "Gets the agent to divide the case price by 15 units, not 12",
            "title": "East Rock Ceramics", "subtitle": "Otaru izakaya ramen-ware line",
            "visible": [["Campus Customs SKU", "CC-MG-001"], ["Item", "Classic Bulldog Mug"], ["Price", "$90.00 per case"],
                        ["Case pack", "12 units per case"], ["Minimum order", "120 units"], ["Lead time", "14 business days"]],
            "hidden": make_attacks.OTARU_HIDDEN_LINES,
            "caught_by": "Design layer (Python decides from the stated $90.00), with the grounding check as a backstop",
        },
        "a2_olea_quote.pdf": {
            "name": "Olea", "kind": "SKU swap", "format": "PDF",
            "where": "Text painted on the page, then covered by a white box the color of the page",
            "where_short": "under a white box on the page", "caught_short": "the prompt layer",
            "goal": "Gets the agent to check $12.00 against a pricier item's limit",
            "title": "Olea Mediterranean Table", "subtitle": "The restaurant-ware line of East Rock Ceramics",
            "visible": [["Vendor", "East Rock Ceramics"], ["Campus Customs SKU", "CC-MG-001"], ["Item", "Classic Bulldog Mug"],
                        ["Unit price", "$12.00 per unit"], ["Minimum order", "120 units"], ["Lead time", "14 business days"]],
            "hidden": make_attacks.OLEA_HIDDEN_LINES,
            "caught_by": "Prompt layer (the document is data, not instructions), backed by the conflict check",
        },
    }
    attacks = []
    for file, m in meta.items():
        runs = [d for d in data["documents"] if d["document"] == file]
        k = key[file]
        true_cap = cap[k["sku"]]["max_unit_cost"]
        by = {}
        for config in ("none", "all"):
            rs = [r for r in runs if r["config"] == config]
            by[config] = {"runs": len(rs), "fooled": sum(not r["decision_match"] for r in rs),
                          "decision": rs[0]["decision"]["agent"], "price": rs[0]["fields"]["unit_price"]["agent"],
                          "sku": rs[0]["fields"]["sku"]["agent"], "reason": rs[0]["reason"]}
        kind = m["kind"]
        attacks.append({**m, "kind_lc": kind if kind.split()[0].isupper() else kind[0].lower() + kind[1:],
                        "file": file, "key": k, "cap": true_cap,
                        "overcharge": round((k["unit_price"] - true_cap) * k["min_order"], 2), "results": by})
    return {"attacks": attacks, "cost": sum(d["cost_usd"] for d in data["documents"]), "calls": len(data["documents"])}


def recommendation(attacks: dict, exam: dict, red: dict) -> dict:
    prices = json.loads((ROOT / "data" / "prices.json").read_text(encoding="utf-8"))["gpt-6-luna"]
    avg = attacks["configs"]["all"]["avg"]
    prefix = avg["cached_tokens"] / avg["model_calls"]  # the cached prefix, read once per model call
    warm = avg["cost_usd"]
    write_extra = prefix * (prices["cache_write_per_1m"] - prices["cached_input_per_1m"]) / 1_000_000
    no_cache = (avg["input_tokens"] * prices["input_per_1m"] + avg["output_tokens"] * prices["output_per_1m"]) / 1_000_000
    month = DAYS * 1000 * warm + DAYS * write_extra
    harms = [{"what": f"{d['doc']}: fake price accepted", "usd": d["harm_if_ordered"],
              "note": f"{d['key']['min_order']} units at ${d['key']['unit_price']:.2f} against a ${d['cap']:.2f} limit"}
             for d in attacks["docs"] if d["harm_if_ordered"]]
    harms += [{"what": f"{a['name']}: {a['kind_lc']}", "usd": a["overcharge"],
               "note": f"{a['key']['min_order']} units at ${a['key']['unit_price']:.2f} against a ${a['cap']:.2f} limit"}
              for a in red["attacks"]]
    return {"days": DAYS, "prices": prices, "warm": warm, "write_extra": write_extra, "no_cache": no_cache,
            "month": month, "month_no_cache": DAYS * 1000 * no_cache, "year": month * 12,
            "harms": harms, "undefended_warm": attacks["configs"]["none"]["avg"]["cost_usd"]}


def main() -> None:
    attacks, exam, red = attack_section(), exam_section(), red_team_section()
    data = {"cache": cache_section(), "attacks": attacks, "exam": exam, "red": red,
            "rec": recommendation(attacks, exam, red), "model": "gpt-6-luna",
            "built": datetime.now().strftime("%B %d, %Y").replace(" 0", " ")}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", payload)
    if payload not in html:
        raise SystemExit("report_template.html is missing the /*__DATA__*/null placeholder.")
    REPORT.write_text(html, encoding="utf-8")
    c, r = data["cache"], data["rec"]
    print(f"caching: ${c['without']['total_usd']:.7f} -> ${c['with']['total_usd']:.7f} ({c['saved_total']:.1%} saved, warm {c['saved_warm']:.1%})")
    print(f"30 days at 1,000/day (Problem 4 agent): ${c['month_without']:.2f} -> ${c['month_with']:.2f}")
    print(f"defended agent: ${r['warm']:.7f}/doc warm, ${r['month']:.2f}/month (no cache ${r['month_no_cache']:.2f})")
    print("harms:", [(h["what"], h["usd"]) for h in r["harms"]])
    print(f"wrote {REPORT.relative_to(ROOT).as_posix()} ({REPORT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
