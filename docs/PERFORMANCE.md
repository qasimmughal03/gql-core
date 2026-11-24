# GQL-Core Performance Benchmark v1

How fast the **published** `gql-core` package answers queries, how much memory a graph takes,
and how both scale, measured against hand-written Python, SQLite and NetworkX on identical data.

## What was measured, and what was not

| Part | Status |
| --- | --- |
| Latency of 26 workloads on a 10,000-node / 53,735-relationship graph, all four systems | **Measured.** Every answer verified against the oracle |
| Graph memory at 10k, 100k and 300k nodes, all three systems | **Measured.** Consistent per element across sizes |
| Inference scaling on isolated hierarchies of 250 to 2,000 companies | **Measured** |
| Latency at 100,000 nodes | **Run, but not valid.** The machine slowed down partway through: about 0.8 GB of RAM was free and Docker Desktop restarted WSL during the run. From `W07b` on, SQLite and plain Python slowed 15–109× for 10× the data, which the work cannot explain. The raw results are kept in `size_100000.json`, marked `"valid": false`, and are not used below |
| Latency at 300,000 nodes | **Not measured.** Stopped when the machine began paging (7,400 pages/s, 0.4 GB free) |
| 1M-node stress test, Neo4j baseline | Not attempted |

So the latency numbers below describe one size, 10k nodes, and scaling beyond it is **not yet
measured**. Re-running `--all` on a machine with about 6 GB free and nothing else running
completes the profile.

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

## Method

**Correctness before timing.** Every system's answer to every workload is compared with an
oracle before it is timed: plain Python over the generator's records, following openCypher
semantics. For example, the oracle enumerates variable-length matches as *trails*, so no
relationship repeats. A system that returns a different answer is recorded as `wrong_result`
and is not timed. In every run, every system returned the oracle's answer for every workload.

**Engine under test.** `gql-core==0.2.0a4` installed from PyPI into a clean environment, run
through `benchmark/run_published.py`, which refuses to run if `gql_core` would come from the
checkout. Each results file records the version, `installed package`, `package index (PyPI)`
and the SHA-256 of the installed files.

**Timing.**
- Warm-up: 2 runs, or 1 if a run takes more than 2 s, or none if it takes more than 20 s.
- Samples: runs are repeated until 200 samples or a 5 s budget per workload and system, with at
  least 5 samples (3 if a run takes more than 20 s).
- Reported: median, p25, p75, p90, minimum, maximum, mean and standard deviation. p95 only with
  at least 20 samples, and p99 only with at least 100; otherwise `null`, not estimated.
- Stages: GQL-Core's openCypher path is also timed stage by stage (parse, validate, plan,
  execute), using the same internal functions in the same order as `gql_core.run`. The table
  shows which path each query takes: `planner`, or `pipeline` for multi-clause queries. Typed
  plans are timed as build, validate and execute.
- Isolation: each graph size, each memory measurement and the inference series run in their own
  process. Everything runs single-threaded.

**Memory.** The change in resident set size while one system builds the graph from the same
records, in a fresh process per system and size.

| System | Data representation | Indexes | Notes |
| --- | --- | --- | --- |
| GQL-Core 0.2.0a4 | `PropertyGraph`: node and edge dicts, per-node adjacency lists, label index | Label index only; no property index | Every `run()` parses, validates and plans again, with no plan cache |
| Python | Dicts built from the same records | Hand-built: by id, by relationship type, by company | The oracle itself: what a careful hand-written implementation costs |
| SQLite 3.50.4 (in memory) | One table per entity, two edge tables, foreign keys as columns | Primary keys and foreign keys, `ANALYZE` | Recursive CTEs for paths and inference; no index on `age` or `score`, matching GQL-Core |
| NetworkX 3.5 | One `DiGraph` per relationship type, plus a node-attribute graph | Adjacency dicts | Used only where its API expresses the workload directly |

All systems run in the same process with no network. Neo4j is not included: it was not
installed, and a fair comparison would need its server, driver round trips and JVM warm-up
controlled separately.

## Results

<!-- generated by benchmark/perf/report.py from benchmark/results/perf/perf_v1.json -->

### Environment

| | |
| --- | --- |
| Engine | gql-core 0.2.0a4, installed package from package index (PyPI) (`<env>/Lib/site-packages/gql_core`) |
| Installed files (RECORD sha256) | `7cb51adcbd85b533…` |
| Harness commit | `3dd6d90` |
| Python | CPython 3.14.7 |
| OS | Windows 11 (10.0.26300) |
| CPU | 13th Gen Intel(R) Core(TM) i5-1345U, 12 logical CPUs (single-threaded runs) |
| RAM | 15.6 GB |
| Baselines | SQLite 3.50.4 (in memory), NetworkX 3.5 |
| Workloads / generator | v1.0 / v1.0, seed 42 |

