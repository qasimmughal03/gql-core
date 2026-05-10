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
- **Property Graph** is in-memory dict-of-dicts (~50K nodes / ~300K edges expected for the full Pakistan corpus; 65 / 112 on the test fixtures).
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

Results below are measured on the bundled test fixtures (5 synthetic matches, 65 nodes / 112 edges). Run `python -m benchmark.vs_sqlite` to reproduce on your machine, or against the full Pakistan corpus once you've downloaded it. Each query runs 100 iterations on each engine; we report median latency and the row-set equality between Cypher and SQL results.

| Query | Purpose | Cypher (ms) | SQL (ms) | SQL/Cypher tokens | Recursive SQL? | Match? |
|---|---|---:|---:|:---:|:---:|:---:|
| Q1 | Top run scorers | 0.098 | 0.013 | 29 / 15 (1.9×) | no | ✓ |
| Q2 | Best bowling at Karachi | 0.125 | 0.010 | 47 / 19 (2.5×) | no | ✓ |
| Q3 | Pakistani captain wins | 0.114 | 0.010 | 44 / 23 (1.9×) | no | ✓ |
| Q4 | Babar's frequent partners (undirected) | 0.096 | 0.015 | 68 / 20 (3.4×) | no (UNION ALL) | ✓ |
| Q5 | Bounded RPQ on `NEXT_DELIVERY*1..3` | 0.090 | 0.008 | 48 / 13 (3.7×) | **yes** | ✓ |

(Hardware: Apple Silicon laptop, Python 3.11. Numbers source: [benchmark/results/results.json](benchmark/results/results.json).)

The thesis claim: **Cypher is more expressible** (fewer tokens, no recursion required for path queries), at the cost of in-memory traversal being slower than SQLite's compiled query plan on this small dataset. The Cypher / SQL row-sets agree on all five queries.

## Limitations and Future Work

- **Out of scope (v1)**: full ISO 39075 (multi-clause queries with `WITH`, set quantifiers, schema-DDL); SHACL-SPARQL constraints (sub-query constraints); disk-backed graph store; LDBC SNB micro-benchmark; LLM hallucination comparison.
- **Captain heuristic**: cricsheet has no canonical per-match captain field. The parser uses the first-listed player on each team's roster for that match. A more robust mapping would pull from cricinfo and cross-reference via `info.registry.people`.
- **Q5's Kleene-star demo**: the bundled fixtures use bounded `*1..3` against a 7-delivery innings to keep the result count predictable; on the full corpus, increasing the bound (or using `*` unbounded) is what the genuine RPQ executor exercises.

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
