"""Layer B: CypherBench NL->Cypher with a local Ollama model, executed on GQL-Core.

Protocol (follows the official zero-shot baseline, cypherbench/baseline/zero_shot_nl2cypher.py):
  * prompt: the official NL2CYPHER_PROMPT_DEFAULT with the official schema string
    (schema JSON + a ``name`` property on every entity, sorted, no descriptions);
  * decoding: temperature 0, stop at "\\n```", strip ```cypher fences;
  * metrics: execution accuracy (official comparison rules) and executable rate.
    Provenance-subgraph Jaccard (PSJS) needs Neo4j provenance tracking and is not computed.

Gold answers are CypherBench's own ``answer_json`` (computed on Neo4j); the
predicted query is executed on GQL-Core. Questions whose *gold* query GQL-Core
cannot reproduce (Layer A failures) are reported separately so engine gaps are
not mistaken for model errors.

The full test split is 2,348 questions. On a CPU-only machine use --per-graph to
evaluate a fixed, seeded, per-graph stratified sample; the sample ids are saved
with the results so the run is reproducible.
"""

from __future__ import annotations

import argparse
import gc
import json
import random
import time
from pathlib import Path

from benchmark.cypherbench.common import QueryTimeout, avg, breakdown, engine_info, git_commit, load_test, run_with_timeout
from benchmark.cypherbench.download import CACHE_DIR, TEST_GRAPHS, graph_path
from benchmark.cypherbench.loader import load_simplekg
from benchmark.cypherbench.metrics import execution_accuracy
from benchmark.gemini_client import make_client, run_slug
from benchmark import nl_pipeline
from gql_core import correct_relationship_directions, schema_triples
from gql_core.nl import value_hints
from gql_core.query.values import value_index
from benchmark.ollama_client import PredictionCache

NL2CYPHER_PROMPT_DEFAULT = """Translate the question to Cypher query based on the schema of a Neo4j knowledge graph.
- Output the Cypher query in a single line, without any additional output or explanation. Do not wrap the query with any formatting like ```.
- Perform graph pattern matching in the `MATCH` clause if possible.
- Avoid listing the same entity multiple times in the results. However, if multiple distinct entities share the same name, their names should be repeated as separate entries.
- Do not return node objects. Instead, return entity names or properties.

Graph Schema:
{schema}

Question: {question}
Cypher: """

OUT = Path("benchmark/results/cypherbench_nl2cypher.json")


def official_schema_str(schema: dict) -> str:
    """Reproduces PropertyGraphSchema.from_json(add_meta_properties={'name': 'str'}).to_sorted().to_str(True)."""
    entities = []
    for e in sorted(schema["entities"], key=lambda x: x["label"]):
        props = dict(sorted({"name": "str", **e["properties"]}.items()))
        entities.append({"label": e["label"], "properties": props})
    relations = []
    for r in sorted(schema["relations"], key=lambda x: (x["label"], x["subj_label"], x["obj_label"])):
        relations.append({"label": r["label"], "subj_label": r["subj_label"], "obj_label": r["obj_label"],
                          "properties": dict(sorted(r["properties"].items()))})
    return json.dumps({"name": schema["name"], "entities": entities, "relations": relations}, indent=2)


def clean_prediction(text: str) -> str:
    """Exactly the official post-processing."""
    return text.replace("```cypher", "").replace("```", "").strip()


def select_items(test: list[dict], graphs: list[str], per_graph: int | None, seed: int,
                 exclude: set[str] | None = None) -> list[dict]:
    items = []
    for g in graphs:
        pool = [x for x in test if x["graph"] == g and x["qid"] not in (exclude or set())]
        if per_graph is not None and per_graph < len(pool):
            pool = random.Random(f"{seed}:{g}").sample(pool, per_graph)
        items += pool
    return items


