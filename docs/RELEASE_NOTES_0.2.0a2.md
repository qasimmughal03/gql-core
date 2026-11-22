# GQL-Core 0.2.0a2 release notes

**Stage:** alpha · **License:** Apache-2.0 · **Python:** 3.11+ · **Previous:** [0.2.0a1](RELEASE_NOTES_0.2.0a1.md)

This release fixes the engine gaps found by running the published CypherBench benchmark, and
documents GQL-Core's measured accuracy on published benchmarks.

## Engine fixes

Running all 2,348 CypherBench test-split gold queries against Neo4j's answers found these gaps.
Each now has a regression test in `tests/test_cypherbench_regressions.py`.

- **`CALL { … }` subqueries** are supported, including `UNION` inside the subquery and
  correlated subqueries that begin with `WITH`.
- **Keywords are case-insensitive**, so `RETURN n, m0 as m` now parses.
- **`ORDER BY` on a missing property after `WITH`** sorts the value as null. Previously it
  sorted by the node itself.
- **Chained comparisons no longer depend on earlier queries.** Parser state keyed by object
  identity leaked from one parse to the next.
- **Pattern matching starts from the most selective node.** Previously a pattern always started
  at its leftmost node, so `(n)-->(m)<--(x {name: 'A'})` scanned every `n` and timed out on large
  graphs. Matching now starts at a bound node with the fewest relationships, then a
  property-filtered node, then the smallest label, and walks the pattern in both directions from
  it. Named paths, variable-length steps and filters that refer to other pattern variables keep
  left-to-right order. This removed every CypherBench timeout; geography went from 80.6% to 98.4%.
- **Simple `WHERE` equalities also choose the start node.** `WHERE c.name = 'X'` and
  `WHERE c.name IN [...]` are now used like an inline `{name: 'X'}` to pick where matching
  starts and to prune that node's candidates. The full `WHERE` is still applied to every match,
  so results are unchanged. This removed the timeouts on model-written CypherBench queries.

## Measured accuracy

| Benchmark | Result |
| --- | --- |
| openCypher TCK `2024.3` | 3,879 / 3,879 supported scenarios pass (18 excluded) |
| CypherBench, gold queries vs Neo4j answers (2,348 questions, 7 graphs) | 98.21% official execution accuracy; 100% counting tied `ORDER BY` rows as matches; no errors or timeouts |
| CypherBench NL→Cypher, `qwen2.5-coder:3b` via Ollama, zero-shot | 13.3% execution accuracy on 210 seeded questions (30 per graph); 92.4% of generated queries run, and every one that does not is invalid Cypher |
| MetaQA via Cypher, same model (100 questions per hop) | 1-hop 67% exact match; 2-hop 0%; 3-hop 0% |
| Hetionet v1.0 (own evaluation against independent ground truth) | 6 / 6 checks agree |
| Test suite | 355 / 355 |

Natural-language accuracy depends mainly on the LLM you connect. The numbers above come from a
deliberately small 3B model and are a baseline. Methodology and per-category results:
[NL_BENCHMARKS.md](NL_BENCHMARKS.md).

## Benchmark harness changes

- New harnesses `benchmark/cypherbench` and `benchmark/metaqa`, with a local Ollama client.
  `huggingface_hub` is added to the `benchmark` extra.
- The earlier self-graded "domain" and "industry" benchmark scripts are removed. Their NL layer
  scored a translator that returned the gold query, and their data was invented. The programs in
  `examples/domains/` remain as API demonstrations, not accuracy evidence.
- Result files record `+dirty` next to the commit hash when produced from uncommitted code.
- A query that exceeds the benchmark timeout is now stopped. Previously it kept running in the
  background and slowed the queries after it.

## Documentation

The README has a new *Accuracy and benchmarks* section, installs from PyPI, and uses absolute
links so they work on the PyPI project page.