### Graphs, load time and memory

| Nodes | Relationships | KNOWS out-degree mean / p99 / max | GQL-Core load (`from_dict`) | GQL-Core load (`add_node`/`add_edge`) | SQLite load + indexes | NetworkX load |
| ---: | ---: | --- | ---: | ---: | ---: | ---: |
| 10,000 | 53,735 | 3.702 / 18 / 300 | 0.24 s | 0.12 s | 0.09 s | 0.13 s |
| 100,000 | 521,961 | 3.533 / 18 / 300 | not valid | not valid | not valid | not valid |

| Nodes | GQL-Core | SQLite (in memory) | NetworkX | GQL-Core bytes per node or relationship |
| ---: | ---: | ---: | ---: | ---: |
| 10,000 | 28 MB | 5 MB | 16 MB | 464 |
| 100,000 | 249 MB | 32 MB | 168 MB | 419 |
| 300,000 | 707 MB | 100 MB | 487 MB | 398 |

Latency tables are given only for valid runs. Excluded, with their raw results kept in the JSON: 100,000 nodes.

### Latency, 10,000 nodes / 53,735 relationships

Median (p95 where at least 20 samples). Every cell is a verified-correct answer.

| Workload | Category | Rows | GQL-Core | Python (dict indexes) | SQLite | NetworkX | GQL-Core path |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `W01_lookup` | exact property lookup | 1 | 10 ms (15 ms) | 0.3 µs | 2.4 µs | 0.4 µs | planner |
| `W02a_label_count` | label scan | 1 | 1.8 ms (3.5 ms) | 0.2 µs | 1.6 µs | 2.5 ms | planner |
| `W02b_label_rows` | label scan | 20 | 0.26 ms (0.56 ms) | 1.8 µs | 0.02 ms | – | planner |
| `W03a_filter_selective` | predicate filtering | 18 | 9.4 ms (13 ms) | 0.34 ms | 0.29 ms | – | pipeline |
| `W03b_filter_broad_count` | predicate filtering | 1 | 104 ms (202 ms) | 0.52 ms | 0.36 ms | – | pipeline |
| `W03c_filter_broad_rows` | predicate filtering | 6,092 | 30 ms (43 ms) | 0.70 ms | 3.1 ms | – | planner |
| `W04a_hop_typical` | single-hop traversal | 4 | 10 ms (15 ms) | 0.4 µs | 3.2 µs | 0.6 µs | planner |
| `W04b_hop_hub` | single-hop traversal | 300 | 9.9 ms (14 ms) | 8.6 µs | 0.11 ms | 9.8 µs | planner |
| `W05a_two_hop_distinct` | multi-hop traversal | 8 | 30 ms (48 ms) | 0.01 ms | 0.01 ms | 1.9 µs | pipeline |
| `W05b_three_hop_count` | multi-hop traversal | 1 | 32 ms (55 ms) | 0.02 ms | – | – | pipeline |
| `W06a_var_len_1_3` | variable-length path | 1 | 29 ms (42 ms) | 0.02 ms | 0.12 ms | 0.01 ms | pipeline |
| `W06b_var_len_unbounded` | variable-length path | 5 | 0.92 ms (2.1 ms) | 0.8 µs | 0.01 ms | 6.0 µs | planner |
| `W07a_join_coworkers` | multi-pattern join | 1 | 24 ms (49 ms) | 0.2 µs | 3.6 µs | 1.2 µs | pipeline |
| `W07b_join_full_graph` | multi-pattern join | 1 | 295 ms | 1.2 ms | 9.1 ms | – | pipeline |
| `W08a_group_industry` | aggregation and grouping | 8 | 120 ms (166 ms) | 5.0 ms | 17 ms | – | planner |
| `W08b_group_city_top5` | aggregation and grouping | 5 | 95 ms (129 ms) | 1.6 ms | 0.54 ms | – | planner |
| `W09_sort_limit` | sorting and limits | 10 | 35 ms (93 ms) | 1.6 ms | 0.46 ms | – | planner |
| `W10a_exists` | correlated existence | 1 | 63 ms (83 ms) | 1.1 ms | 6.4 ms | – | pipeline |
| `W10b_not_exists` | correlated existence | 1 | 247 ms (281 ms) | 0.97 ms | 2.7 ms | – | pipeline |
| `W11a_at_least` | quantified relationship predicate | 63 | 87 ms (111 ms) | 1.0 ms | 3.7 ms | – | typed_plan |
| `W11b_all` | quantified relationship predicate | 186 | 13 ms (28 ms) | 0.25 ms | 0.35 ms | – | typed_plan |
| `W12a_typed_filter` | typed-plan execution | 18 | 77 ms (100 ms) | 0.37 ms | – | – | typed_plan |
| `W12b_typed_hop` | typed-plan execution | 4 | 4.5 ms (7.8 ms) | 0.3 µs | – | – | typed_plan |
| `W13_transitive_inference` | ontology transitive inference | 1 | 567 ms | 0.65 ms | 3.4 ms | 4.7 ms | inference |
| `W14b_derived_via_var_len` | derived relation query | 1 | 3.4 ms (5.3 ms) | 0.7 µs | – | – | pipeline |
| `W14a_derived_query` | derived relation query | 1 | 3.3 ms (5.6 ms) | 0.8 µs | – | – | pipeline |

