"""Build the expected-vs-actual workbook for the Gemini 2.5 Flash NL->Cypher runs.

Usage, from the repository root (needs openpyxl):

    python benchmark/workbook/build_answers_workbook.py . cb_rows.json benchmark/results/gemini_nl_benchmark_answers.xlsx

cb_rows.json comes from cypherbench_rows.py; the failure categories from nl_failure_taxonomy.py.
"""
import collections
import json
import os
import sys

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

repo, cb_rows_path, out = sys.argv[1:4]
sys.path.insert(0, repo)
os.chdir(repo)
from benchmark.cypherbench.common import load_test  # noqa: E402

R = "benchmark/results/"
MQ = {n: json.load(open(f"{R}metaqa_nl2cypher__gemini_gemini-2.5-flash{s}.json", encoding="utf-8"))
      for n, s in [("model", ""), ("corrected", "__corrected"), ("pipeline", "__pipeline")]}
CB = {n: json.load(open(f"{R}cypherbench_nl2cypher__gemini_gemini-2.5-flash{s}.json", encoding="utf-8"))
      for n, s in [("model", ""), ("corrected", "__corrected"), ("pipeline", "__pipeline")]}
cb_rows = {} if cb_rows_path == "-" else json.load(open(cb_rows_path, encoding="utf-8"))
gold = {x["qid"]: x for x in load_test()}
_tax = json.load(open(f"{R}nl_failure_taxonomy.json", encoding="utf-8"))["runs"]
TAXONOMY = {i["qid"]: i["primary"] for i in _tax["cypherbench/pipeline"]["items"]}

FONT = "Arial"
HEAD = Font(name=FONT, bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", start_color="1F4E78")
BODY = Font(name=FONT, size=10)
WRAP = Alignment(wrap_text=True, vertical="top")
GOOD = PatternFill("solid", start_color="C6EFCE")
BAD = PatternFill("solid", start_color="FFC7CE")
MAX = 1500


def clip(s: str) -> str:
    return s if len(s) <= MAX else s[:MAX] + f" ... [{len(s):,} characters in total]"


def norm(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(norm(x) for x in v) + "]"
    return "null" if v is None else str(v)


def fmt_rows(rows, n_total=None) -> str:
    if rows is None:
        return ""
    lines = [" | ".join(norm(v) for v in (r.values() if isinstance(r, dict) else r)) for r in rows]
    txt = "; ".join(lines) if lines else "(no rows)"
    n = n_total if n_total is not None else len(rows)
    if n > 1:
        txt = f"[{n} rows] " + txt
    return clip(txt)


def sheet(wb, title, headers, widths, rows, correct_cols, notes=None):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
        cell = ws.cell(row=1, column=c)
        cell.font, cell.fill, cell.alignment = HEAD, HEAD_FILL, WRAP
        if notes and headers[c - 1] in notes:
            cell.comment = Comment(notes[headers[c - 1]], "GQL-Core benchmark")
    for r in rows:
        ws.append(r)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font, cell.alignment = BODY, WRAP
    last = ws.max_row
    for col in correct_cols:
        rng = f"{col}2:{col}{last}"
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=["1"], fill=GOOD))
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=["0"], fill=BAD))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{last}"
    return ws


def attempts_text(rec):
    att = rec.get("attempts", [])
    repairs = "; ".join(x for a in att for x in a["repairs"])
    fb = att[0]["feedback"] if att and len(att) > 1 else ""
    if fb:
        fb = f"Retried. Feedback given: {fb}"
    return repairs, fb


# ---------------- MetaQA ----------------
mq_rows = []
by_id = {n: {r["qid"]: r for r in d["results"]} for n, d in MQ.items()}
for qid, m in by_id["model"].items():
    c, p = by_id["corrected"][qid], by_id["pipeline"][qid]

    def answers(r):
        if r.get("error"):
            return "Query failed: " + r["error"]
        pa = r.get("pred_answers") or []
        s = "; ".join(pa) if pa else "(no answers)"
        return clip(s + (" ... [first 50 shown]" if len(pa) >= 50 else ""))

    repairs, fb = attempts_text(p)
    mq_rows.append([qid, f"{m['hops']}-hop", m["question"], clip("; ".join(sorted(m["gold_answers"]))),
                    m["pred_cypher"], answers(m), int(m["em"]),
                    c["pred_cypher"], answers(c), int(c["em"]),
                    p["pred_cypher"], repairs, fb, answers(p), int(p["em"]), round(p["f1"], 3)])

mq_headers = ["Question ID", "Hops", "Question", "Expected answers (MetaQA gold)",
              "Model-only query", "Model-only answers", "Model-only correct",
              "Direction-corrected query", "Direction-corrected answers", "Direction-corrected correct",
              "Pipeline query (final)", "Pipeline repairs", "Pipeline retry", "Pipeline answers",
              "Pipeline correct", "Pipeline F1"]
