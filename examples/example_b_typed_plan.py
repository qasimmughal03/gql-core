"""Example B — Programmatic Typed Query Plans with PlanBuilder.

Demonstrates:
- Constructing typed relational & graph query plans via PlanBuilder.
- Operators: Scan, Filter, Expand, Project, Sort.
- Typed Boolean expressions: and_, eq, gt, lit, prop, col.
- Static plan validation with validate_logical_plan.
- Deterministic execution with execute_plan against an in-memory PropertyGraph.
- Realistic use case: Service dependencies and high-latency dependencies in a cloud architecture.

Run with:
    python examples/example_b_typed_plan.py
"""

from __future__ import annotations

from gql_core import (
    Edge,
    Node,
    PlanBuilder,
    PropertyGraph,
    and_,
    col,
    eq,
    execute_plan,
    gt,
    lit,
    prop,
    validate_logical_plan,
)


def main() -> None:
    # 1. Populate a realistic microservice dependency architecture
    graph = PropertyGraph()

    # Define Microservices
    services = [
        {"id": "auth_svc", "label": "Service", "name": "AuthService", "tier": "critical", "p99_latency": 15},
        {"id": "order_svc", "label": "Service", "name": "OrderService", "tier": "critical", "p99_latency": 120},
        {"id": "pay_svc", "label": "Service", "name": "PaymentService", "tier": "critical", "p99_latency": 250},
        {"id": "notif_svc", "label": "Service", "name": "NotificationService", "tier": "standard", "p99_latency": 35},
        {"id": "db_main", "label": "Database", "name": "MainPostgres", "tier": "critical", "p99_latency": 5},
    ]
    for s in services:
        graph.add_node(Node(id=s["id"], label=s["label"], props=s))

    # Define Service Calls / Dependencies
    dependencies = [
        ("order_svc", "auth_svc", "DEPENDS_ON", 10),
        ("order_svc", "pay_svc", "DEPENDS_ON", 180),
        ("order_svc", "db_main", "DEPENDS_ON", 8),
        ("pay_svc", "db_main", "DEPENDS_ON", 12),
        ("notif_svc", "db_main", "DEPENDS_ON", 6),
    ]
    for idx, (src, dst, rel, rpc_ms) in enumerate(dependencies, 1):
        graph.add_edge(Edge(id=f"dep_{idx}", label=rel, src=src, dst=dst, props={"rpc_latency_ms": rpc_ms}))

    print(f"Service graph ready: {len(graph._nodes)} nodes, {len(graph._edges)} dependencies.")

    # 2. Build a Typed Query Plan:
    # Find all dependencies of 'critical' tier services where the dependency itself has p99_latency > 50ms
    plan = (
        PlanBuilder.scan("s", "Service")
        .filter(eq(prop("s", "tier"), lit("critical")))
        .expand("DEPENDS_ON", to_var="dep", from_var="s")
        .filter(gt(prop("dep", "p99_latency"), lit(50)))
        .project(
            (prop("s", "name"), "caller_service"),
            (prop("dep", "name"), "target_service"),
            (prop("dep", "p99_latency"), "target_latency_ms"),
        )
        .sort((col("target_latency_ms"), "DESC"))
        .build()
    )

    # 3. Validate Plan before execution
    report = validate_logical_plan(plan, strict=True)
    assert report.is_valid, f"Logical plan validation failed: {report.errors}"
    print(f"Plan validation passed: is_valid={report.is_valid}.")

    # 4. Deterministic Execution
    execution_result = execute_plan(plan, graph)
    rows = execution_result["rows"]

    print("\n--- Typed Plan Results: Critical services depending on high-latency services ---")
    for r in rows:
        print(f"  {r['caller_service']} -> {r['target_service']} (target p99: {r['target_latency_ms']}ms)")

    assert rows == [
        {"caller_service": "OrderService", "target_service": "PaymentService", "target_latency_ms": 250}
    ], f"Unexpected typed plan results: {rows}"

    print("\nExample B completed successfully.")


if __name__ == "__main__":
    main()
