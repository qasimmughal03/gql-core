"""GQL-Core: A generic property-graph query engine with formal grammar.

GQL-Core implements a documented subset of ISO/IEC 39075:2024 (GQL) —
MATCH ... WHERE ... RETURN with regular path queries (RPQ) and full
aggregation — on top of an in-memory property graph with SHACL-style
validation.

Usage::

    from gql_core import PropertyGraph, ShapeValidator, GraphIngester, run_query

    graph = PropertyGraph()
    validator = ShapeValidator("my-shapes.yaml")
    ingester = GraphIngester(graph, validator)
    ingester.ingest_directory("my-data/")

    rows = run_query(
        "MATCH (n)-[e]->(m) RETURN n.name AS src, e.label, m.name AS dst",
        graph,
        schema_path="my-shapes.yaml",
    )

Or use the CLI::

    gql-core validate --schema my-shapes.yaml --data my-data/
    gql-core query --schema my-shapes.yaml --data my-data/ "MATCH (n) RETURN n"
    gql-core benchmark --schema my-shapes.yaml --data my-data/ --suite queries.yaml
"""

__version__ = "0.2.0"

from gql_core.graph import Edge, Node, PropertyGraph
from gql_core.ingester import GraphIngester, IngestReport
from gql_core.validator import ShapeValidator, ShapeViolationError
from gql_core.query.executor import run as run_query
from gql_core.ai import ask, translate_to_gql

__all__ = [
    "__version__",
    "ask",
    "Edge",
    "GraphIngester",
    "IngestReport",
    "Node",
    "PropertyGraph",
    "run_query",
    "ShapeValidator",
    "ShapeViolationError",
    "translate_to_gql",
]

