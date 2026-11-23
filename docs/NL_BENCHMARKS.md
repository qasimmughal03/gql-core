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

**Result (full test split, 2,348 questions, commit `43cab07`, `PYTHONHASHSEED=0`, 120 s timeout, CPU-only laptop):**

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

## Layer B: NL→Cypher with Gemini 2.5 Flash

```bash
export GEMINI_API_KEY=...        # read from the environment, sent as a header, never stored
python -m benchmark.cypherbench.run_nl2cypher --provider gemini --model gemini-2.5-flash --per-graph 30 [--correct-directions | --pipeline]
python -m benchmark.metaqa.run_nl2cypher      --provider gemini --model gemini-2.5-flash --per-hop 100  [--correct-directions | --pipeline]
```

`--provider ollama` runs a local model instead.

**Model and decoding.** `gemini-2.5-flash` through the Gemini API, temperature 0, thinking
disabled (`thinkingBudget: 0`), up to 512 output tokens. The model's raw outputs are cached in
`benchmark/cache/predictions/`, so a run can be re-scored without new API calls.

**Prompts.**
* **CypherBench:** the official zero-shot prompt and schema string
  (`zero_shot_nl2cypher.py`) and the official post-processing. The predicted query runs on
  GQL-Core and is scored with official execution accuracy against Neo4j's gold answer. PSJS
  (provenance subgraph Jaccard) needs Neo4j provenance tracking and is not computed.
* **MetaQA:** MetaQA has gold answers but no gold queries, so this is end-to-end KGQA: the
  CypherBench prompt wording plus the MetaQA schema, with one added line saying that the
  bracketed entity is an exact node `name`. The answer set is the first returned column, with
  the topic entity removed (MetaQA gold sets never include it). Metrics: exact set match, mean
  F1, and Hit (at least one returned answer is correct). "Hit" is not "Hits@1", because a
  Cypher query returns an unranked set.

**Three configurations**, each in its own results file:

| Configuration | Flag | What changes |
| --- | --- | --- |
| Model only | none | The model's query runs exactly as written. |
| + direction correction | `--correct-directions` | The same cached answers, after `gql_core.correct_relationship_directions`: an arrow is reversed only when the schema makes the written direction impossible and the reverse possible for the labels involved. |
| GQL-Core pipeline | `--pipeline` | What `gql_core.ask` does (`benchmark/nl_pipeline.py`): the schema in the prompt is followed by the stored values of low-cardinality string properties; the model's query is repaired (directions, and string literals that match exactly one stored value ignoring case); and if it fails, returns no rows or returns duplicate rows, the model is shown what happened and may revise it once. |

None of these sees a gold query or a gold answer. Every repair and every retry is recorded per
question in the results file.

**Sampling.** On a CPU-only machine the full splits take days to execute. `--per-graph` and
`--per-hop` draw a fixed, seeded, stratified sample (seed 0 below). The sample size, seed and
every evaluated id are written to the results. **The pipeline was developed on a disjoint dev
sample** (`--seed 1 --exclude-sample-seed 0`, sharing no questions with seed 0) and then run
once on the seed-0 sample.

### Results (CypherBench at commit `afce555`, MetaQA at `67cd6f8`)

MetaQA has no dates, so the one engine change between the two commits (gap 10 below) does not
affect it. The dev-sample column was measured during development (CypherBench at `9969830`,
MetaQA at `f084a69`), before the final engine fixes.

| Benchmark (metric) | Sample | Model only | + direction correction | **GQL-Core pipeline** | Dev sample, pipeline |
| --- | --- | ---: | ---: | ---: | ---: |
| CypherBench (execution accuracy) | 210 of 2,348 | 61.4% | 66.2% | **73.3%** | 78.1% |
| MetaQA 1-hop (exact match) | 100 of 9,947 | 69% | 88% | **88%** | 89% |
| MetaQA 2-hop | 100 of 14,872 | 40% | 100% | **100%** | 100% |
| MetaQA 3-hop | 100 of 14,274 | 52% | 80% | **86%** | 88% |
| MetaQA, all | 300 | 53.7% | 89.3% | **91.3%** | 92.3% |

MetaQA F1 for the pipeline is 93.4% and Hit is 94.7%. On CypherBench, 99.5% of the pipeline's final queries run without error. On the 205 sampled
questions whose gold query GQL-Core reproduces exactly (Layer A), the pipeline scores 75.1%.

| CypherBench graph | nba | flight_accident | fictional_character | company | geography | movie | politics |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Model only | 63.3% | 83.3% | 60.0% | 56.7% | 70.0% | 43.3% | 53.3% |
| + direction correction | 63.3% | 86.7% | 60.0% | 60.0% | 70.0% | 50.0% | 73.3% |
| GQL-Core pipeline | 83.3% | 86.7% | 63.3% | 70.0% | 70.0% | 56.7% | 83.3% |

