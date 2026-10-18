"""Tests for Typed Temporal Operators and Collection Operations in GQL-Core."""

from __future__ import annotations

import pytest

from gql_core import (
    Date,
    DateTime,
    Duration,
    Interval,
    Time,
    between,
    eq,
    gt,
    in_,
    lit,
    lt,
    not_in,
)
from gql_core.ir import CollectionQuantifier, FunctionCall, ListExpr, Literal, Variable
from gql_core.physical.evaluator import eval_predicate, eval_value


def test_temporal_models_and_arithmetic():
    """Verify Date, Time, DateTime, Duration, Interval arithmetic and comparisons."""
    # 1. Date creation and arithmetic
    d1 = Date(2026, 1, 1)
    d2 = Date(2026, 1, 15)
    dur = Duration(days=14)

    assert d1 + dur == d2
    assert d2 - d1 == dur
    assert d1 < d2
    assert d2 > d1

    # 2. DateTime and Timezone
    dt1 = DateTime.from_iso("2026-05-01T12:00:00+00:00")
    dt2 = DateTime.from_iso("2026-05-01T14:00:00+00:00")
    assert dt2 - dt1 == Duration(seconds=7200)

    # 3. Intervals
    inv1 = Interval(start=d1, end=d2)
    mid_date = Date(2026, 1, 10)
    after_date = Date(2026, 2, 1)

    assert inv1.contains(mid_date) is True
    assert inv1.contains(after_date) is False

    inv2 = Interval(start=Date(2026, 1, 10), end=Date(2026, 1, 25))
    assert inv1.overlaps(inv2) is True
    assert inv1.is_disjoint(inv2) is False

    # Intersection
    inter = inv1.intersection(inv2)
    assert inter is not None
    assert inter.start == Date(2026, 1, 10)
    assert inter.end == Date(2026, 1, 15)


def test_temporal_filter_in_evaluation():
    """Verify evaluation of temporal comparisons against rows."""
    row = {
        "event_date": Date(2026, 6, 15),
        "cutoff_date": Date(2026, 6, 1),
    }

    # event_date > cutoff_date
    pred = gt(Variable("event_date"), Variable("cutoff_date"))
    assert eval_predicate(pred, row) is True

    # between(event_date, 2026-06-01, 2026-06-30)
    pred_between = between(
        Variable("event_date"),
        Literal(Date(2026, 6, 1)),
        Literal(Date(2026, 6, 30)),
    )
    assert eval_predicate(pred_between, row) is True


def test_collection_operators():
    """Verify IN, NOT IN, SIZE, and collection quantifiers."""
    row = {
        "tags": ["python", "graph", "ai"],
        "scores": [85, 92, 78],
    }

    # 1. IN / NOT IN
    assert eval_predicate(in_(lit("python"), Variable("tags")), row) is True
    assert eval_predicate(not_in(lit("rust"), Variable("tags")), row) is True
    assert eval_predicate(in_(lit("rust"), Variable("tags")), row) is False

    # 2. SIZE / LENGTH function call
    size_expr = FunctionCall(name="SIZE", args=(Variable("tags"),))
    assert eval_value(size_expr, row) == 3

    # 3. Collection quantifiers
    # ALL(score IN scores WHERE score >= 70) -> True
    all_pass = CollectionQuantifier(
        quantifier="ALL",
        elem_var="s",
        collection_expr=Variable("scores"),
        predicate=gt(Variable("s"), lit(70)),
    )
    assert eval_predicate(all_pass, row) is True

    # ANY(score IN scores WHERE score > 90) -> True (92)
    any_high = CollectionQuantifier(
        quantifier="ANY",
        elem_var="s",
        collection_expr=Variable("scores"),
        predicate=gt(Variable("s"), lit(90)),
    )
    assert eval_predicate(any_high, row) is True

    # SINGLE(score IN scores WHERE score > 90) -> True (only 92)
    single_high = CollectionQuantifier(
        quantifier="SINGLE",
        elem_var="s",
        collection_expr=Variable("scores"),
        predicate=gt(Variable("s"), lit(90)),
    )
    assert eval_predicate(single_high, row) is True

    # NONE(score IN scores WHERE score < 50) -> True
    none_fail = CollectionQuantifier(
        quantifier="NONE",
        elem_var="s",
        collection_expr=Variable("scores"),
        predicate=lt(Variable("s"), lit(50)),
    )
    assert eval_predicate(none_fail, row) is True
