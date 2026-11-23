# Integration demo: service impact analysis

A small application that uses GQL-Core as an ordinary dependency, the way you would in your own
project. It needs nothing from this repository except the two files in this folder.

```bash
python -m pip install -r requirements.txt     # installs gql-core from PyPI
python app.py                                 # what breaks if the database fails?
python app.py --failed auth
```

What it does:

1. **Loads a graph** of services, the teams that own them, and their direct `DEPENDS_ON` edges
   ([`services.json`](services.json)).
2. **Derives indirect dependencies** with a transitive rule. Each derived edge keeps its
   provenance: the rule that produced it and the two edges it came from.
3. **Answers a question with a declarative query**: every service affected by a failure, whether
   the dependency is direct or derived, and which team to call.

```text
Derived dependencies:
  web DEPENDS_ON db  (rule transitive_DEPENDS_ON, from web->orders and orders->db)
  ...
If 'db' fails, these services are affected:
  Mobile BFF     tier 1  indirect  owner: Frontend
  Storefront     tier 1  indirect  owner: Frontend
  Auth API       tier 2  direct    owner: Identity
  Orders API     tier 2  direct    owner: Checkout
  Payments API   tier 2  indirect  owner: Payments
```

## Questions in plain English (optional)

`ask()` has a language model write the query and GQL-Core check and run it. The demo includes a
ten-line Gemini client; any function from prompt text to query text works.

```bash
export GEMINI_API_KEY=...          # Windows: setx GEMINI_API_KEY ...
python app.py --ask "Which services does the Payments team own, and what do they depend on?"
```

```text
Query:    MATCH (t:Team)-[:OWNS]->(s1:Service)-[:DEPENDS_ON]->(s2:Service) WHERE t.name = "Payments" RETURN ...
  {'OwnedService': 'Payments API', 'DependsOnService': 'Auth API'}
  {'OwnedService': 'Payments API', 'DependsOnService': 'Postgres'}
  {'OwnedService': 'Payments API', 'DependsOnService': 'Redis'}
```

The model's query can differ from run to run. Any repair GQL-Core made to it is printed as
`Repaired: ...`.