mq_notes = {
    "Expected answers (MetaQA gold)": "The answer set from the MetaQA test split (Zhang et al., 2018).",
    "Model-only correct": "1 = exact match: the set of returned names equals the gold set. Computed by "
                          "benchmark/metaqa/run_nl2cypher.py; the topic entity is removed first.",
    "Pipeline answers": "The first returned column, as names, sorted. Only the first 50 are stored.",
    "Pipeline F1": "Harmonic mean of precision and recall of the returned set against the gold set.",
}

# ---------------- CypherBench ----------------


def cells(rows):
    return [tuple(sorted(norm(v) for v in (r.values() if isinstance(r, dict) else r))) for r in rows]


def cause(entry, g, engine_gold=None):
    if entry.get("error"):
        return "Query failed: " + entry["error"][:120]
    gold_rows = json.loads(g["answer_json"])
    pred = entry.get("rows", [])
    if not pred:
        return "Returned no rows" if gold_rows else "Gold is empty"
    if not gold_rows:
        return "Returned rows; the gold answer is empty"
    pc = len(pred[0])
    gc = len(gold_rows[0])
    if pc != gc:
        return "Extra columns" if pc > gc else "Missing columns"
    pm, gm = collections.Counter(cells(pred)), collections.Counter(cells(gold_rows))
    if engine_gold is not None and pm == gm and cells(pred) == cells(engine_gold):
        return "Same rows as the gold query; only the order of tied rows differs from Neo4j"
    if set(pm) == set(gm):
        if sum(pm.values()) > sum(gm.values()):
            return "Right rows, but duplicates (no DISTINCT)"
        if sum(pm.values()) < sum(gm.values()):
            return "Right rows, but too few repeats (DISTINCT on names that gold keeps)"
        return "Right rows, different order"
    if len(gold_rows) == 1 and len(pred) == 1:
        return "Different value (count or aggregate)"
    if set(pm) & set(gm):
        return "Some rows right, others missing or extra"
    return "Different rows"


cb_list = []
cause_counts = collections.Counter()
mismatch = 0
by_cb = {n: {r["qid"]: r for r in d["results"]} for n, d in CB.items()}
for qid, m in (by_cb["model"].items() if cb_rows else []):
    c, p = by_cb["corrected"][qid], by_cb["pipeline"][qid]
    g = gold[qid]
    rr = cb_rows[qid]
    for n, rec in (("model", m), ("corrected", c), ("pipeline", p)):
        if rr[n]["rerun_ex"] != rec["execution_accuracy"]:
            mismatch += 1

    def ans(n):
        e = rr[n]
        return "Query failed: " + e["error"] if e.get("error") else fmt_rows(e.get("rows"), e.get("n_rows"))

    repairs, fb = attempts_text(p)
    why = "" if p["execution_accuracy"] == 1 else cause(rr["pipeline"], g, rr.get("gold_on_engine"))
    if why:
        cause_counts[why.split(":")[0] if why.startswith("Query failed") else why] += 1
    cb_list.append([qid, g["graph"], g["from_template"]["match_category"], g["nl_question"], g["gold_cypher"],
                    fmt_rows(json.loads(g["answer_json"])),
                    m["pred_cypher"], ans("model"), int(m["execution_accuracy"]),
                    c["pred_cypher"], ans("corrected"), int(c["execution_accuracy"]),
                    p["pred_cypher"], repairs, fb, ans("pipeline"), int(p["execution_accuracy"]), why,
                    TAXONOMY.get(qid, "")])

cb_headers = ["Question ID", "Graph", "Question type", "Question", "Gold query (CypherBench)",
              "Expected answer (Neo4j)", "Model-only query", "Model-only answer", "Model-only correct",
              "Direction-corrected query", "Direction-corrected answer", "Direction-corrected correct",
              "Pipeline query (final)", "Pipeline repairs", "Pipeline retry", "Pipeline answer",
              "Pipeline correct", "Why the pipeline answer is wrong", "How the pipeline query differs from the gold query"]
cb_notes = {
    "Expected answer (Neo4j)": "CypherBench's answer_json: the gold query's result computed on Neo4j. "
                               "Rows are separated by ';', columns by '|'.",
    "Model-only correct": "1 = official CypherBench execution accuracy: same multiset of rows, columns in any "
                          "order, row order checked only when the gold query has ORDER BY.",
    "Why the pipeline answer is wrong": "Classified automatically by comparing the returned rows with the gold rows.",
    "How the pipeline query differs from the gold query": "Primary category from benchmark/nl_failure_taxonomy.py: a "
        "heuristic structural comparison of the two queries (labels, relationship types and directions, constants, "
        "EXISTS/NOT/OPTIONAL, paths, aggregates, DISTINCT, ORDER BY/LIMIT).",
}

# ---------------- workbook ----------------
wb = Workbook()
summary = wb.active
summary.title = "Summary"
sheet(wb, "MetaQA", mq_headers, [11, 7, 40, 34, 46, 30, 10, 46, 30, 10, 46, 30, 30, 30, 10, 8], mq_rows,
      ["G", "J", "O"], mq_notes)
