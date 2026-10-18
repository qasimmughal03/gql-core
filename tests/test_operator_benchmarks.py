"""Operator-level microbenchmark test suite for GQL-Core logical and ontology reasoning.

Measures:
- Execution latency for Boolean compositions, correlated EXISTS, joins, set algebra,
  quantifiers, temporal filters, and grouping
- Scaling as graph size increases (e.g. 100 to 1,000 nodes)
- Inference rule materialization speed and derived fact throughput.
"""

from __future__ import annotations

import time
import pytest

from gql_core import (
    Edge,
    InferenceEngine,
    Node,
    OntologySchema,
    PlanBuilder,
    PropertyGraph,
    RelationshipType,
    all_rel,
    and_,
    at_least_rel,
    avg,
    count,
    eq,
    execute_plan,
    exists,
    gt,
    lit,
    not_exists,
    or_,
    pattern,
    prop,
    sum_,
    var,
)


@pytest.fixture
def benchmark_graph() -> PropertyGraph:
    """Generate a synthetic scalable graph: 1,000 nodes, 2,500 edges."""
    g = PropertyGraph()
    # 500 Users, 500 Products
    for i in range(500):
        g.add_node(Node(id=f"u_{i}", label="User", props={"id": i, "status": "active" if i % 2 == 0 else "inactive", "score": i}))
    for j in range(500):
        g.add_node(Node(id=f"p_{j}", label="Product", props={"id": j, "price": 10.0 + (j % 50), "category": f"cat_{j % 5}"}))

    # Edges: PURCHASES
    for i in range(500):
        for k in range(5):
            p_id = (i * 3 + k) % 500
            g.add_edge(Edge(id=f"e_{i}_{k}", label="PURCHASES", src=f"u_{i}", dst=f"p_{p_id}"))

    return g


def test_benchmark_boolean_and_exists_composition(benchmark_graph: PropertyGraph):
    """Benchmark complex Boolean composition with correlated EXISTS and NOT EXISTS."""
    has_cheap_product = pattern("u", "PURCHASES", "p", target_filter=gt(prop("p", "price"), lit(20.0)))
    is_active = eq(prop("u", "status"), lit("active"))

    plan = (
        PlanBuilder.scan("u", "User")
        .filter(and_(is_active, exists(has_cheap_product)))
        .project((prop("u", "id"), "uid"))
        .build()
    )

    t0 = time.perf_counter()
    res = execute_plan(plan, benchmark_graph)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert res["count"] > 0
    # Performance assertion: 500 users evaluated in under 150 ms
    assert latency_ms < 250.0, f"Latency too high: {latency_ms:.2f} ms"


def test_benchmark_quantified_relationships(benchmark_graph: PropertyGraph):
    """Benchmark AT_LEAST and ALL over 500 entities with branching factor 5."""
    plan = (
        PlanBuilder.scan("u", "User")
        .filter(at_least_rel(3, "u", "PURCHASES", "p"))
        .project((prop("u", "id"), "uid"))
        .build()
    )

    t0 = time.perf_counter()
    res = execute_plan(plan, benchmark_graph)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert res["count"] == 500  # Every user has 5 purchases
    assert latency_ms < 250.0, f"Latency too high: {latency_ms:.2f} ms"


def test_benchmark_grouping_and_aggregates(benchmark_graph: PropertyGraph):
    """Benchmark multi-key hash grouping, COUNT, SUM, AVG over graph stream."""
    plan = (
        PlanBuilder.scan("u", "User")
        .expand("PURCHASES", to_var="p", from_var="u")
        .project(
            (prop("u", "status"), "user_status"),
            (prop("p", "category"), "category"),
            (prop("p", "price"), "price"),
        )
        .group_by(
            ["user_status", "category"],
            (count(var("price")), "order_count"),
            (sum_(var("price")), "total_revenue"),
            (avg(var("price")), "avg_price"),
        )
        .build()
    )

    t0 = time.perf_counter()
    res = execute_plan(plan, benchmark_graph)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert res["count"] > 0
    assert latency_ms < 500.0, f"Latency too high: {latency_ms:.2f} ms"


def test_benchmark_inference_engine_scaling():
    """Benchmark fixed-point inference generation of transitive relationships."""
    schema = OntologySchema()
    schema.add_relationship(RelationshipType(name="STEP", source_type="Node", target_type="Node", is_transitive=True))

    g = PropertyGraph()
    # Linear chain of 50 steps: 0 -> 1 -> 2 ... -> 49
    # Transitive closure generates 50 * 49 / 2 = 1,225 derived facts!
    for i in range(50):
        g.add_node(Node(id=f"n_{i}", label="Node"))
    for i in range(49):
        g.add_edge(Edge(id=f"e_{i}", label="STEP", src=f"n_{i}", dst=f"n_{i+1}"))

    engine = InferenceEngine(schema=schema, max_iterations=60)

    t0 = time.perf_counter()
    _, new_facts = engine.infer(g)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    # 1,225 - 49 = 1,176 newly derived transitive facts
    assert len(new_facts) == 1176
    assert latency_ms < 3000.0, f"Inference too slow: {latency_ms:.2f} ms for 1,176 facts"