def _pipeline_record(it, g, graph, schema_str, hints, triples, index, client, cache, timeout, engine_ok) -> dict:
    def generate(prompt: str, key: str) -> dict:
        rec = cache.get(key)
        if rec is None:
            gen = client.generate(prompt, stop=["\n```"])
            rec = {"id": key, "raw": gen.text, "gen_seconds": round(gen.seconds, 2),
                   "prompt_tokens": gen.prompt_tokens, "output_tokens": gen.output_tokens}
            cache.put(rec)
        return rec

    prompt = NL2CYPHER_PROMPT_DEFAULT.format(schema=nl_pipeline.schema_with_hints(schema_str, hints),
                                             question=it["nl_question"])
    out = nl_pipeline.answer(prompt, graph=graph, triples=triples, index=index, generate=generate,
                             execute=lambda q: run_with_timeout(q, graph, timeout), clean=clean_prediction,
                             qid=it["qid"])
    best = out["best"]
    rec = {
        "qid": it["qid"], "graph": g, "nl_question": it["nl_question"],
        "match_category": it["from_template"]["match_category"],
        "return_pattern_id": it["from_template"]["return_pattern_id"],
        "gold_cypher": it["gold_cypher"], "pred_cypher": best["query"],
        "gen_seconds": sum((cache.get(k) or {}).get("gen_seconds", 0) for k in
                           [it["qid"]] + [f"{it['qid']}#retry{j}" for j in range(1, len(out["attempts"]))]),
        "gold_reproducible_on_engine": engine_ok.get(it["qid"]),
        "attempts": [{k: a[k] for k in ("model_query", "query", "repairs", "error", "feedback")}
                     for a in out["attempts"]],
        "executable": 0.0, "execution_accuracy": 0.0,
    }
    if best["error"] is None:
        rec["executable"] = 1.0
        rec["execution_accuracy"] = execution_accuracy(best["rows"], it["answer_json"], it["gold_cypher"])
    else:
        rec["error"] = best["error"]
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", choices=["ollama", "gemini"], default="ollama",
                    help="ollama (local) or gemini (needs GEMINI_API_KEY in the environment)")
    ap.add_argument("--model", required=True, help="model name, e.g. qwen2.5-coder:7b or gemini-2.5-flash-lite")
    ap.add_argument("--graphs", nargs="+", default=TEST_GRAPHS, choices=TEST_GRAPHS)
    ap.add_argument("--per-graph", type=int, default=None, help="seeded stratified sample size per graph")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=120.0, help="per-query execution timeout (s)")
    ap.add_argument("--parity", type=Path, default=Path("benchmark/results/cypherbench_engine_parity.json"),
                    help="Layer A results, used to flag questions whose gold query GQL-Core cannot reproduce")
    ap.add_argument("--correct-directions", action="store_true",
                    help="reverse relationship arrows the schema makes impossible before running "
                         "(gql_core.correct_relationship_directions); written to a separate results file")
    ap.add_argument("--pipeline", action="store_true",
                    help="GQL-Core NL pipeline (benchmark/nl_pipeline.py): stored-value hints in the prompt, "
                         "query repair, one execution-feedback retry; written to a separate results file")
    ap.add_argument("--exclude-sample-seed", type=int, default=None,
                    help="draw the sample from questions NOT in this seed's sample (a disjoint dev set)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    slug = run_slug(args.provider, args.model)
    if args.out is None:
        name = OUT.stem if args.provider == "ollama" else f"{OUT.stem}__{slug}"
        name += "__pipeline" if args.pipeline else "__corrected" if args.correct_directions else ""
        name += f"__seed{args.seed}" if args.seed != 0 or args.exclude_sample_seed is not None else ""
        args.out = OUT.with_name(f"{name}.json")
    client = make_client(args.provider, args.model)
    model_info = client.check()
    cache = PredictionCache(Path("benchmark/cache/predictions")
                            / f"cypherbench__{slug}{'__pipeline' if args.pipeline else ''}.jsonl")
    engine_ok: dict[str, bool] = {}
    if args.parity.exists():
        engine_ok = {r["qid"]: r["status"] == "match" for r in json.loads(args.parity.read_text(encoding="utf-8"))["results"]}

    test = load_test()
    exclude = None
    if args.exclude_sample_seed is not None:
        exclude = {x["qid"] for x in select_items(test, args.graphs, args.per_graph, args.exclude_sample_seed)}
    items = select_items(test, args.graphs, args.per_graph, args.seed, exclude)
    print(f"model {args.model} ({model_info.get('details', {}).get('parameter_size')}); {len(items)} questions", flush=True)

    results = []
    for g in args.graphs:
        g_items = [x for x in items if x["graph"] == g]
        if not g_items:
            continue
        graph, schema = load_simplekg(graph_path(g))
        schema_str = official_schema_str(schema)
        triples = schema_triples(schema)
        if args.pipeline:
            hints = value_hints(graph, labels=[e["label"] for e in schema["entities"]])
            index = value_index(graph)
        print(f"[{g}] {len(graph._nodes):,} nodes / {len(graph._edges):,} edges; {len(g_items)} questions", flush=True)
        for i, it in enumerate(g_items, 1):
            if args.pipeline:
                results.append(_pipeline_record(it, g, graph, schema_str, hints, triples, index, client, cache,
                                                args.timeout, engine_ok))
                if i % 10 == 0 or i == len(g_items):
                    print(f"  {i}/{len(g_items)}  EX "
                          f"{avg([r['execution_accuracy'] for r in results if r['graph'] == g]):.3f}", flush=True)
                continue
            cached = cache.get(it["qid"])
            if cached is None:
                prompt = NL2CYPHER_PROMPT_DEFAULT.format(schema=schema_str, question=it["nl_question"])
                gen = client.generate(prompt, stop=["\n```"])
                cached = {"id": it["qid"], "raw": gen.text, "gen_seconds": round(gen.seconds, 2),
                          "prompt_tokens": gen.prompt_tokens, "output_tokens": gen.output_tokens}
                cache.put(cached)
            pred = clean_prediction(cached["raw"])
            changes: list[str] = []
            if args.correct_directions:
                fix = correct_relationship_directions(pred, triples)
                pred, changes = fix.query, fix.changes
            rec = {
                "qid": it["qid"], "graph": g, "nl_question": it["nl_question"],
                "match_category": it["from_template"]["match_category"],
                "return_pattern_id": it["from_template"]["return_pattern_id"],
                "gold_cypher": it["gold_cypher"], "pred_cypher": pred,
                "gen_seconds": cached["gen_seconds"],
                "gold_reproducible_on_engine": engine_ok.get(it["qid"]),
                "executable": 0.0, "execution_accuracy": 0.0,
            }
            if args.correct_directions:
                rec["pred_cypher_model"] = clean_prediction(cached["raw"])
                rec["direction_changes"] = changes
            try:
                rows = run_with_timeout(pred, graph, args.timeout)
                rec["executable"] = 1.0
                rec["execution_accuracy"] = execution_accuracy(rows, it["answer_json"], it["gold_cypher"])
            except QueryTimeout as exc:
                rec["error"] = str(exc)
            except Exception as exc:  # noqa: BLE001
                rec["error"] = f"{type(exc).__name__}: {exc}"[:300]
            results.append(rec)
            if i % 10 == 0 or i == len(g_items):
                print(f"  {i}/{len(g_items)}  EX {avg([r['execution_accuracy'] for r in results if r['graph'] == g]):.3f}"
                      f"  last gen {cached['gen_seconds']}s", flush=True)
        del graph
        gc.collect()

    reproducible = [r for r in results if r["gold_reproducible_on_engine"]]
    summary = {
        "benchmark": "CypherBench test split (megagonlabs/cypherbench), zero-shot NL->Cypher",
        "model": model_info,
        "protocol": "official zero-shot prompt + official schema string; temperature 0; official EX comparison; "
                    "predicted queries executed on GQL-Core, compared with Neo4j gold answers",
        "direction_correction": args.correct_directions,
        "pipeline": nl_pipeline.__doc__.strip() if args.pipeline else None,
        "retried": sum(1 for r in results if len(r.get("attempts", ())) > 1),
        "repaired": sum(1 for r in results if any(a["repairs"] for a in r.get("attempts", ()))),
        "queries_direction_corrected": sum(1 for r in results if r.get("direction_changes")),
        "engine": engine_info(),
        "git_commit": git_commit(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sample": {"per_graph": args.per_graph, "seed": args.seed, "n": len(results),
                   "excluded_sample_of_seed": args.exclude_sample_seed,
                   "full_test_size": len(test)},
        "execution_accuracy": avg([r["execution_accuracy"] for r in results]),
        "executable": avg([r["executable"] for r in results]),
        "execution_accuracy_on_engine_reproducible_subset": {
            "n": len(reproducible), "value": avg([r["execution_accuracy"] for r in reproducible])},
        "avg_generation_seconds": avg([r["gen_seconds"] for r in results]),
        **breakdown(results, "execution_accuracy"),
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "results"}, indent=2))
    print(f"saved {args.out}")


if __name__ == "__main__":
    main()
