"""Run with: python examples/quickstart.py (after pip install -e .)."""

from gql_core import (
    Edge, Node, PropertyGraph, PlanBuilder, eq, execute_plan, lit, prop, run
)


def main() -> None:
    graph = PropertyGraph()
    graph.add_node(Node(id="alice", label="Person", props={"name": "Alice"}))
    graph.add_node(Node(id="bob", label="Person", props={"name": "Bob"}))
    graph.add_edge(Edge(id="e1", label="KNOWS", src="alice", dst="bob"))

    rows = run(
        "MATCH (a:Person)-[:KNOWS]->(b:Person) "
        "WHERE a.name = 'Alice' RETURN b.name AS friend",
        graph,
    )
    assert rows == [{"friend": "Bob"}], rows
    print("Text query:", rows)

    plan = (
        PlanBuilder.scan("p", "Person")
        .filter(eq(prop("p", "name"), lit("Alice")))
        .project((prop("p", "name"), "name"))
        .build()
    )
    structured_rows = execute_plan(plan, graph)["rows"]
    assert structured_rows == [{"name": "Alice"}], structured_rows
    print("Typed plan:", structured_rows)


if __name__ == "__main__":
    main()
