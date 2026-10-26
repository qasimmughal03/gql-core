"""Example A — Graph Querying with Textual openCypher / GQL.

Demonstrates:
- Building an in-memory PropertyGraph with labeled nodes, directed edges, and properties.
- Querying with MATCH, WHERE, RETURN, ORDER BY.
- Multi-hop variable-length graph traversals (*1..2).

Run with:
    python examples/example_a_graph_query.py
"""

from __future__ import annotations

import gql_core
from gql_core import Edge, Node, PropertyGraph


def main() -> None:
    # 1. Build an in-memory organization & project graph
    graph = PropertyGraph()

    # Create employee and project nodes
    graph.add_node(Node(id="alice", label="Person", props={"name": "Alice", "role": "Director", "dept": "Eng"}))
    graph.add_node(Node(id="bob", label="Person", props={"name": "Bob", "role": "Lead", "dept": "Eng"}))
    graph.add_node(Node(id="charlie", label="Person", props={"name": "Charlie", "role": "Engineer", "dept": "Eng"}))
    graph.add_node(Node(id="dana", label="Person", props={"name": "Dana", "role": "Designer", "dept": "Product"}))
    graph.add_node(Node(id="proj_alpha", label="Project", props={"name": "Alpha", "status": "active"}))

    # Add management hierarchy and project assignments
    graph.add_edge(Edge(id="e1", label="MANAGES", src="alice", dst="bob", props={"since": 2022}))
    graph.add_edge(Edge(id="e2", label="MANAGES", src="bob", dst="charlie", props={"since": 2023}))
    graph.add_edge(Edge(id="e3", label="WORKS_ON", src="bob", dst="proj_alpha", props={"allocation": 0.5}))
    graph.add_edge(Edge(id="e4", label="WORKS_ON", src="charlie", dst="proj_alpha", props={"allocation": 1.0}))
    graph.add_edge(Edge(id="e5", label="WORKS_ON", src="dana", dst="proj_alpha", props={"allocation": 0.8}))

    print(f"Graph initialized with {len(graph._nodes)} nodes and {len(graph._edges)} edges.")

    # 2. Simple MATCH with WHERE, RETURN, and ORDER BY
    q1 = """
    MATCH (p:Person)-[w:WORKS_ON]->(proj:Project)
    WHERE p.dept = 'Eng'
    RETURN p.name AS engineer, w.allocation AS alloc, proj.name AS project
    ORDER BY alloc DESC
    """
    rows1 = gql_core.run(q1, graph)
    print("\n--- Query 1: Engineers working on projects (ordered by allocation DESC) ---")
    for r in rows1:
        print(f"  {r['engineer']} -> {r['project']} ({r['alloc'] * 100:.0f}%)")

    assert rows1 == [
        {"engineer": "Charlie", "alloc": 1.0, "project": "Alpha"},
        {"engineer": "Bob", "alloc": 0.5, "project": "Alpha"},
    ], f"Unexpected Query 1 results: {rows1}"

    # 3. Multi-hop traversal: Find direct and indirect reports of Alice (*1..2)
    q2 = """
    MATCH (dir:Person {name: 'Alice'})-[:MANAGES*1..2]->(sub:Person)
    RETURN sub.name AS report, sub.role AS role
    ORDER BY report ASC
    """
    rows2 = gql_core.run(q2, graph)
    print("\n--- Query 2: All subordinates under Alice (1 to 2 hops) ---")
    for r in rows2:
        print(f"  {r['report']} ({r['role']})")

    assert rows2 == [
        {"report": "Bob", "role": "Lead"},
        {"report": "Charlie", "role": "Engineer"},
    ], f"Unexpected Query 2 results: {rows2}"

    print("\nExample A completed successfully.")


if __name__ == "__main__":
    main()
