# Changelog

All notable changes to GQL-Core. Versions follow [PEP 440](https://peps.python.org/pep-0440/);
while the version is `0.x`, an alpha release may change the API. Full details for each release
are in `docs/RELEASE_NOTES_<version>.md`.

Benchmark datasets, prompts and evaluation harnesses are versioned with their results (the
commit stamped in each results file), not with the package: a new benchmark run does not by
itself produce a new GQL-Core release.

## [Unreleased]

### Fixed
- A pattern predicate or `EXISTS { … }` could not use a relationship that the enclosing `MATCH`
  had already matched, so `MATCH (a)-[:KNOWS]->(b) WHERE EXISTS { (a)-[:KNOWS]->(b) }` returned
  nothing.

### Changed
- The repository moved to [`qasimmughal03/gql-core`](https://github.com/qasimmughal03/gql-core);
  links updated.

## [0.2.0a3] - 2026-11-23

First PyPI release since 0.2.0a1. It includes everything in 0.2.0a2.

### Added
- `ask()` and `translate_to_gql()` check the generated query against the graph by default:
  - `correct_relationship_directions()` reverses arrows the schema forbids;
  - `ground_values()` replaces string literals that match one stored value when case is ignored;
  - the schema prompt lists stored values of low-cardinality properties;
  - a query that fails, returns no rows or returns duplicate rows gets one retry with
    execution feedback.
- `ask(explain=True)` reports, for each attempt, the model's query, the repairs made, the query
  run, and any error or feedback.
- `examples/integration_demo/`: an impact-analysis application that uses GQL-Core from PyPI.
- `CHANGELOG.md`, `CONTRIBUTING.md`, `CITATION.cff`.

### Fixed
- `EXISTS { … }` was left unparsed, so `EXISTS` returned no rows and `NOT EXISTS` every row.
  `exists((pattern))` and `exists(n.prop)` now work too.
- Expanding to a label matched only a node's first label.
- `[:a|b]` relationships matched nothing in queries using `DISTINCT`, `WITH` or
  `count(DISTINCT …)`.
- Result column names were read from a `RETURN` inside `CALL { }` or `EXISTS { }`.
- `WHERE n.date.year = 2010` as the only condition matched nothing.

### Changed
- The wheel contains only the `gql_core` package. 0.2.0a1 also installed top-level `benchmark`,
  `query`, `graph` and `ingestion` packages, which could clash with other packages; they remain
  in the repository for the benchmark harnesses and tests.

## [0.2.0a2] - 2026-11-22 (tagged, not published to PyPI)

### Added
- CypherBench engine-parity and NL→Cypher harnesses; MetaQA NL→Cypher harness.

### Fixed
- `CALL { … }` subqueries, including `UNION` inside them.
- Case-insensitive keywords.
- `ORDER BY` on a missing property after `WITH` sorts as null.
- Parser state leaked between parses through `id()`-keyed markers.
- Pattern matching starts at the most selective node; `WHERE` equalities choose the start node.
  This removed every CypherBench timeout.

### Removed
- Self-graded domain benchmarks. Only published benchmarks, or checks against independently
  computed ground truth, are reported.

## [0.2.0a1] - 2026-11-17

First public alpha on PyPI: in-memory property graph, Cypher text queries, typed query plans,
ontology inference, optional natural-language interface, openCypher TCK and LDBC SNB harnesses.

[Unreleased]: https://github.com/qasimmughal03/gql-core/compare/v0.2.0a3...HEAD
[0.2.0a3]: https://github.com/qasimmughal03/gql-core/compare/v0.2.0a2...v0.2.0a3
[0.2.0a2]: https://github.com/qasimmughal03/gql-core/compare/v0.2.0a1...v0.2.0a2
[0.2.0a1]: https://github.com/qasimmughal03/gql-core/releases/tag/v0.2.0a1
