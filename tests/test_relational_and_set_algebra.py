"""Tests for Relational Joins, Set Algebra, Aggregation, and Conditional Expressions in GQL-Core."""

from __future__ import annotations

import pytest

from gql_core import (
    Edge,
    Node,
    PlanBuilder,
    PropertyGraph,
    avg,
    case_when,
    coalesce,
    collect,
    count,
    eq,
    execute_plan,
    gt,
    lit,
    max_,
    min_,
    or_,
    prop,
    sum_,
    var,
)
from gql_core.ir import ProjectItem


@pytest.fixture
def sales_graph() -> PropertyGraph:
    """Fixture graph: Customers, Orders, Items:
    - Alice: Order 101 ($100, status: completed), Order 102 ($200, status: completed), Order 103 ($50, status: pending)
    - Bob: Order 201 ($300, status: completed)
    - Charlie: No orders (tests outer join null padding)
    """
    g = PropertyGraph()
    g.add_node(Node(id="c1", label="Customer", props={"id": "c1", "name": "Alice", "tier": "gold"}))
    g.add_node(Node(id="c2", label="Customer", props={"id": "c2", "name": "Bob", "tier": "silver"}))
    g.add_node(Node(id="c3", label="Customer", props={"id": "c3", "name": "Charlie", "tier": "bronze"}))

    g.add_node(Node(id="o1", label="Order", props={"id": "o1", "amount": 100, "status": "completed"}))
    g.add_node(Node(id="o2", label="Order", props={"id": "o2", "amount": 200, "status": "completed"}))
    g.add_node(Node(id="o3", label="Order", props={"id": "o3", "amount": 50, "status": "pending"}))
    g.add_node(Node(id="o4", label="Order", props={"id": "o4", "amount": 300, "status": "completed"}))

    g.add_edge(Edge(id="e1", label="PLACED", src="c1", dst="o1"))
    g.add_edge(Edge(id="e2", label="PLACED", src="c1", dst="o2"))
    g.add_edge(Edge(id="e3", label="PLACED", src="c1", dst="o3"))
    g.add_edge(Edge(id="e4", label="PLACED", src="c2", dst="o4"))

    return g


def test_optional_match_left_outer_join(sales_graph: PropertyGraph):
    """Verify OPTIONAL MATCH retains Charlie with None order bindings."""
    scan_c = PlanBuilder.scan("c", "Customer").build()
    from gql_core.ir import Expand, LeftOuterJoin, Project, ProjectItem

    # Expand PLACED with optional=True
    exp_order = Expand(
        from_var="c",
        edge_var="e",
        edge_label="PLACED",
        direction="out",
        to_var="o",
        to_label="Order",
        optional=True,
    )

    plan = (
        PlanBuilder(scan_c)
        .expand("PLACED", to_var="o", to_label="Order", optional=True, from_var="c")
        .project(
            (prop("c", "name"), "customer"),
            (prop("o", "amount"), "amount"),
        )
        .build()
    )

    res = execute_plan(plan, sales_graph)
    by_name = {r["customer"]: r["amount"] for r in res["rows"] if r["amount"] is None}
    assert "Charlie" in by_name
    assert by_name["Charlie"] is None


def test_semi_and_anti_joins(sales_graph: PropertyGraph):
    """Verify SemiJoin (customers with orders) and AntiJoin (customers with no orders)."""
    customers = PlanBuilder.scan("c", "Customer").project((prop("c", "id"), "cid"), (prop("c", "name"), "name"))
    # Orders linked to customers
    cust_orders = (
        PlanBuilder.scan("c", "Customer")
        .expand("PLACED", to_var="o", from_var="c")
        .project((prop("c", "id"), "cid"))
    )

    # 1. SemiJoin: returns Alice and Bob (have placed orders)
    semi_plan = customers.semi_join(cust_orders, on=("cid",)).build()
    res_semi = execute_plan(semi_plan, sales_graph)
    semi_names = {r["name"] for r in res_semi["rows"]}
    assert semi_names == {"Alice", "Bob"}

    # 2. AntiJoin: returns Charlie (no placed orders)
    anti_plan = customers.anti_join(cust_orders, on=("cid",)).build()
    res_anti = execute_plan(anti_plan, sales_graph)
    anti_names = {r["name"] for r in res_anti["rows"]}
    assert anti_names == {"Charlie"}