### Where GQL-Core's time goes (median per stage)

**10,000 nodes**

| Workload | Path | Parse | Validate | Plan | Execute | Parse share |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `W01_lookup` | planner | 0.54 ms | 0.05 ms | 0.02 ms | 8.2 ms | 6.1% |
| `W02a_label_count` | planner | 0.61 ms | 0.05 ms | 0.04 ms | 3.3 ms | 15.3% |
| `W02b_label_rows` | planner | 0.18 ms | 0.02 ms | 0.01 ms | 0.03 ms | 72.5% |
| `W03a_filter_selective` | pipeline | 0.51 ms | 0.06 ms | 0.0 µs | 9.1 ms | 5.3% |
| `W03b_filter_broad_count` | pipeline | 0.57 ms | 0.06 ms | 0.0 µs | 101 ms | 0.6% |
| `W03c_filter_broad_rows` | planner | 0.51 ms | 0.06 ms | 0.03 ms | 20 ms | 2.5% |
| `W04a_hop_typical` | planner | 0.55 ms | 0.05 ms | 0.02 ms | 8.8 ms | 5.8% |
| `W04b_hop_hub` | planner | 0.40 ms | 0.03 ms | 0.02 ms | 5.8 ms | 6.4% |
| `W05a_two_hop_distinct` | pipeline | 0.66 ms | 0.05 ms | 0.0 µs | 36 ms | 1.8% |
| `W05b_three_hop_count` | pipeline | 0.72 ms | 0.04 ms | 0.0 µs | 32 ms | 2.2% |
| `W06a_var_len_1_3` | pipeline | 0.64 ms | 0.04 ms | 0.0 µs | 29 ms | 2.2% |
| `W06b_var_len_unbounded` | planner | 0.54 ms | 0.04 ms | 0.02 ms | 0.82 ms | 37.8% |
| `W07a_join_coworkers` | pipeline | 0.65 ms | 0.04 ms | 0.0 µs | 29 ms | 2.2% |
| `W07b_join_full_graph` | pipeline | 1.2 ms | 0.07 ms | 0.0 µs | 449 ms | 0.3% |
| `W08a_group_industry` | planner | 0.82 ms | 0.08 ms | 0.03 ms | 105 ms | 0.8% |
| `W08b_group_city_top5` | planner | 0.74 ms | 0.08 ms | 0.03 ms | 84 ms | 0.9% |
| `W09_sort_limit` | planner | 0.60 ms | 0.07 ms | 0.03 ms | 45 ms | 1.3% |
| `W10a_exists` | pipeline | 0.64 ms | 0.04 ms | 0.0 µs | 62 ms | 1.0% |
| `W10b_not_exists` | pipeline | 0.53 ms | 0.05 ms | 0.0 µs | 226 ms | 0.2% |
| `W14b_derived_via_var_len` | pipeline | 0.60 ms | 0.05 ms | 0.0 µs | 2.4 ms | 19.4% |
| `W14a_derived_query` | pipeline | 0.70 ms | 0.06 ms | 0.0 µs | 2.8 ms | 19.6% |

### Typed plan vs the same query in openCypher

| Nodes | Typed plan | Build + validate | Execute | openCypher twin | Parse + validate + plan | Execute |
| ---: | --- | ---: | ---: | --- | ---: | ---: |
| 10,000 | `W12a_typed_filter` | 0.07 ms | 71 ms | `W03a_filter_selective` | 0.57 ms | 9.1 ms |
| 10,000 | `W12b_typed_hop` | 0.05 ms | 3.9 ms | `W04a_hop_typical` | 0.62 ms | 8.8 ms |

### Inference

