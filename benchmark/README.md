# Benchmarks

Harnesses for the published benchmarks GQL-Core is measured on. They live in the repository, not
in the `gql-core` package. Datasets are downloaded on demand into `benchmark/cache/` (git-ignored).

| Folder | Benchmark | What it measures | Results |
| --- | --- | --- | --- |
| `tck/` | [openCypher TCK](https://github.com/opencypher/openCypher) `2024.3` | Engine conformance: results, errors, side effects | `results/tck_compatibility_results.json` |
| `cypherbench/` | [CypherBench](https://huggingface.co/datasets/megagonlabs/cypherbench) | Engine: all 2,348 gold queries vs Neo4j's answers (`run_engine_parity`). Domain evaluation: NL→Cypher (`run_nl2cypher`) | `results/cypherbench_engine_parity.json`, `results/cypherbench_nl2cypher__*.json` |
| `metaqa/` | [MetaQA](https://github.com/yuyuz/MetaQA) | Domain evaluation: NL→Cypher on the movie KB, 1–3 hops | `results/metaqa_nl2cypher__*.json` |
| `snb/` | [LDBC SNB](https://ldbcouncil.org/benchmarks/snb/) SF0.1 (unaudited) | Engine performance and correctness on official parameter cases | `results/snb_interactive_results.json` |
| `industry/` | Hetionet v1.0 (own check) | Queries and a rule vs an independent plain-Python computation | `results/full_hetionet_benchmark.json` |

**Engine benchmarks** (TCK, CypherBench parity, LDBC, Hetionet) measure GQL-Core alone: a fixed
query goes in and the result is compared with the reference.

**Domain evaluations** (CypherBench and MetaQA NL→Cypher) measure an end-to-end pipeline: a
language model writes the query and GQL-Core repairs and runs it. Their scores depend on the
model and prompt as much as on GQL-Core, so each is reported three ways (model only, + direction
correction, full pipeline). `nl_pipeline.py` is the pipeline; `gemini_client.py` and
`ollama_client.py` are the model clients.

Each results file records the git commit, model and decoding settings, sample seed and every
evaluated question id. The NL evaluations are versioned by those files, not by the package
version: rerunning them with a new model or prompt does not produce a new GQL-Core release.
`results/gemini_nl_benchmark_answers.xlsx` lists every question with its expected and actual
answers. Methodology: [`docs/NL_BENCHMARKS.md`](../docs/NL_BENCHMARKS.md).

How to run each one: see "Reproduce" in the [README](../README.md#reproduce).