if cb_list:
  sheet(wb, "CypherBench", cb_headers,
      [11, 13, 18, 44, 50, 34, 50, 34, 10, 50, 34, 10, 50, 30, 30, 34, 10, 30, 30], cb_list, ["I", "L", "Q"], cb_notes)

n_mq, n_cb = len(mq_rows) + 1, len(cb_list) + 1
engines = {(d["engine"]["version"], d["engine"].get("installed_from", d["engine"]["source"]))
           for d in list(MQ.values()) + list(CB.values())}
assert len(engines) == 1, f"results were produced by different engines: {engines}"
(ver, src), = engines
summary.append([f"Gemini 2.5 Flash, NL->Cypher executed on gql-core {ver} installed from {src} "
                f"(seed-0 test samples)"])
summary.append([])
summary.append(["Benchmark", "Questions", "Model only", "+ direction correction", "GQL-Core pipeline"])
summary.append(["MetaQA (exact match)", f"=COUNTA(MetaQA!A2:A{n_mq})",
                f"=AVERAGE(MetaQA!G2:G{n_mq})", f"=AVERAGE(MetaQA!J2:J{n_mq})", f"=AVERAGE(MetaQA!O2:O{n_mq})"])
for h in (1, 2, 3):
    summary.append([f"   MetaQA {h}-hop", f'=COUNTIF(MetaQA!B2:B{n_mq},"{h}-hop")'] +
                   [f'=AVERAGEIF(MetaQA!B2:B{n_mq},"{h}-hop",MetaQA!{c}2:{c}{n_mq})' for c in "GJO"])
if not cb_list:
    pass
else:
  summary.append(["CypherBench (execution accuracy)", f"=COUNTA(CypherBench!A2:A{n_cb})",
                f"=AVERAGE(CypherBench!I2:I{n_cb})", f"=AVERAGE(CypherBench!L2:L{n_cb})",
                f"=AVERAGE(CypherBench!Q2:Q{n_cb})"])
for g in (["nba", "flight_accident", "fictional_character", "company", "geography", "movie", "politics"] if cb_list else []):
    summary.append([f"   CypherBench {g}", f'=COUNTIF(CypherBench!B2:B{n_cb},"{g}")'] +
                   [f'=AVERAGEIF(CypherBench!B2:B{n_cb},"{g}",CypherBench!{c}2:{c}{n_cb})' for c in "ILQ"])
summary.append([])
start = summary.max_row + 1
if cb_list:
    summary.append(["Why CypherBench pipeline answers are wrong", "Questions"])
    for k, _ in cause_counts.most_common():
        crit = k + "*" if k == "Query failed" else k
        summary.append([k, f'=COUNTIF(CypherBench!R2:R{n_cb},"{crit}")'])
    summary.append(["Total wrong", f"=SUM(B{start + 1}:B{summary.max_row})"])
summary.append([])
for line in [
    "How to read this workbook",
    "MetaQA and CypherBench sheets: one row per question, with the expected answer and what each configuration returned.",
    "Green 1 = correct, red 0 = wrong. Use the column filters to show only wrong answers.",
    "Model only: the model's query run exactly as written. + direction correction: the same answers, with arrows the "
    "schema forbids reversed. GQL-Core pipeline: what ask() does (stored-value hints, query repair, one retry).",
    "Correct (1/0) values are the benchmark harness's scores (benchmark/results/*.json); the percentages above are "
    "formulas over those columns.",
    "Sources: CypherBench test split (megagonlabs/cypherbench, arXiv:2412.18702); MetaQA vanilla test split "
    "(Zhang et al., AAAI 2018). Model: gemini-2.5-flash, temperature 0, thinking off.",
    "Long cells are cut at 1,500 characters; MetaQA stores the first 50 answers of each result.",
]:
    summary.append([line])

for row in summary.iter_rows():
    for cell in row:
        cell.font = Font(name=FONT, size=10)
summary["A1"].font = Font(name=FONT, size=12, bold=True)
for c in range(1, 6):
    summary.cell(row=3, column=c).font = HEAD
    summary.cell(row=3, column=c).fill = HEAD_FILL
if cb_list:
  summary.cell(row=start, column=1).font = HEAD
  summary.cell(row=start, column=1).fill = HEAD_FILL
  summary.cell(row=start, column=2).font = HEAD
  summary.cell(row=start, column=2).fill = HEAD_FILL
for r in range(4, 4 + 4 + 8):
    for c in (3, 4, 5):
        summary.cell(row=r, column=c).number_format = "0.0%"
summary.column_dimensions["A"].width = 52
for col in "BCDE":
    summary.column_dimensions[col].width = 20

wb.save(out)
print("saved", out, "| MetaQA rows", len(mq_rows), "| CypherBench rows", len(cb_list),
      "| re-run EX differs from recorded:", mismatch)
print("pipeline failure causes:", dict(cause_counts.most_common()))