Transitive `SUBSIDIARY_OF` closure with `InferenceEngine` on the full benchmark graph (every node and relationship becomes a fact), and the derived-edge query against its variable-length twin:

| Nodes | Derived facts | Inference | SQLite recursive CTE | NetworkX | Default `max_facts` derives | Materialize | `W14a` derived edges | `W14b` variable-length |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 | 2,030 | 567 ms | 3.4 ms | 4.7 ms | 2,030 | 0.4 s | 3.3 ms | 3.4 ms |

Inference alone, on hierarchies with no other facts:

| Companies | Asserted edges | Derived facts | Correct | Median | Derived facts per second |
| ---: | ---: | ---: | :---: | ---: | ---: |
| 250 | 225 | 485 | yes | 113 ms | 4,294 |
| 500 | 450 | 1,146 | yes | 654 ms | 1,752 |
| 1,000 | 900 | 2,528 | yes | 2.32 s | 1,092 |
| 2,000 | 1,800 | 5,682 | yes | 10.91 s | 521 |

## Interpretation

**1. Where is GQL-Core competitive?** It isn't competitive with SQLite anywhere. At 10k nodes it
comes closest on scan-heavy work: returning 6,092 filtered rows (`W03c`, 30 ms against 3.1 ms),
grouping by industry (`W08a`, 120 ms against 17 ms) and an `EXISTS` subquery per company
(`W10a`, 63 ms against 6.4 ms). Each is within 7–13×. It beats NetworkX at counting a label
(`W02a`, 1.8 ms against 2.5 ms), because NetworkX has no label index and scans every node. For
point queries it is 3,000–7,000× slower than SQLite (`W01`, `W04a`, `W07a`).

**2. What dominates execution time?**
- **Finding the start node.** There is no property index. A lookup by `id` (`W01`), one hop from
  a typical person (`W04a`, 4 rows) and one hop from a hub (`W04b`, 300 rows) all take about
  10 ms. The traversal itself is not the cost; scanning about 9,000 `Person` nodes to find the
  start is. The same unbounded path from a `Company`, a label with about 830 nodes, takes 0.9 ms
  (`W06b`).
- **The row-at-a-time pipeline executor.** It handles multi-pattern, multi-hop, `EXISTS` and
  compound-`WHERE` queries. Counting `age < 60 AND active` (`W03b`, pipeline) takes 104 ms,
  while returning all 6,092 people under 60 (`W03c`, planner) takes 30 ms. The negated pattern
  predicate (`W10b`) is the slowest single-graph query, at 247 ms.
- **Per-row cost.** Aggregation and full joins cost about 10–30 µs per input row (`W08a`,
  `W07b`).

**3. Parsing against execution.** Parse, validate and plan take a median of 0.6 ms at 10k nodes,
2.2% of a query's time. They matter only for tiny queries: 72% of `W02b`, which returns 20
cities in 0.26 ms. There is no plan cache, so repeating a query repeats that cost, but caching
would save at most about 0.6 ms a query.

**4. Throughput against graph size.** At 10k nodes, a single thread answers about 100 point
queries a second, 30–40 multi-hop queries, and 3–10 whole-graph joins or aggregations. **Scaling with
size is not yet measured validly** (see the status table). Two facts bound it. Point queries
are label scans, so they grow at least linearly with the label's size. On the CypherBench graphs
(up to 885k nodes, 1.9M relationships), the median gold query took about 0.2 s, and the slowest
took minutes ([NL_BENCHMARKS.md](NL_BENCHMARKS.md)).

**5. Memory cost.** About **400–460 bytes per node or relationship**: 464 at 10k, 419 at 100k
and 398 at 300k, which is 707 MB for a 300k-node, 1.56M-relationship graph. That is 1.5× as
much as NetworkX (about 270–280 bytes) and 5–8× as much as SQLite in memory (about 55 bytes).

**6. Recursive traversal.** On its own it isn't the expensive part. `KNOWS*1..3` (`W06a`,
29 ms) costs the same as fixed two- and three-hop patterns (`W05a`, `W05b`, 30–32 ms), and all
three are dominated by finding the start node and by pipeline overhead. SQLite's recursive CTE
takes 0.12 ms, and NetworkX's breadth-first search 0.01 ms.

**7. Do typed plans reduce compilation overhead?** Yes, by about 10×: building and validating a
plan takes 0.05–0.07 ms, against 0.6 ms to parse, validate and plan the same query in Cypher.
But that saves only about 0.5 ms. Execution decides latency, and here typed plans are mixed. The
typed hop (`W12b`, 4.5 ms) is about twice as fast as its Cypher twin, while the typed filter
(`W12a`, 77 ms) is **8× slower** than Cypher's (`W03a`, 9.4 ms). The typed-plan physical
operators evaluate filters much more slowly than the Cypher executor does.

