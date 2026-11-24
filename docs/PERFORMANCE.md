# GQL-Core Performance Benchmark v1

How fast the **published** `gql-core` package answers queries, how much memory a graph takes,
and how both scale, measured against hand-written Python, SQLite and NetworkX on identical data.

> **Status:** the harness is complete and was smoke-tested on a 10,000-node graph, where every
> workload returned the oracle's answer on every system. The full measurement (10k, 100k and
> 500k nodes) has not been run yet. Tables are added here only from a full run's
> `benchmark/results/perf/perf_v1.json`; see [Running it](#running-it).

## What is measured

| Category | Workload ids | Notes |
| --- | --- | --- |
| Exact property lookup | `W01` | One person by `id`. GQL-Core has no property index, so this is a label scan with a filter |
| Label scan | `W02a`, `W02b` | Count all companies; return every city id |
| Predicate filtering | `W03a`–`W03c` | 0.16% selectivity, about 53% counted, about 67% returned row by row |
| Single-hop traversal | `W04a`, `W04b` | From a typical person (out-degree 4) and from a hub (out-degree 300) |
| Multi-hop traversal | `W05a`, `W05b` | Distinct friends-of-friends; distinct people exactly 3 hops away |
| Variable-length paths | `W06a`, `W06b` | `KNOWS*1..3`; unbounded `SUBSIDIARY_OF*` up a company hierarchy |
| Multi-pattern joins | `W07a`, `W07b` | Co-workers of one person; a three-pattern join over the whole graph |
| Aggregation and grouping | `W08a`, `W08b` | Per-industry count and average; top five cities |
| Sorting and limits | `W09` | Top 10 by a unique score |
| Correlated existence | `W10a`, `W10b` | `EXISTS { }` subquery; negated pattern predicate |
| Quantified relationship predicates | `W11a`, `W11b` | `AT_LEAST` and `ALL` in typed plans |
| Typed-plan execution | `W12a`, `W12b` | Typed-plan twins of `W03a` and `W04a` |
| Ontology transitive inference | `W13` | Transitive `SUBSIDIARY_OF` closure with `InferenceEngine`, plus a separate scaling series |
| Derived relation queries | `W14a`, `W14b` | The same answer from materialized inferred edges and from a variable-length path |

Workload definitions: [`benchmark/perf/workloads.py`](../benchmark/perf/workloads.py)
(version 1.0). Unsupported operations are not benchmarked. `shortestPath()` is not in
0.2.0a4, for example, so no workload uses it.

## Data

[`benchmark/perf/generate.py`](../benchmark/perf/generate.py) (version 1.0, seed 42) builds
deterministic graphs in plain Python, without importing `gql_core`:

- `Person` (about 91% of nodes), `Company` (about 8.3%), `City` (about 0.2%, at least 10).
- `KNOWS` out-degree follows an exponential distribution with mean 4, capped at 200, and targets
  are skewed toward low-numbered people, so there are popular people. Five hubs know 300 people
  each. There are no self-loops and no duplicate pairs.
- Each person has exactly one `WORKS_AT` and one `LIVES_IN`, and each company has one
  `LOCATED_IN`.
- `SUBSIDIARY_OF` forms a forest in which company *i* reports to company ⌊(*i*−1)/4⌋, except
  every tenth company, which is a root.
- `score` is a permutation, so `ORDER BY score` has no ties.

Every results file records each graph's node and relationship counts by label, and its in- and
out-degree distributions.

## Correctness before timing

Every system's answer to every workload is compared with an oracle before it is timed: plain
Python over the generator's records, following openCypher semantics. For example, the oracle
enumerates variable-length matches as *trails*, so no relationship repeats. A system that returns
a different answer is recorded as `wrong_result` and is not timed for that workload. A baseline
is therefore only compared where it computes the same answer as GQL-Core.

## Timing protocol

- **Engine under test:** `gql-core==0.2.0a4` installed from PyPI into a clean environment and run
  through `benchmark/run_published.py`. The launcher refuses to run if `gql_core` would come from
  this checkout. Each results file records the version, `installed package`, `package index
  (PyPI)` and the SHA-256 of the installed files.
- **Warm-up:** 2 runs, or 1 if a run takes more than 2 s, or none if it takes more than 20 s.
- **Samples:** runs are repeated until 200 samples are collected or the time budget (5 s per
  workload and system) is used, with at least 5 samples (3 if a run takes more than 20 s). The
  results report the median, p25, p75, p90, minimum, maximum, mean and standard deviation. p95
  is reported only with at least 20 samples, and p99 only with at least 100. Otherwise they are
  `null`, not estimated.
- **Stages:** GQL-Core's openCypher path is also timed stage by stage (parse, validate, plan,
  execute), using the same internal functions in the same order as `gql_core.run`. The table
  shows which path each query takes: `planner`, or `pipeline` for multi-clause queries. Typed
  plans are timed as build, validate and execute.
