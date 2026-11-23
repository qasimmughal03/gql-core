"""Impact analysis for a small service architecture, built on GQL-Core.

A self-contained application that uses GQL-Core as an ordinary dependency:

1. it loads a service graph (services, the teams that own them, and DEPENDS_ON edges);
2. it derives every indirect dependency with a transitive rule, keeping the provenance;
3. it answers "what breaks if X fails?" with a declarative query;
4. optionally, it answers a question in plain English with ``ask()`` and Gemini.

Run it from anywhere after ``pip install gql-core``:

    python app.py                         # impact analysis for the database
    python app.py --failed auth           # another service
    python app.py --ask "Which services does the payments team own?"   # needs GEMINI_API_KEY
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import requests

from gql_core import PropertyGraph, ask, run
from gql_core.inference import InferenceEngine, make_transitive_rule

DATA = Path(__file__).with_name("services.json")


def load_graph() -> PropertyGraph:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    return PropertyGraph.from_dict(data)


def derive_dependencies(graph: PropertyGraph) -> list[str]:
    """Add every indirect DEPENDS_ON edge and explain where each one came from."""
    engine = InferenceEngine()
    engine.add_rule(make_transitive_rule("DEPENDS_ON"))
    _, derived = engine.infer(graph)
    explanations = []
    for fact in derived:
        src, rel, dst = fact.args
        via = " and ".join(f"{a}->{c}" for a, _, c in (e.args for e in fact.evidence))
        explanations.append(f"{src} {rel} {dst}  (rule {fact.rule_name}, from {via})")
    engine.materialize(graph)
    return sorted(explanations)


def impact(graph: PropertyGraph, failed: str) -> list[dict]:
    """Every service that depends on ``failed``, directly or not, with its owning team."""
    node = graph.get_node(failed)
    if node is None or "Service" not in node.labels:
        raise SystemExit(f"unknown service {failed!r}")
    # The id was checked against the graph above, so it is safe to place in the query.
    return run(
        f"MATCH (s:Service)-[d:DEPENDS_ON]->(f:Service {{id: '{failed}'}}), (t:Team)-[:OWNS]->(s) "
        "RETURN s.name AS service, t.name AS team, s.tier AS tier, "
        "CASE WHEN d.is_inferred THEN 'indirect' ELSE 'direct' END AS dependency "
        "ORDER BY tier, service",
        graph,
    )


def gemini(prompt: str, model: str = "gemini-2.5-flash") -> str:
    """A minimal ``ask()`` client: any function from prompt text to query text works."""
    key = os.environ["GEMINI_API_KEY"]
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "thinkingConfig": {"thinkingBudget": 0}},
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--failed", default="db", help="id of the failed service (default: db)")
    parser.add_argument("--ask", help="a question in plain English (uses Gemini; needs GEMINI_API_KEY)")
    args = parser.parse_args()

    graph = load_graph()
    print("Derived dependencies:")
    for line in derive_dependencies(graph):
        print("  " + line)

    print(f"\nIf '{args.failed}' fails, these services are affected:")
    for row in impact(graph, args.failed):
        print(f"  {row['service']:<14} tier {row['tier']}  {row['dependency']:<8}  owner: {row['team']}")

    if args.ask:
        out = ask(graph, args.ask, client=gemini, explain=True)
        print(f"\nQuestion: {args.ask}\nQuery:    {out['query']}")
        for attempt in out["attempts"]:
            for change in attempt["repairs"]:
                print(f"Repaired: {change}")
        for row in out["results"]:
            print(f"  {row}")


if __name__ == "__main__":
    main()
