# Natural-language and engine benchmarks: CypherBench and MetaQA

GQL-Core is evaluated on two published benchmarks, using their own data, questions,
gold answers and metrics. Nothing in these harnesses is hand-written test data.

| Benchmark | What it provides | Used for |
| --- | --- | --- |
| **CypherBench** (Feng et al., 2024, [arXiv:2412.18702](https://arxiv.org/abs/2412.18702); data [megagonlabs/cypherbench](https://huggingface.co/datasets/megagonlabs/cypherbench), Apache-2.0) | 7 Wikidata-derived property graphs (test split), 2,348 test questions, each with a gold Cypher query and the gold answer computed on Neo4j | Layer A (engine) and Layer B (NL→Cypher) |
| **MetaQA** (Zhang et al., AAAI 2018; [original release](https://github.com/yuyuz/MetaQA), mirrored at [camazlucas/MetaQA](https://huggingface.co/datasets/camazlucas/MetaQA)) | WikiMovies KB (134,741 triples) and 1/2/3-hop test questions (9,947 / 14,872 / 14,274) with gold answer sets | Layer B (end-to-end KGQA through Cypher) |

Datasets are downloaded into `benchmark/cache/` (git-ignored) and are not redistributed.

## Layer A: engine correctness (CypherBench gold queries)

`python -m benchmark.cypherbench.download`
`PYTHONHASHSEED=0 python -m benchmark.cypherbench.run_engine_parity`

Every CypherBench test question's **gold** Cypher query is executed on GQL-Core over the
same graph, and the result is compared with the gold answer Neo4j produced
(`answer_json`), using the **official execution-accuracy comparison** (vendored from
the CypherBench repository in `benchmark/cypherbench/metrics.py`: row multisets,
column permutation allowed, order compared only when the gold query has `ORDER BY`).
Errors and timeouts (120 s, as in the official evaluation) count as failures.

**Tied rows.** openCypher leaves the order of rows with equal `ORDER BY` keys
undefined, so Neo4j's gold order among ties is arbitrary. The official score counts
such cases as failures, and we report that score unchanged. Separately, each
`ORDER BY` mismatch is diagnosed: the query is re-run exposing its sort key, and the
case is marked `tie_equivalent` only if Neo4j's rows form a valid ordering with
exactly our key sequence. Both numbers are in the results file.

Results: `benchmark/results/cypherbench_engine_parity.json`.

**Result (full test split, 2,348 questions, `PYTHONHASHSEED=0`, 120 s timeout, CPU-only laptop):**

| Graph | Questions | Official execution accuracy | Counting tied order as a match |
| --- | --- | --- | --- |
| nba | 270 | 98.15% | 100% |
| flight_accident | 189 | 98.94% | 100% |
| fictional_character | 385 | 100% | 100% |
| company | 347 | 96.54% | 100% |
| geography | 366 | 98.36% | 100% |
| movie | 401 | 98.50% | 100% |
| politics | 390 | 97.18% | 100% |
| **All** | **2,348** | **98.21%** | **100%** |

There were no errors and no timeouts. All 42 official failures are `ORDER BY` queries whose rows
differ from Neo4j's only in the order of rows with equal sort keys, which openCypher leaves
undefined.

## Layer B: NL→Cypher with a local model (Ollama)

`python -m benchmark.cypherbench.run_nl2cypher --model <ollama-tag> [--per-graph N]`
`python -m benchmark.metaqa.run_nl2cypher --model <ollama-tag> [--per-hop N]`

* **CypherBench:** the official zero-shot prompt and schema string
  (`zero_shot_nl2cypher.py`), temperature 0, official post-processing. The predicted
  query runs on GQL-Core and is scored with official execution accuracy against
  Neo4j's gold answer; the executable rate is reported too. PSJS (provenance subgraph
  Jaccard) needs Neo4j provenance tracking and is not computed. Questions whose gold
  query GQL-Core cannot reproduce (Layer A failures) are flagged, so engine gaps are
  not mistaken for model errors.
* **MetaQA:** MetaQA has gold answers but no gold queries, so this is end-to-end KGQA:
  the CypherBench prompt wording plus the MetaQA schema, with one added line saying
  that the bracketed entity is an exact node `name`. The answer set is the first
  returned column, with the topic entity removed (MetaQA gold sets never include it).
  Metrics: exact set match, mean F1, and Hit (at least one returned answer is
  correct). "Hit" is not "Hits@1", because a Cypher query returns an unranked set.
* **Sampling.** On a CPU-only machine the full splits take days. `--per-graph` and
  `--per-hop` draw a fixed, seeded, stratified sample. The sample size, seed and every
  evaluated id are written to the results, so reported numbers state the n they come
  from. Model outputs are cached in `benchmark/cache/predictions/`, so interrupted
  runs resume.

Results: `benchmark/results/cypherbench_nl2cypher.json`, `benchmark/results/metaqa_nl2cypher.json`.

## Engine gaps found and fixed by Layer A

Running real gold queries surfaced three engine bugs, each with a regression test in
`tests/test_cypherbench_regressions.py`:

1. `CALL { … UNION … }` subqueries were not supported (310 of 2,348 test questions).
2. Keywords were case-sensitive (`RETURN n, m0 as m` failed to parse).
3. `WITH … RETURN … ORDER BY n.prop` sorted a null property as the node object
   itself, instead of as null.
4. Pattern matching always started at the leftmost node, so
   `(n)-->(m0)<--(m1 {name: 'X'})` scanned every `n` and timed out on large graphs.
   The matcher now starts at the most selective node (bound, with the fewest edges
   first; then property-filtered; then smallest label), walking the chain backwards
   and forwards from it. Named paths,
   variable-length steps and filters that reference other pattern variables keep
   left-to-right order. The three gold queries that had timed out now finish in
   0.1–2.5 s with correct answers.

A latent parser bug also appeared along the way: parenthesized-expression markers,
keyed by `id()`, leaked between parses, so chained comparisons depended on earlier
queries. It is now reset per parse.
