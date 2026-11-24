# GQL-Core 0.2.0a4 release notes

**Stage:** alpha · **License:** Apache-2.0 · **Python:** 3.11+ · **Previous:** [0.2.0a3](RELEASE_NOTES_0.2.0a3.md)

A bug-fix release.

## Fixed

- **`EXISTS` and pattern predicates can use a relationship the enclosing `MATCH` already
  matched.** Relationship uniqueness applies within one pattern, and a predicate is a separate
  pattern. The enclosing match's used relationships were passed into the predicate, so these
  queries returned no rows, and their `NOT` forms returned every row:

  ```cypher
  MATCH (a)-[:KNOWS]->(b) WHERE EXISTS { (a)-[:KNOWS]->(b) } RETURN b
  MATCH (a)-[:KNOWS]->(b) WHERE (a)-[:KNOWS]->(b) RETURN b
  MATCH (a)-[:KNOWS]->(b) WHERE exists((a)-[:KNOWS]->(b)) RETURN b
  ```

  The bug predates 0.2.0a3 and was found by a smoke test of the published 0.2.0a3 wheel. A
  regression test is in `tests/test_cypherbench_regressions.py`.

## Changed

- The repository moved to [`qasimmughal03/gql-core`](https://github.com/qasimmughal03/gql-core).
  Package metadata and documentation links point there; old links redirect.

## Measured accuracy

| Benchmark | Result |
| --- | --- |
| openCypher TCK `2024.3` | 3,879 / 3,879 supported scenarios pass (18 excluded); unchanged |
| Test suite | 395 / 395 |

At release, the CypherBench and MetaQA results in the README came from the 0.2.0a3 engine. They
have since been re-run against this release, installed from PyPI. The NL results are identical,
and the CypherBench gold check is 98.00% strict and 100% semantic. See
[NL_BENCHMARKS.md](NL_BENCHMARKS.md).