def test_set_algebra_union_intersect_except(sales_graph: PropertyGraph):
    """Test UNION, UNION ALL, INTERSECT, and EXCEPT."""
    # Relation 1: ['Alice', 'Bob', 'Alice']
    r1 = (
        PlanBuilder.scan("c", "Customer")
        .filter(or_(eq(prop("c", "name"), lit("Alice")), eq(prop("c", "name"), lit("Bob"))))
        .project((prop("c", "name"), "name"))
    )

    # Relation 2: ['Bob', 'Charlie']
    r2 = (
        PlanBuilder.scan("c", "Customer")
        .filter(or_(eq(prop("c", "name"), lit("Bob")), eq(prop("c", "name"), lit("Charlie"))))
        .project((prop("c", "name"), "name"))
    )

    # 1. UNION (distinct): Alice, Bob, Charlie
    u_distinct = r1.union(r2, all=False).build()
    res_u = execute_plan(u_distinct, sales_graph)
    names_u = [r["name"] for r in res_u["rows"]]
    assert sorted(names_u) == ["Alice", "Bob", "Charlie"]

    # 2. UNION ALL: Alice, Bob, Bob, Charlie (preserves duplicates)
    u_all = r1.union(r2, all=True).build()
    res_u_all = execute_plan(u_all, sales_graph)
    names_u_all = [r["name"] for r in res_u_all["rows"]]
    assert sorted(names_u_all) == ["Alice", "Bob", "Bob", "Charlie"]

    # 3. INTERSECT: Bob
    intersect_plan = r1.intersect(r2, all=False).build()
    res_int = execute_plan(intersect_plan, sales_graph)
    assert res_int["rows"] == [{"name": "Bob"}]

    # 4. EXCEPT: Alice (in r1, not in r2)
    except_plan = r1.except_(r2, all=False).build()
    res_exc = execute_plan(except_plan, sales_graph)
    assert res_exc["rows"] == [{"name": "Alice"}]


def test_group_by_aggregates_and_having(sales_graph: PropertyGraph):
    """Test GROUP BY with COUNT, SUM, AVG, MIN, MAX, COLLECT, and HAVING."""
    # Alice has orders 100, 200, 50 (sum=350, avg=116.67, min=50, max=200, count=3)
    # Bob has order 300 (sum=300, count=1)
    plan = (
        PlanBuilder.scan("c", "Customer")
        .expand("PLACED", to_var="o", from_var="c")
        .project(
            (prop("c", "name"), "cust_name"),
            (prop("o", "amount"), "amount"),
        )
        .group_by(
            ["cust_name"],
            (count(var("amount")), "order_count"),
            (sum_(var("amount")), "total_spend"),
            (avg(var("amount")), "avg_spend"),
            (min_(var("amount")), "min_spend"),
            (max_(var("amount")), "max_spend"),
            (collect(var("amount")), "order_amounts"),
        )
        .having(gt(var("order_count"), lit(1)))  # Only customers with > 1 order (Alice)
        .build()
    )

    res = execute_plan(plan, sales_graph)
    assert len(res["rows"]) == 1
    alice_row = res["rows"][0]
    assert alice_row["cust_name"] == "Alice"
    assert alice_row["order_count"] == 3
    assert alice_row["total_spend"] == 350
    assert alice_row["min_spend"] == 50
    assert alice_row["max_spend"] == 200
    assert sorted(alice_row["order_amounts"]) == [50, 100, 200]


def test_case_when_and_coalesce(sales_graph: PropertyGraph):
    """Test CASE WHEN / THEN / ELSE and COALESCE expressions."""
    # Case expression assigning tier bonuses
    case_expr = case_when(
        [
            (eq(prop("c", "tier"), lit("gold")), lit("High Priority")),
            (eq(prop("c", "tier"), lit("silver")), lit("Medium Priority")),
        ],
        else_expr=lit("Standard Priority"),
    )

    plan = (
        PlanBuilder.scan("c", "Customer")
        .project(
            (prop("c", "name"), "name"),
            (case_expr, "priority"),
            (coalesce(prop("c", "missing_val"), lit("DefaultValue")), "safe_val"),
        )
        .sort((var("name"), "ASC"))
        .build()
    )

    res = execute_plan(plan, sales_graph)
    rows = {r["name"]: r for r in res["rows"]}
    assert rows["Alice"]["priority"] == "High Priority"
    assert rows["Alice"]["safe_val"] == "DefaultValue"
    assert rows["Bob"]["priority"] == "Medium Priority"
    assert rows["Charlie"]["priority"] == "Standard Priority"