### Why the model alone misses, and what the pipeline fixes

Every failed question of the model-only runs was classified by re-running its query.

**MetaQA** (139 of 300 failed):

| Cause | Questions | Fixed by |
| --- | ---: | --- |
| Relationship written in the reverse direction, e.g. `(:Person)-[:written_by]->(:Movie)` | 107 | direction correction |
| Bracketed entity given the wrong type, e.g. the film *Kiss Them for Me* as a `Person`, or a tag read as an actor | about 20 | not fixable without the answer; partly by the retry |
| Two different films share a title and MetaQA's KB merges them into one node, so the answer includes the other film's director or year | 7 | not fixable: a dataset artefact |
| Other (a non-existent property such as `m.release_year.name`, a timeout) | 5 | partly by the retry |

The 2-hop questions show the effect most clearly: 60 of the 61 failures were reversed
arrows, and with them reversed every 2-hop question in the sample is answered exactly.

**CypherBench** (81 of 210 failed):

| Cause | Questions | Fixed by |
| --- | ---: | --- |
| Query returns nothing: a stored value written with different capitalisation (`'Swingman'` for `swingman`), a wrong property, or a wrong relationship | 18 | value grounding, stored-value hints, retry |
| Duplicate rows: no `DISTINCT` although the prompt asks for unique entities | 16 | retry (the feedback names the duplicates) |
| Relationship in the reverse direction | 13 | direction correction, where the two ends have different labels |
| A count or aggregate differs (often because of a mis-capitalised filter value) | 12 | value grounding, hints |
| Too many or too few rows, or different rows: a different reading of the question | 18 | not fixable mechanically |
| Other (a missing column, a label or relationship not in the schema, one timeout) | 4 | |

Direction correction cannot help when both ends of a relationship have the same label, as in
`(c:Character)-[:hasStudent]->(teacher:Character)`, where only the meaning tells which way the
edge goes.

### What the pipeline still gets wrong

**CypherBench** (56 of 210 wrong after the pipeline, commit `afce555`). Each final query was
re-run and its rows compared with the gold answer:

| Cause | Questions |
| --- | ---: |
| Some rows right, others missing or extra: another reading of the question | 21 |
| A count or aggregate differs | 11 |
| Returns no rows, even after the retry | 10 |
| Different rows | 5 |
| Right rows, different order | 4 |
| Right rows, but duplicated (no `DISTINCT`) | 2 |
| Same rows as the gold query on GQL-Core; only the order of tied `ORDER BY` rows differs from Neo4j | 1 |
| A column missing | 1 |
| Timed out (120 s) | 1 |

The weakest question types are `ORDER BY` questions (12.5% of 8) and `OPTIONAL MATCH`
questions (38% of 21). Every question, with the expected answer, each configuration's query and
answer, and the cause above, is in
[`gemini_nl_benchmark_answers.xlsx`](../benchmark/results/gemini_nl_benchmark_answers.xlsx).

## Engine gaps found and fixed by these benchmarks

Running real gold queries (Layer A) and real model output (Layer B) surfaced these engine bugs.
Each has a regression test in `tests/test_cypherbench_regressions.py`.

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
5. Equality and `IN` conditions in `WHERE` (for example `WHERE c.name = 'X'`) were not used to
   choose the start node, so model-written queries timed out. They now choose the start
   node and prune its candidates; the full `WHERE` is still applied, so results are unchanged.
6. `EXISTS { … }` was left unparsed: `EXISTS` returned no rows, `NOT EXISTS` returned every row,
   and a `WHERE` inside the braces failed with "unbound variable". The Neo4j 4 forms
   `exists((pattern))` and `exists(n.prop)` were unknown functions.
7. Expanding to `(y:Year)` checked only a node's first label, so a node labelled both `Movie`
   and `Year` (MetaQA's year *2010*, which is also a film title) never matched. The
   variable-length operator had the same check.
8. A relationship with several types, `[:directed_by|written_by]`, matched nothing in queries
   that use `DISTINCT`, `WITH` or `count(DISTINCT …)`.
9. Result column names were read from the first `RETURN` in the text, including one inside
   `CALL { }` or `EXISTS { }`.
10. A nested property in a single `WHERE` condition, such as `WHERE m.release_date.year = 2010`,
    was pushed into the scan as a property literally named `release_date.year`, so it matched
    nothing. It is now read the same way as in a larger `WHERE`.

Items 6 to 10 were fixed after the Layer A measurement at `43cab07`.

A latent parser bug also appeared along the way: parenthesized-expression markers,
keyed by `id()`, leaked between parses, so chained comparisons depended on earlier
queries. It is now reset per parse.
