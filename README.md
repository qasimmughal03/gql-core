# Cricket Knowledge Graph with Formal Query

A property-graph database over Pakistan international cricket (data: [cricsheet.org](https://cricsheet.org/format/json/)) with a formally-specified, Lark-parsed subset of [GQL/Cypher](https://www.iso.org/standard/76120.html) and SHACL-style validation. Includes a SQLite mirror benchmark to demonstrate that graph-native querying with a formal grammar is more expressible for path/relational queries than equivalent SQL.

## Overview

Five-layer pipeline, strictly downward dataflow:

```
JSON files  ─►  Ingestion  ─►  Validation  ─►  Property Graph  ─►  Query Engine  ─►  Benchmark
                                                                      │
                                                                      └─►  Lark grammar (GQL-Core)
```

- **Ingestion** parses cricsheet match JSON ([format spec](https://cricsheet.org/format/json/)).
- **Validation** enforces SHACL-style shape constraints on every node and edge (W3C SHACL Recommendation).
- **Property Graph** is in-memory dict-of-dicts. The full Pakistan corpus (1,123 men's matches downloaded from cricsheet) materializes to **712K nodes / 1.47M edges** — most of that bulk is ball-by-ball Delivery nodes (706K of them) and the NEXT_DELIVERY chain (703K). The bundled test fixtures are 65 nodes / 112 edges.
- **Query Engine** parses a documented subset of [ISO/IEC 39075:2024 (GQL)](https://www.iso.org/standard/76120.html) — `MATCH ... WHERE ... RETURN` with regular path queries (RPQ) via path quantifiers and full aggregation (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`).
- **Benchmark** compares the engine vs SQLite on five canonical queries: latency, expressibility (token count + recursion), correctness.

Three concrete reasons the graph engine wins on path/relational queries:

1. **Path quantifiers vs recursive CTEs.** `[:NEXT_DELIVERY*1..3]` is one Cypher token; the SQL equivalent needs `WITH RECURSIVE chain(...) AS (... UNION ALL ...)` with an explicit depth guard.
2. **Undirected edges.** `(a)-[t:TEAMMATES_WITH]-(b)` is one pattern; SQL must `UNION ALL` the two endpoint orderings because the relation is stored canonically (`a < b`).
3. **Verifiable shapes.** Every node/edge passes through a SHACL-style validator before insertion — the database refuses to hold rows that violate the schema. There is no equivalent in SQL DDL beyond `NOT NULL` and `CHECK`.

## Quickstart

```bash
git clone https://github.com/qasimmughal03/knowledge-graoh-with-formal-query.git
cd knowledge-graoh-with-formal-query
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Live data (the full Pakistan corpus from cricsheet.org)
python scripts/download_cricsheet.py
python -m ingestion.cricsheet_parser data/pakistan
python scripts/build_sqlite_mirror.py
python -m benchmark.vs_sqlite              # writes benchmark/results/results.json

# Test suite (uses bundled fixtures, no network needed)
pytest --cov=. --cov-report=term-missing
```

## Ontology

### Nodes (7)

| Label | Required | Optional | ID source |
|---|---|---|---|
| Player | `id, name, country` | `dob, batting_style, bowling_style, role` | `info.registry.people[name]` (8-char hex), fallback `slug(name)` |
| Match | `id, date, format, gender, season` | `venue_id, city, team_type, balls_per_over, outcome_winner, outcome_method` | `Path(filename).stem` (cricsheet's stable numeric ID) |
| Venue | `id, name` | `city` | `slug(venue) + '@' + slug(city)`; either component → `'unknown'` if missing |
| Team | `id, name` | `country_code, type` | mapped country code (`PAK`, `ENG`, …) or `slug(name)` |
| Innings | `id, match_id, team_id, innings_idx` | `declared, forfeited, super_over, target_runs, target_overs` | `f'{match_id}:{innings_idx}'` |
| Delivery | `id, innings_id, over, ball, batter_id, bowler_id, runs_total` | `runs_batter, runs_extras, wicket_kind, player_out, fielders, extras_*` | `f'{match_id}:{innings_idx}:{over}.{ball_idx}'` |
| Tournament | `id, name` | `match_type, season` | `slug(info.event.name)`; node skipped when `info.event` absent |

`format` enum is taken verbatim from cricsheet: `Test`, `ODI`, `T20`, `IT20`, `ODM`, `MDM`. The `wicket_kind` enum lists all cricsheet-documented kinds (case- and space-sensitive: `caught and bowled`, `obstructing the field`, …).

### Edges (9)

| Label | Source | Target | Cardinality | Properties |
|---|---|---|---|---|
| PLAYED_FOR | Player | Team | M:N | `first_match_date, last_match_date` |
| BATTED_IN | Player | Match | M:N | `runs, balls_faced, fours, sixes` |
| BOWLED_IN | Player | Match | M:N | `overs, runs_conceded, wickets, maidens` |
| CAPTAINED | Player | Match | M:N | (none) |
| PLAYED_AT | Match | Venue | M:1 | (none) |
| TEAMMATES_WITH | Player | Player | undirected | `match_count` (canonical `src=min(id), dst=max(id)`) |
| IN_INNINGS | Delivery | Innings | M:1 | (none) |
| NEXT_DELIVERY | Delivery | Delivery | 1:1 | (none) |
| PART_OF_TOURNAMENT | Match | Tournament | M:1 | (none) |

Per-match BATTED_IN / BOWLED_IN aggregates are derived from the delivery walk:

- **Batter `balls_faced`** excludes wides; **`fours`** counts boundaries (`runs.batter == 4 and not non_boundary`); **`sixes`** counts `runs.batter == 6`.
- **Bowler `runs_conceded`** = `runs.batter + extras.wides + extras.noballs` (byes/legbyes are not charged to the bowler); **`wickets`** are credited only for `bowled`, `caught`, `lbw`, `stumped`, `hit wicket`, `caught and bowled` (run-outs and retirements are not credited per ICC convention); **`maidens`** = legal-ball-complete overs with zero runs charged.

`TEAMMATES_WITH` is materialized at ingestion: every same-team pair gets one canonical edge, and `match_count` increments for every additional shared match. Re-ingesting a match is idempotent — the graph carries a `seen_match_ids` set that short-circuits the materialization step.

## Query Language

`GQL-Core` is a documented subset of ISO/IEC 39075:2024 (GQL):

- `MATCH` patterns with multiple comma-separated path patterns (joined on shared variables).
- Directed (`-[]->`, `<-[]-`) and undirected (`-[]-`) edges.
- Quantifiers `*` (= `*1..∞` per Cypher convention), `+`, `*N`, `*M..N` over edges (RPQ).
- `WHERE` with `AND`, `OR`, `NOT`, parenthesization, and the comparison operators `= != < <= > >=`.
- Inline node-property filters: `(p:Player {country: "PAK"})`.
- Edge variable binding: `-[r:BATTED_IN]->`.
- `RETURN` projections, full aggregation (`COUNT`, `SUM`, `AVG`, `MIN`, `MAX`), aliasing (`AS`), `ORDER BY` (`ASC`/`DESC`), `LIMIT`.

The Lark grammar at [query/grammar.lark](query/grammar.lark) is the normative spec. Below is the parse tree of Q3 (the most-winning Pakistani captains query), as printed by [query/parser.py](query/parser.py)'s `parse_tree`:

```text
start
  query
    match_clause
      pattern
        node_pat
          p
          Player
        rel_out
          edge_label	CAPTAINED
        node_pat
          m
          Match
    where_clause
      or_expr
        and_expr
          not_expr
            atom_expr
              comparison
                ref
                  m
                  outcome_winner
                =
                str_val	"Pakistan"
          not_expr
            atom_expr
              comparison
                ref
                  p
                  country
                =
                str_val	"PAK"
    return_clause
      proj_ref
        ref
          p
          name
        alias	captain
      proj_agg
        agg_call
          COUNT
          ref	m
        alias	wins
      order_by
        ref	wins
        direction	DESC
      limit	5
```

The five canonical queries are paired with their SQL equivalents in [benchmark/queries.py](benchmark/queries.py).

## Benchmark

The harness runs **two classes** of paired Cypher / SQL queries on the same data, with strict row-set equality checked between engines:

1. **Direct queries (Q1–Q5)** in [benchmark/queries.py](benchmark/queries.py) — simple lookups, single-edge traversals, and one bounded RPQ. These verify the engine can answer ordinary relational questions correctly.
2. **Logical Reasoning Benchmark (LR1–LR5)** in [benchmark/logical_reasoning.py](benchmark/logical_reasoning.py) — conjunction over shared variables, transitive closure, multi-edge constraints, heterogeneous-path composition, RPQ with target-side filtering. These verify the engine can answer questions that *require* the graph model.

Each query runs `--iters 50` (default 100) on each engine. The harness substitutes `{start_id}` with an actual Delivery id from the loaded graph so the same query works on fixtures and on the full corpus. Reproduce with:

```bash
curl -sSL -o data/pakistan_json.zip https://cricsheet.org/downloads/pakistan_json.zip
unzip -q data/pakistan_json.zip -d data/pakistan/ && rm data/pakistan_json.zip
python scripts/build_sqlite_mirror.py
python -m benchmark.vs_sqlite --data data/pakistan --db data/cricket_male.db --iters 50
```

### Direct queries (Q1–Q5) — full Pakistan men's corpus, 712K nodes / 1.47M edges

| Query | Purpose | Cypher (ms) | SQL (ms) | SQL/Cypher tokens | Recursive SQL? | Match? |
|---|---|---:|---:|:---:|:---:|:---:|
| Q1 | Top run scorers | 32.5 | 8.6 | 29 / 15 (1.9×) | no | ✓ |
| Q2 | Best bowling at Karachi | 28.4 | 8.3 | 47 / 21 (2.2×) | no | ✓ |
| Q3 | Pakistani captain wins | 3.0 | 0.8 | 44 / 23 (1.9×) | no | ✓ |
| **Q4** | Babar's frequent partners (undirected) | **0.6** | **16.6** | 68 / 20 (3.4×) | no (`UNION ALL`) | ✓ |
| Q5 | Bounded RPQ on `NEXT_DELIVERY*1..3` | 382.8 | 0.01 | 53 / 13 (4.1×) | **yes** | ✓ |

### Logical Reasoning Benchmark (LR1–LR5) — same corpus

| Query | Reasoning pattern | Cypher (ms) | SQL (ms) | SQL/Cypher tokens | Recursive SQL? | Match? |
|---|---|---:|---:|:---:|:---:|:---:|
| LR1 | Conjunctive multi-pattern (all-rounders) | 619.9 | 128.0 | 49 / 24 (2.0×) | no | ✓ |
| **LR2** | Bounded transitive closure (2-hop teammates) | **2.3** | **1.9** | 108 / 15 (**7.2×**) | **yes** | ✓ |
| LR3 | Multi-edge constraint + threshold (Test centurions) | 22.1 | 0.7 | 44 / 25 (1.8×) | no | ✓ |
| LR4 | Heterogeneous-path composition (co-venue batters) | 117.0 | 78.3 | 74 / 28 (2.6×) | no | ✓ |
| LR5 | RPQ + target-side property filter | 382.9 | 34.0 | 55 / 14 (3.9×) | **yes** | ✓ |

Spot-check of logical-reasoning correctness on real data (verifiable against cricket history):

- **LR1 all-rounders top 3**: Shahid Afridi (163 matches), Mohammad Hafeez (146), Shoaib Malik (87) — textbook Pakistani all-rounders.
- **LR3 Test centurions top 3**: Younis Khan (32), Azhar Ali (23), Asad Shafiq (18) — matches the historical record (Younis Khan is Pakistan's all-time leading Test centurion).
- **LR4 Babar's co-venue batters top 3**: Mohammad Hafeez (1893 venue co-occurrences), Shoaib Malik (1813), Mohammad Rizwan (1689) — Pakistan's most-capped recent batters.

(Hardware: Apple Silicon, Python 3.11. Raw numbers: [benchmark/results/results.json](benchmark/results/results.json).)

### What this proves

- **Correctness**: 10 / 10 queries (Q1–Q5 + LR1–LR5) return `result_correct: true` — Cypher and SQL row-sets are identical after canonical sorting.
- **Expressibility**: every Cypher query is shorter than its SQL equivalent, by 1.8× to **7.2×** (LR2 — the SQL version needs `WITH RECURSIVE` with explicit `CASE` expressions to walk an undirected edge stored canonically).
- **Speed trade-offs**: SQLite's compiled query plan wins on aggregation-heavy queries (Q1, Q3, Q5, LR3) and on the RPQ + filter case (LR5) where its B-tree index on `prev_id` beats our Python BFS. Cypher wins big on **Q4** (undirected single-hop neighbor lookup, 26× faster than SQL's `UNION ALL`) — a structural property of the graph model: direct adjacency is one dictionary lookup, while SQL has to assemble the symmetric closure at query time.

## Limitations and Future Work

- **Out of scope (v1)**: full ISO 39075 (multi-clause queries with `WITH`, set quantifiers, schema-DDL); SHACL-SPARQL constraints (sub-query constraints); disk-backed graph store; LDBC SNB micro-benchmark; LLM hallucination comparison; `DISTINCT` keyword (the executor dedupes RPQ targets automatically, but `RETURN DISTINCT x` is not a parsed keyword); `EXISTS` / `NOT EXISTS` pattern predicates in WHERE.
- **Captain heuristic is unreliable**: cricsheet has no canonical per-match captain field. The parser uses the first-listed player on each team's roster for that match — so the captain edges reflect listing order, not historical truth. Q3 ("Pakistani captain wins") returns plausible-but-wrong names (Mohammad Hafeez and Fakhar Zaman at the top instead of Babar Azam and Misbah-ul-Haq). The Logical Reasoning class deliberately avoids `CAPTAINED` for this reason. A real fix would cross-reference cricinfo's captain registry.
- **Cypher slower than SQLite for compiled-plan-friendly queries**: the Python BFS in [query/executor.py](query/executor.py) is a tens-of-lines implementation; SQLite's recursive CTE engine is decades of C optimization. The benchmark shows Cypher wins only on structurally graph-shaped operations (Q4 undirected lookup, LR2 transitive closure tokens). Everything else is slower than SQL on this dataset. A C/Rust implementation of the executor would close most of the gap.

## References

- ISO/IEC 39075:2024 — Graph Query Language ([standard](https://www.iso.org/standard/76120.html))
- W3C SHACL — Shapes Constraint Language ([recommendation](https://www.w3.org/TR/shacl/))
- cricsheet.org JSON specification ([format page](https://cricsheet.org/format/json/))
- Lark parsing library ([docs](https://lark-parser.readthedocs.io/))

## TU Berlin / RWTH Aachen relevance

This project intentionally maps to the core modules of German CS master's programmes:

- **Formal Languages & Automata** — `query/grammar.lark` is an EBNF spec; the RPQ executor in [query/executor.py](query/executor.py) is a direct implementation of finite-automaton path semantics.
- **Database Systems** — the [benchmark/](benchmark/) folder compares the relational and graph models on the same data, controlling for everything except expressibility and execution model.
- **Knowledge Representation** — `ontology/shapes.yaml` is a SHACL-flavored schema with required/optional fields, enums, patterns, and bounds; the validator at [ingestion/validator.py](ingestion/validator.py) enforces these as a NodeShape/PropertyShape pipeline.
- **Practical Engineering** — pinned dependencies, ~95 unit tests, ≥90% coverage, deterministic IDs, idempotent ingestion.
