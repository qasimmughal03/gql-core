"""MetaQA 1/2/3-hop: NL->Cypher with a local Ollama model, executed on GQL-Core.

MetaQA ships questions with gold *answer sets* (no gold queries), so this is an
end-to-end KGQA evaluation: the model writes one Cypher query per question, the
query runs on GQL-Core over the full MetaQA KB, and the returned answers are
scored against the gold set.

Protocol
  * prompt: the CypherBench zero-shot instructions (same wording) with the MetaQA
    schema in the same JSON format, plus one line stating that the bracketed
    text is the exact ``name`` of the topic entity (the "vanilla" setting already
    marks it);
  * decoding: temperature 0, official CypherBench post-processing;
  * prediction = the distinct string values of the first returned column, with
    the topic entity removed (MetaQA gold sets never contain the topic entity);
  * metrics: exact set match (EM), mean F1, and Hit (at least one returned answer
    is in the gold set). Hit is reported instead of "Hits@1" because a Cypher
    query returns an unranked set.

The test splits hold 9,947 / 14,872 / 14,274 questions. On a CPU-only machine use
--per-hop for a fixed, seeded sample; the sampled ids are stored in the results.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from benchmark.cypherbench.common import QueryTimeout, avg, git_commit, run_with_timeout
from benchmark.cypherbench.run_nl2cypher import clean_prediction
from benchmark.metaqa.loader import HOPS, OBJECT_LABEL, load_graph, load_questions
from benchmark.ollama_client import OllamaClient, PredictionCache

PROMPT = """Translate the question to Cypher query based on the schema of a Neo4j knowledge graph.
- Output the Cypher query in a single line, without any additional output or explanation. Do not wrap the query with any formatting like ```.
- Perform graph pattern matching in the `MATCH` clause if possible.
- Avoid listing the same entity multiple times in the results. However, if multiple distinct entities share the same name, their names should be repeated as separate entries.
- Do not return node objects. Instead, return entity names or properties.
- The entity written in square brackets in the question is the exact `name` of a node in the graph.

Graph Schema:
{schema}

Question: {question}
Cypher: """

OUT = Path("benchmark/results/metaqa_nl2cypher.json")


def schema_str() -> str:
    labels = sorted({"Movie", *OBJECT_LABEL.values()})
    entities = [{"label": lbl, "properties": {"name": "str"}} for lbl in labels]
    relations = [{"label": r, "subj_label": "Movie", "obj_label": o, "properties": {}}
                 for r, o in sorted(OBJECT_LABEL.items())]
    return json.dumps({"name": "metaqa", "entities": entities, "relations": relations}, indent=2)


def score(pred: set[str], gold: set[str]) -> dict[str, float]:
    tp = len(pred & gold)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(gold) if gold else 0.0
    return {"em": float(pred == gold), "f1": (2 * p * r / (p + r)) if (p + r) else 0.0, "hit": float(tp > 0)}


def answers_from_rows(rows: list[dict], topic: str) -> set[str]:
    out: set[str] = set()
    for row in rows:
        if not row:
            continue
        v = next(iter(row.values()))
        vals = v if isinstance(v, (list, tuple)) else [v]
        for x in vals:
            if x is None:
                continue
            name = x.props.get("name") if hasattr(x, "props") else x
            if name is not None:
                out.add(str(name))
    out.discard(topic)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="Ollama model tag, e.g. qwen2.5-coder:7b")
    ap.add_argument("--hops", nargs="+", type=int, default=list(HOPS), choices=HOPS)
    ap.add_argument("--per-hop", type=int, default=None, help="seeded sample size per hop")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=60.0, help="per-query execution timeout (s)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    client = OllamaClient(args.model)
    model_info = client.check()
    cache = PredictionCache(Path("benchmark/cache/predictions") / f"metaqa__{args.model.replace(':', '_').replace('/', '_')}.jsonl")
    graph, triples = load_graph()
    schema = schema_str()
    print(f"MetaQA KB: {len(graph._nodes):,} entities / {len(graph._edges):,} triples; model {args.model}", flush=True)

    results = []
    totals = {}
    for h in args.hops:
        qs = load_questions(h)
        totals[h] = len(qs)
        if args.per_hop is not None and args.per_hop < len(qs):
            qs = random.Random(f"{args.seed}:{h}").sample(qs, args.per_hop)
        for i, q in enumerate(qs, 1):
            cached = cache.get(q.qid)
            if cached is None:
                gen = client.generate(PROMPT.format(schema=schema, question=q.question), stop=["\n```"])
                cached = {"id": q.qid, "raw": gen.text, "gen_seconds": round(gen.seconds, 2),
                          "prompt_tokens": gen.prompt_tokens, "output_tokens": gen.output_tokens}
                cache.put(cached)
            pred_cypher = clean_prediction(cached["raw"])
            rec = {"qid": q.qid, "hops": h, "question": q.question, "pred_cypher": pred_cypher,
                   "gold_answers": q.answers, "gen_seconds": cached["gen_seconds"], "executable": 0.0,
                   "em": 0.0, "f1": 0.0, "hit": 0.0}
            try:
                rows = run_with_timeout(pred_cypher, graph, args.timeout)
                rec["executable"] = 1.0
                pred = answers_from_rows(rows, q.topic)
                rec.update(score(pred, set(q.answers)))
                rec["pred_answers"] = sorted(pred)[:50]
            except QueryTimeout as exc:
                rec["error"] = str(exc)
            except Exception as exc:  # noqa: BLE001
                rec["error"] = f"{type(exc).__name__}: {exc}"[:300]
            results.append(rec)
            if i % 10 == 0 or i == len(qs):
                hr = [r for r in results if r["hops"] == h]
                print(f"  {h}-hop {i}/{len(qs)}  EM {avg([r['em'] for r in hr]):.3f}  F1 {avg([r['f1'] for r in hr]):.3f}"
                      f"  last gen {cached['gen_seconds']}s", flush=True)

    by_hop = {}
    for h in args.hops:
        hr = [r for r in results if r["hops"] == h]
        by_hop[f"{h}-hop"] = {"n": len(hr), "test_size": totals[h], "em": avg([r["em"] for r in hr]),
                              "f1": avg([r["f1"] for r in hr]), "hit": avg([r["hit"] for r in hr]),
                              "executable": avg([r["executable"] for r in hr])}
    summary = {
        "benchmark": "MetaQA vanilla test splits (Zhang et al., 2018), NL->Cypher end-to-end KGQA",
        "model": model_info,
        "protocol": "CypherBench zero-shot prompt wording + MetaQA schema; temperature 0; "
                    "first returned column as the answer set, topic entity removed",
        "git_commit": git_commit(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kb": {"entities": len(graph._nodes), "triples": len(triples)},
        "sample": {"per_hop": args.per_hop, "seed": args.seed},
        "by_hop": by_hop,
        "overall": {"n": len(results), "em": avg([r["em"] for r in results]), "f1": avg([r["f1"] for r in results]),
                    "hit": avg([r["hit"] for r in results]), "executable": avg([r["executable"] for r in results])},
        "avg_generation_seconds": avg([r["gen_seconds"] for r in results]),
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
