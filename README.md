# Campus Customs Vendor Desk Agent (MGT 409E Homework 6)

A PydanticAI agent that reads one vendor document (a quote, catalog page, or supplier email), pulls out the vendor, SKU, unit price, lead time, and minimum order, and recommends whether to buy, following the Campus Customs Shop Handbook. The homework measures and cuts the cost of each run, then attacks and defends the agent against prompt injection.

> **Disclaimer:** This project uses Campus Customs for educational purposes only. There is no real partnership with the shop, and all vendors and documents are made up.

## Setup

Built and tested on Python 3.14.7. You need a Portkey API key. Every model call uses `gpt-6-luna` through Portkey.

```bash
python -m pip install -r requirements.txt
cp .env.example .env
```

On Windows, use `copy .env.example .env`. Then open `.env` and replace `your_key_here` with your Portkey key. `.env` is in `.gitignore` and is never committed.

## Run the agent

```bash
python agent.py --doc data/practice_docs/p01_bluehen_quote.html
```

This reads one document and prints the answer, the tools called, the tokens, and the cost. Any `.html`, `.pdf`, or `.eml` file under `data/` works, for example `data/exam_docs/e06_quote.pdf` or `data/my_attacks/a2_olea_quote.pdf`.

| Option | What it does |
|---|---|
| *(none)* | All three defense layers on, prompt caching on. This is the final agent. |
| `--no-defenses` | The undefended Problem 3 agent. |
| `--defenses code,prompt` | Only the layers listed (any of `code`, `design`, `prompt`). |
| `--no-cache` | Turns prompt caching off. |

Each run appends to `output/usage_log.json` (tokens and cost) and `output/audit_trail.json` (tool calls, what was removed or flagged, and the final answer).

**Safety:** the `send_email` and `approve_payment` tools never send or pay anything. They only log to `output/trap_calls.json`, which is still an empty list.

## Reproduce the results

Each script calls the model and overwrites its result file. All of them together cost a few cents.

| Problem | Command | Writes |
|---|---|---|
| 4. Caching | `python cache_test.py` | `output/cache_test.json` |
| 5. Attacks, no defenses | `python attack_test.py` | `output/attack_results.json` |
| 6. Defenses, layer by layer | `python defense_test.py` | `output/defense_results.json`, `output/defense_layers.json` |
| 7. My two attacks | `python red_team_test.py` | `output/red_team.json` |
| 8. Exam documents | `python exam_test.py` | `output/exam_results.json` |
| 9. Results page | `python build_report.py` | `output/hw6_report.html` (no model calls) |

Run `cache_test.py` only when no cached run has happened in the last 35 minutes, or the first cache write won't show up. `python make_attacks.py` rebuilds the two attack documents in `data/my_attacks/`.

## Where to look

- **`output/hw6_report.html`**: the results page. Download it and double-click; it needs no internet.
- **`output/harness.md`**: every field, tool, and defense, in plain English.
- **`output/*.md`**: the write-up for each problem.
- **`AI_prompts.md`**: the prompts used to build this.

## Layout

```
agent.py, tools.py, models.py   the agent, its tools and defenses, and its data types
prompts/prompt.md               the agent's instructions
data/                           handbook, prices, answer key, practice, exam and attack documents
output/                         logs, results and write-ups
*_test.py, make_attacks.py      the scripts in the table above
build_report.py, report_template.html   build the results page
```
