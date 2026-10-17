# Cricket Knowledge Graph — Example Domain

This directory is a complete example of how to use `gql-core` with a
real-world domain: Pakistan international cricket data from
[cricsheet.org](https://cricsheet.org/).

## Quickstart

```bash
# Install gql-core
pip install -e .

# Download live data (optional — fixtures are bundled)
python examples/cricket/download.py

# Validate + ingest
gql-core validate --schema examples/cricket/shapes.yaml --data examples/cricket/fixtures/
gql-core ingest --schema examples/cricket/shapes.yaml --data examples/cricket/fixtures/

# Run a query
gql-core query --schema examples/cricket/shapes.yaml --data examples/cricket/fixtures/ \
  "MATCH (p:Player) RETURN p.name AS player ORDER BY player ASC LIMIT 5"

# Build SQLite mirror
gql-core mirror --schema examples/cricket/shapes.yaml --data examples/cricket/fixtures/ \
  --db examples/cricket/cricket.db

# Run benchmark suite
gql-core benchmark --schema examples/cricket/shapes.yaml --data examples/cricket/fixtures/ \
  --suite examples/cricket/benchmark/suite.yaml --db examples/cricket/cricket.db --iters 30
```

## Ontology

7 node types: Player, Match, Venue, Team, Innings, Delivery, Tournament
9 edge types: PLAYED_FOR, BATTED_IN, BOWLED_IN, CAPTAINED, PLAYED_AT,
               TEAMMATES_WITH, IN_INNINGS, NEXT_DELIVERY, PART_OF_TOURNAMENT

Full ontology documentation in `shapes.yaml`.

## Data

- `fixtures/` — 5 bundled test matches (4 T20, 1 Test; 16 players, 65 nodes, 112 edges)
- `data/` — live data from cricsheet.org (712K nodes, 1.47M edges for full Pakistan corpus)
- `ground_truth.json` — hand-verified expected values for the fixture corpus

## Migrating from the Old CLI

| Old Command | New Equivalent |
|---|---|
| `python -m ingestion.cricsheet_parser data/` | `gql-core validate --schema shapes.yaml --data data/` |
| `python scripts/build_sqlite_mirror.py` | `gql-core mirror --schema shapes.yaml --data data/ --db cricket.db` |
| `python -m benchmark.vs_sqlite` | `gql-core benchmark --suite suite.yaml --db cricket.db` |