**8. How does inference scale?**
- On the whole 10k graph, the transitive closure takes 567 ms for 2,030 derived facts, because
  all 63,735 nodes and relationships become facts first. SQLite's recursive CTE takes 3.4 ms,
  and NetworkX 4.7 ms.
- On isolated hierarchies it grows about **quadratically**: 0.11 s for 250 companies, 0.65 s
  for 500, 2.3 s for 1,000 and 10.9 s for 2,000. When an index key is absent, rule evaluation
  scans every fact (see the findings below).
- With the default `max_facts`, inference on the 100k graph derives **1 fact instead of
  28,041**, without warning. This is a correctness-affecting default; the count, not the
  timing, comes from the 100k run.
- Queries over the materialized derived edges (`W14a`, 3.3 ms) cost the same as the
  variable-length query they replace (`W14b`, 3.4 ms) at this depth.

**9. Value over plain Python or NetworkX.** The value isn't speed: hand-written dict code is 20
to 120,000× faster for the same answer, and NetworkX is comparable where it applies. GQL-Core's
value is what you don't have to write or verify yourself:
- declarative openCypher (3,879/3,879 supported TCK scenarios; 2,348/2,348 CypherBench gold
  answers correct);
- variable-length trail semantics, `EXISTS`, `OPTIONAL MATCH`, aggregation and typed plans an
  agent can build and validate;
- rule inference with provenance.

The reference application shows the trade. Its impact analysis is a few queries and rules, and
it answers in milliseconds on a realistic catalog. For graphs of thousands to tens of thousands
of elements and interactive use, the latencies measured here (0.3–300 ms per query) are workable. For
point lookups at scale, or whole-graph analytics on hundreds of thousands of elements, they are
not.

**10. The most important limitations for real developers.**
- **No property index.** Every lookup by a property is a scan, so cost grows with the label's
  size.
- **About half of query shapes run on the slow pipeline executor:** multi-pattern, multi-hop,
  `EXISTS` and compound `WHERE`.
- **Memory:** about 400 bytes per element. A 1M-node, 5M-relationship graph needs about 2.5 GB.
- **Inference:** a silent `max_facts` cut-off, quadratic behaviour when an index key is
  missing, and no semi-naive evaluation.
- **No plan cache, no parameters and no `shortestPath()`.**
- **The typed-plan filter executor** is slower than the Cypher one.
- **Machine sensitivity:** on battery, the same queries ran about 2.5–4× slower (CypherBench
  timeouts, inference series).

### Optimization candidates (not done; no engine changes in this workstream)

1. A property index, or at least an `id` index, for start-node selection. This is the largest
   single win for point queries.
2. Treat an absent argument-index key as zero candidates in `_evaluate_rule_body`; count only
   derived facts against `max_facts`, or warn when the limit is reached; semi-naive evaluation.
3. Move multi-pattern, `EXISTS` and compound-`WHERE` queries onto the planner, or batch the
   pipeline executor.
4. Bring the typed-plan filter evaluation up to the Cypher executor's speed.
5. A parse and plan cache keyed by query text.
6. A more compact node and edge representation (`__slots__`, adjacency split by relationship
   type).

## Findings from building the harness

- **Silent inference cut-off.** The default `max_facts=250_000` counts stored facts, one per node
  and one per relationship. On a larger graph, `infer()` returns after deriving a single fact.
- **Quadratic rule evaluation.** In `_evaluate_rule_body`, looking up an index key that doesn't
  exist returns `None`, which the code treats as "no index". It then scans every fact of the
  predicate, instead of returning no candidates. Answers stay correct.
- **`PlanBuilder.expand()` after `.filter()` needs an explicit `from_var=`.** Otherwise the
  builder falls back to `'a'`, and validation rejects the plan.

## Running it

```bash
python -m venv .venv-pub
.venv-pub/bin/pip install "gql-core[benchmark]==0.2.0a4" networkx psutil
PYTHONHASHSEED=0 .venv-pub/bin/python benchmark/run_published.py benchmark.perf.run_perf --all --sizes 10000 100000 300000
python benchmark/perf/report.py        # Markdown tables from benchmark/results/perf/perf_v1.json
```

Use a machine on mains power with about 6 GB free and nothing else running. Stop Docker Desktop
and WSL first; Docker restarts WSL on its own. Results files per part are in
`benchmark/results/perf/`, and a part marked `"valid": false` says why.
