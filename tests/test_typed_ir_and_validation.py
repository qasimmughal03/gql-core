"""Tests for Canonical Typed Query IR, Serialization, and Validation in GQL-Core."""

from __future__ import annotations

import json
import pytest

from gql_core import (
    DataType,
    PlanBuilder,
    PlanValidationError,
    and_,
    col,
    eq,
    gt,
    is_null,
    lit,
    not_,
    or_,
    prop,
    validate_logical_plan,
    var,
)
from gql_core.ir import (
    Expand,
    Filter,
    Join,
    Limit,
    Project,
    ProjectItem,
    Scan,
    Sort,
    SortTerm,
    plan_from_dict,
    plan_to_dict,
)


def test_ir_serialization_and_deserialization_roundtrip():
    """Verify that a complex plan tree serializes to versioned JSON and deserializes identically."""
    builder = (
        PlanBuilder.scan("p", "Person", status="active")
        .filter(and_(gt(prop("p", "age"), lit(25)), not_(is_null(prop("p", "name")))))
        .project(
            (prop("p", "name"), "full_name"),
            (prop("p", "age"), "age_years"),
            distinct=True,
        )
        .sort((col("age_years"), "DESC"))
        .limit(10, offset=5)
    )

    plan = builder.build()
    plan_dict = plan_to_dict(plan)
    assert plan_dict["version"] == "1.0"
    assert plan_dict["_type"] == "Limit"
    assert plan_dict["count"] == 10
    assert plan_dict["offset"] == 5

    # JSON text roundtrip
    json_str = json.dumps(plan_dict)
    recovered_plan = plan_from_dict(json.loads(json_str))

    assert isinstance(recovered_plan, Limit)
    assert recovered_plan.count == 10
    assert recovered_plan.offset == 5
    assert isinstance(recovered_plan.input, Sort)


def test_validator_rejects_unbound_variable_in_filter():
    """Verify that referencing an unbound variable raises PlanValidationError."""
    scan = Scan(var="p", label="Person")
    # Referencing unknown variable 'q'
    flt = Filter(input=scan, predicate=eq(prop("q", "age"), lit(30)))

    with pytest.raises(PlanValidationError) as exc:
        validate_logical_plan(flt, strict=True)
    assert "UNBOUND_VARIABLE" in str(exc.value)


def test_validator_rejects_unbound_variable_in_expand():
    """Verify that expanding from an unbound variable raises PlanValidationError."""
    scan = Scan(var="p", label="Person")
    # Expanding from 'unknown_var' which was never scanned
    exp = Expand(from_var="unknown_var", edge_var="e", edge_label="KNOWS", direction="out", to_var="f")
    plan = Join(left=scan, right=exp, on=("p",), kind="INNER")

    with pytest.raises(PlanValidationError) as exc:
        validate_logical_plan(plan, strict=True)
    assert "UNBOUND_VARIABLE" in str(exc.value)


def test_validator_rejects_missing_join_key():
    """Verify that joining on a key absent from either relation raises PlanValidationError."""
    scan1 = Scan(var="a", label="A")
    scan2 = Scan(var="b", label="B")
    # Joining on 'shared_id' which is not bound in either scan
    join = Join(left=scan1, right=scan2, on=("shared_id",), kind="INNER")

    with pytest.raises(PlanValidationError) as exc:
        validate_logical_plan(join, strict=True)
    assert "JOIN_KEY_MISSING" in str(exc.value)


def test_validator_rejects_set_op_schema_mismatch():
    """Verify that Union with mismatched projections raises PlanValidationError."""
    scan1 = Scan(var="a", label="A")
    p1 = Project(input=scan1, projections=(ProjectItem(expr=prop("a", "x"), alias="x"),))

    scan2 = Scan(var="b", label="B")
    p2 = Project(input=scan2, projections=(ProjectItem(expr=prop("b", "y"), alias="y"),))

    from gql_core.ir import Union
    u = Union(left=p1, right=p2, all=False)

    with pytest.raises(PlanValidationError) as exc:
        validate_logical_plan(u, strict=True)
    assert "SET_OP_SCHEMA_MISMATCH" in str(exc.value)


def test_validator_rejects_invalid_limit_and_bounds():
    """Verify negative limit or inverted hop bounds raise PlanValidationError."""
    scan = Scan(var="a", label="A")
    lim = Limit(input=scan, count=-5)
    with pytest.raises(PlanValidationError) as exc:
        validate_logical_plan(lim, strict=True)
    assert "INVALID_LIMIT" in str(exc.value)

    from gql_core.ir import RecursiveExpand
    rec = RecursiveExpand(from_var="a", edge_var=None, edge_label="LINK", direction="out", min_hops=5, max_hops=2, to_var="b")
    join_rec = Join(left=scan, right=rec, on=("a",), kind="INNER")
    with pytest.raises(PlanValidationError) as exc2:
        validate_logical_plan(join_rec, strict=True)
    assert "INVALID_BOUNDS" in str(exc2.value)
