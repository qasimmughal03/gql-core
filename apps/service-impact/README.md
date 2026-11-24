# service-impact: a reference application built on GQL-Core

A small, complete application that uses the published `gql-core` package the way a third-party
project would: as a pinned dependency from PyPI, with no access to GQL-Core's source tree.

It answers the questions an on-call engineer asks during an incident:

- Which services read from or write to database X?
- If component Y fails, what else stops working, directly or indirectly?
- Which teams own the affected components, and who do I page?
- What dependency path explains each result?
- Which relationships were stored in the catalog, and which were inferred, and by which rule?

```text
service catalog (JSON) → validation → property graph → GQL-Core queries + rule inference → CLI / JSON API
```

## Install and run

```bash
python -m venv .venv
.venv/bin/pip install ".[test]"            # Windows: .venv\Scripts\pip install ".[test]"
.venv/bin/service-impact version            # gql-core 0.2.0a4 at .../site-packages/gql_core/__init__.py
.venv/bin/service-impact impact orders-db
```

```text
If orders-db fails, 8 components are affected:

  tier 1  orders-svc           direct   1 hop(s)  owner: Checkout (lead Omar Haddad, #checkout-oncall)
          evidence: orders-svc -[READS_FROM]-> orders-db
  tier 1  public-gateway       indirect 2 hop(s)  owner: Platform (lead Ana Ruiz, #platform-oncall)
          evidence: public-gateway -[CALLS]-> orders-svc -[READS_FROM]-> orders-db
          inferred by: transitive_RELIES_ON, calls_implies_relies_on, reads_from_implies_relies_on
  ...
  tier 3  legacy-reporting     direct   1 hop(s)  owner: NO OWNER

Affected components with no owning team: legacy-reporting

Teams to notify:
  Growth     #growth            3 component(s): mobile-bff, notification-svc, web-storefront
  Checkout   #checkout-oncall   2 component(s): fulfillment-worker, orders-svc
  ...
```

Other commands:

```bash
service-impact dependents catalog-db       # stored readers and writers of a database
service-impact teams sessions-cache        # teams to notify, as JSON
service-impact hotspots --min 3            # services that call at least 3 components (typed plan)
service-impact tier-owners --tier 1        # owning team of every tier-1 service (typed plan)
service-impact plan --tier 1               # that typed plan as JSON, the form an agent would send
service-impact --json impact k8s-prod-us   # full result as JSON
service-impact serve --port 8080           # JSON API; see below
service-impact --catalog my_catalog.json impact some-id
```

JSON API (`service-impact serve`): `GET /health`, `/components`, `/impact/<id>`, `/teams/<id>`,
`/dependents/<database-id>`, `/hotspots?min=3`, `/tier-owners?tier=1`. Unknown ids return 404.

## How it uses GQL-Core

| Part | GQL-Core feature | Where |
| --- | --- | --- |
| Catalog → graph | `PropertyGraph`, `Node`, `Edge` | [`catalog.py`](src/service_impact/catalog.py) |
| Every runtime relationship implies `RELIES_ON`, which is transitive | `InferenceEngine`, custom `InferenceRule`s, `make_transitive_rule`; each derived fact keeps its rule and evidence | [`analysis.py`](src/service_impact/analysis.py) `runtime_rules` |
| Stored vs inferred | derived `RELIES_ON` edges carry `is_inferred` and `inferred_by`; catalog edges carry `source: catalog` | `ImpactAnalyzer.__init__` |
| Readers and writers of a database | openCypher: typed relationship alternatives, `collect(type(r))` | `dependents_of_database` |
| Shortest evidence path | openCypher variable-length path, `nodes(p)`, `relationships(p)` | `impact` |
| Teams to notify | multi-pattern `MATCH`, `count`, `collect`, `ORDER BY` | `teams_to_notify` |
| Affected but unowned | negated pattern predicate `NOT (c)-[:OWNED_BY]->(:Team)` | `unowned_affected` |
| Fan-out hotspots | typed plan with an `AT_LEAST` quantified relationship predicate | `fan_out_hotspots` |
| Owners per tier | typed plan, validated with `validate_logical_plan`, serialised to JSON and back | `tier_owners` |

The impact answer is computed twice, by inference and by a path query, and
`ImpactAnalyzer.impact` raises if the two disagree.

## Tests

```bash
.venv/bin/pytest          # run from this folder, so the installed packages are the ones imported
```

The 38 tests check, among other things, that `gql_core` is the installed 0.2.0a4 release, that
every component's impact set equals an independent breadth-first search over the catalog file,
that every evidence path consists of stored relationships, that inferred edges are marked, that a
dependency cycle does not report the failed component as affected by itself, that ids which are
not in the graph (including injection attempts) are rejected, and that the CLI and the HTTP API
work end to end.

## Limitations found while building it (gql-core 0.2.0a4)

- **No query parameters.** `gql_core.run` takes no parameter map, so the app checks every id
  against the graph and a strict pattern before placing it in query text.
- **No `shortestPath()`.** The evidence path is the shortest of the variable-length paths
  returned, chosen in Python, with a 10-hop bound.
- **`InferenceEngine` default `max_facts=250_000` counts stored facts too.** On a larger graph,
  inference stops early without an error, so the app sets `max_facts` explicitly.
- **`PlanBuilder.expand()` after `.filter()` needs `from_var=`.** The builder infers the source
  variable only directly after `scan()` or `expand()`; otherwise validation reports an unbound
  variable `'a'`.
- **In memory only.** The graph is rebuilt from the catalog at start-up (milliseconds for this
  catalog); there is no persistence or concurrent writing.