- **Isolation:** each graph size, each memory measurement and the inference series run in their
  own process, so memory never carries over. Everything runs single-threaded on one machine,
  and the environment (CPU, RAM, OS, Python, SQLite and NetworkX versions, engine stamp) is
  recorded.
- **Memory:** the change in resident set size while one system builds the graph from the same
  records, in a fresh process per system and size.

## Baselines and their differences

| System | Data representation | Indexes | Notes |
| --- | --- | --- | --- |
| GQL-Core 0.2.0a4 | `PropertyGraph`: node and edge dicts, per-node adjacency lists, label index | Label index only; no property index | Every `run()` parses, validates and plans again, with no plan cache |
| Python | Dicts built from the same records | Hand-built: by id, by relationship type, by company | The oracle itself: what a careful hand-written implementation costs |
| SQLite (in memory) | One table per entity, two edge tables, foreign keys as columns | Primary keys and foreign keys (`knows.src`, `knows.dst`, `works_at.*`, `company.parent`, `person.city`), `ANALYZE` | Variable-length paths and inference use recursive CTEs; no index on `age` or `score`, matching GQL-Core |
| NetworkX 3.5 | One `DiGraph` per relationship type, plus a node-attribute graph | Adjacency dicts | Used only where its API expresses the workload directly |

Neo4j is not included: it was not installed on the measurement machine, and a fair comparison
would need its server, driver round trips and JVM warm-up controlled separately. No result here
claims GQL-Core is faster or slower than a system it was not measured against.

## Findings so far

These came out of building the harness and the reference application. They don't depend on the
full timing run:

- **Silent inference cut-off.** `InferenceEngine`'s default `max_facts=250_000` counts the graph's
  stored facts (one per node and one per relationship), not just the derived ones. On a graph with
  more than about 250,000 nodes plus relationships, `infer()` returns after deriving a single fact,
  with no error or warning. The benchmark passes `max_facts` explicitly, and records what the
  default does at each size.
- **Quadratic rule evaluation on facts with no outgoing edges.** In `_evaluate_rule_body`, looking
  up an argument index key that doesn't exist returns `None`, which the code treats as "no index".
  It then scans every fact of the predicate, instead of returning no candidates. In an isolated
  hierarchy, every derivation that reaches a root triggers that scan, and the time grows roughly
  with the square of the number of facts (1,000 companies: about 9 s). A graph whose roots also
  have other outgoing relationships doesn't hit the fallback. The answers stay correct, so this is
  an optimization candidate, not a correctness defect.
- **About half the queries bypass the planner.** In the smoke run, 11 of the 21 openCypher
  workloads ran on the row-at-a-time `pipeline` executor. They include every multi-pattern,
  multi-hop, `KNOWS*1..3`, `EXISTS` and compound-`WHERE` (`AND`) query. Execution, not parsing,
  dominates: parsing is 1–3 ms per query on the smoke-test graph.
- **No plan or parse cache.** Every `run()` parses and plans again. For selective queries on small
  graphs, parsing is a measurable share of the latency.
- **`PlanBuilder.expand()` after `.filter()` needs an explicit `from_var=`.** Otherwise the builder
  falls back to `'a'`, and validation rejects the plan as having an unbound variable.

## Running it

```bash
python -m venv .venv-pub
.venv-pub/bin/pip install "gql-core[benchmark]==0.2.0a4" networkx psutil
PYTHONHASHSEED=0 .venv-pub/bin/python benchmark/run_published.py benchmark.perf.run_perf --all --sizes 10000 100000 500000
python benchmark/perf/report.py        # Markdown tables from benchmark/results/perf/perf_v1.json
```

Use a machine on mains power with nothing else running. Laptop power management changes the
results by a large factor (see the CypherBench timeout note in
[NL_BENCHMARKS.md](NL_BENCHMARKS.md)).
