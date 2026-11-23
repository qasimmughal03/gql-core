# GQL-Core 0.2.0a3 release notes

**Stage:** alpha · **License:** Apache-2.0 · **Python:** 3.11+ · **Previous:** [0.2.0a2](RELEASE_NOTES_0.2.0a2.md) (tagged, not uploaded to PyPI; its changes are included here)

This release makes `ask()` much more accurate by checking the model's query against the graph
before running it, and fixes engine bugs found by running real model output.

## Natural-language queries

`ask()` and `translate_to_gql()` now repair the generated query by default. Every step uses only
the schema, the stored data and the engine's own results.

- **`correct_relationship_directions(query, schema)`** reverses an arrow only when the schema makes
  the written direction impossible and the reverse possible, for example
  `(:Person)-[:written_by]->(:Movie)` when the graph only has `(:Movie)-[:written_by]->(:Person)`.
  `schema` can be a graph, a CypherBench-style schema dict, or a set of triples
  (`schema_triples`).
- **`ground_values(query, graph)`** replaces an equality-compared string literal with the one
  stored value it matches ignoring case and whitespace (`'Shooting guard'` → `'shooting guard'`).
  Ambiguous, unlabelled and non-equality cases are left alone.
- **Stored values in the prompt.** The schema prompt lists the values of string properties with
  few distinct values (`gql_core.nl.value_hints`), and now shows every relationship direction
  present in the graph, counting all of a node's labels. Previously it sampled 100 edges per type
  and used only the first label.
- **One retry with execution feedback.** If the query fails, returns no rows, or returns duplicate
  rows, the model sees what happened and may revise it (`max_retries=1`). A revision never
  replaces a query that returned rows with one that fails or returns nothing. With
  `explain=True`, every attempt is returned under `attempts`.
- Turn the repairs off with `correct_directions=False` and the retry with `max_retries=0`.

Measured with Gemini 2.5 Flash on seeded samples (details in [NL_BENCHMARKS.md](NL_BENCHMARKS.md)):

| Benchmark | Model only | With the GQL-Core pipeline |
| --- | ---: | ---: |
| CypherBench, 210 questions (execution accuracy) | 61.4% | **73.3%** |
| MetaQA, 300 questions (exact match) | 53.7% | **91.3%** |

## Engine fixes

Each has a regression test in `tests/test_cypherbench_regressions.py`.

- **`EXISTS { … }`** was left unparsed, so `EXISTS` returned no rows and `NOT EXISTS` returned
  every row, without an error. It now works in `WHERE` and `RETURN`, and a `WHERE` inside the
  braces can use the subquery's own variables. `EXISTS { MATCH … }` with a single pattern is
  supported; other subquery forms raise `UnsupportedFeature` instead of answering wrongly.
  The Neo4j 4 forms `exists((pattern))` and `exists(n.prop)` work.
- **Nodes with several labels.** Expanding to `(y:Year)` checked only a node's first label, so a
  node labelled `Movie` and `Year` never matched. The variable-length operator had the same
  check.
- **Relationships with several types.** `[:a|b]` matched nothing in queries using `DISTINCT`,
  `WITH` or `count(DISTINCT …)`.
- **Column names** were read from the first `RETURN` in the query text, including one inside
  `CALL { }` or `EXISTS { }`.
- **Nested properties in a single condition.** `WHERE m.release_date.year = 2010` on its own
  matched nothing, because it was pushed into the scan as a property named `release_date.year`.

## Packaging

- The wheel now contains only the `gql_core` package. 0.2.0a1 also installed top-level
  `benchmark`, `query`, `graph` and `ingestion` packages, which could clash with other packages
  of the same name. They stay in the repository for the harnesses and tests.
- `ask(explain=True)` now reports, for each attempt, the model's query (`model_query`), the
  repairs made (`repairs`), the query run, and any error or feedback.
- New: `CHANGELOG.md`, `CONTRIBUTING.md`, `CITATION.cff`, `examples/integration_demo/`, and a
  release workflow that publishes through PyPI Trusted Publishing after a manual approval.

## Benchmark harness

- `--provider gemini` for the CypherBench and MetaQA NL→Cypher harnesses (key read from
  `GEMINI_API_KEY`, sent as a header, never stored).
- `--correct-directions` and `--pipeline` modes, written to separate results files.
- `--exclude-sample-seed` draws a dev sample disjoint from the test sample.
- Result files no longer mark the commit stamp `+dirty`.

## Measured accuracy

| Benchmark | Result |
| --- | --- |
| openCypher TCK `2024.3` | 3,879 / 3,879 supported scenarios pass (18 excluded); unchanged by this release |
| CypherBench, gold queries vs Neo4j answers (2,348 questions, measured at `43cab07`) | 98.21% official execution accuracy; 100% counting tied `ORDER BY` rows as matches |
| Test suite | 394 / 394 |
