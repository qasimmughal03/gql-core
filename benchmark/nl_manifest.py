"""Write benchmark/results/nl_benchmark_manifest.json: what the NL benchmark results were made from.

For each benchmark: the dataset and its pinned revision, the split and sample, the model and
decoding settings, the prompt and pipeline source files (SHA-256), the cached model responses
(SHA-256 and entry count; the cache itself is not published), the engine that ran the queries,
the metric definitions, and each configuration's score with its per-question results file.

    python benchmark/nl_manifest.py
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

RESULTS = Path("benchmark/results")
CACHE = Path("benchmark/cache")
OUT = RESULTS / "nl_benchmark_manifest.json"

CONFIGS = {
    "model-only": ("", "Gemini's query as generated, executed unchanged"),
    "direction-corrected": ("__corrected", "relationship directions corrected against the schema by "
                                           "gql_core.correct_relationship_directions; no other change"),
    "pipeline": ("__pipeline", "the full GQL-Core NL pipeline: value hints in the prompt, direction correction, "
                               "validation, and one retry with the engine's error or empty-result feedback"),
}


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def hf_revision(meta_dir: Path) -> str | None:
    revs = {p.read_text(encoding="utf-8").splitlines()[0] for p in meta_dir.rglob("*.metadata")}
    return revs.pop() if len(revs) == 1 else (sorted(revs) or [None])[0]


def cache_info(name: str) -> dict:
    p = CACHE / "predictions" / name
    if not p.exists():
        return {"file": name, "present": False}
    return {"file": f"benchmark/cache/predictions/{name}", "sha256": sha256(p),
            "entries": sum(1 for line in p.open(encoding="utf-8") if line.strip()),
            "last_written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(p.stat().st_mtime))}


def bench(name: str, dataset: dict, files: list[str], caches: list[str], score_key) -> dict:
    configs = {}
    engine = None
    for cfg, (suffix, desc) in CONFIGS.items():
        f = RESULTS / f"{name}_nl2cypher__gemini_gemini-2.5-flash{suffix}.json"
        d = json.loads(f.read_text(encoding="utf-8"))
        engine = engine or d["engine"]
        if d["engine"] != engine:
            raise SystemExit(f"{f} was produced by a different engine")
        configs[cfg] = {"description": desc, "results_file": f.as_posix(), "results_sha256": sha256(f),
                        "questions": len(d["results"]), "score": score_key(d), "harness_commit": d["git_commit"],
                        "timestamp": d["timestamp"]}
    return {
        "dataset": dataset,
        "model": d["model"],
        "protocol": d["protocol"],
        "sample": d["sample"],
        "engine": engine,
        "prompt_and_pipeline_sources": {p: sha256(Path(p)) for p in files},
        "model_response_cache": [cache_info(c) for c in caches],
        "configurations": configs,
    }


def main() -> None:
    cb_test = CACHE / "cypherbench" / "test.json"
    manifest = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": "End-to-end question answering: the language model writes the query, GQL-Core corrects, validates "
                "and executes it. These scores are not engine accuracy; see cypherbench_engine_parity.json for that.",
        "cypherbench": bench(
            "cypherbench",
            {"name": "CypherBench", "source": "huggingface.co/datasets/megagonlabs/cypherbench", "license": "Apache-2.0",
             "revision": hf_revision(CACHE / "cypherbench" / ".cache"), "split": "test",
             "test_json_sha256": sha256(cb_test), "gold_answer_format": "answer_json: JSON list of rows from Neo4j",
             "metric": "official CypherBench execution accuracy (EX): rows equal as a multiset, or as a list "
                       "when the gold query has ORDER BY; columns may be permuted"},
            ["benchmark/cypherbench/run_nl2cypher.py", "benchmark/cypherbench/common.py",
             "benchmark/cypherbench/metrics.py", "benchmark/nl_pipeline.py", "benchmark/gemini_client.py"],
            ["cypherbench__gemini_gemini-2.5-flash.jsonl", "cypherbench__gemini_gemini-2.5-flash__pipeline.jsonl"],
            lambda d: {"execution_accuracy": d["execution_accuracy"], "executable": d["executable"]}),
        "metaqa": bench(
            "metaqa",
            {"name": "MetaQA (vanilla)", "source": "huggingface.co/datasets/camazlucas/MetaQA",
             "revision": hf_revision(CACHE / "metaqa" / ".cache"), "split": "1-hop, 2-hop and 3-hop vanilla test",
             "gold_answer_format": "answer entity set per question",
             "metric": "exact match (EM): the first returned column, topic entity removed, equals the gold answer "
                       "set; F1 and hit@any also reported"},
            ["benchmark/metaqa/run_nl2cypher.py", "benchmark/metaqa/loader.py", "benchmark/nl_pipeline.py",
             "benchmark/gemini_client.py"],
            ["metaqa__gemini_gemini-2.5-flash.jsonl", "metaqa__gemini_gemini-2.5-flash__pipeline.jsonl"],
            lambda d: d["overall"]),
    }
    OUT.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({b: {c: v["score"] for c, v in manifest[b]["configurations"].items()}
                      for b in ("cypherbench", "metaqa")}, indent=2))
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
