"""Fluent / programmatic builder API for constructing typed query plans in GQL-Core.

Allows programmatic, type-safe construction of query plans without generating
raw Cypher text.
"""

from __future__ import annotations

import json
from typing import Any

from gql_core.graph import PropertyGraph
from gql_core.ir import (
    AggregateExpr,
    And,
    AntiJoin,
    Arithmetic,
    Between,
    BoolExpr,
    CaseExpr,
    CoalesceExpr,
    CollectionQuantifier,
    Comparison,
    Distinct,
    Except,
    Exists,
    Expand,
    Filter,
    FunctionCall,
    GroupBy,
    Having,
    In,
    Intersect,
    IsNotNull,
    IsNull,
    IsMissing,
    IsPresent,
    Join,
    LeftOuterJoin,
    Limit,
    ListExpr,
    Literal,
    MapExpr,
    Not,
    NotBetween,
    NotExists,
    NotIn,
    Or,
    PatternExpr,
    Project,
    ProjectItem,
    Property,
    QuantifiedRel,
    RecursiveExpand,
    RegexMatch,
    RelOp,
    Scan,
    SemiJoin,
    Sort,
    SortTerm,
    StringMatch,
    TemporalExpr,
    TypePredicate,
    Union,
    ValueExpr,
    Variable,
    plan_from_dict,
    plan_to_dict,
)
from gql_core.physical.engine import execute_physical_plan, explain_plan, optimize_plan
from gql_core.types import DataType
from gql_core.validator_ir import ValidationReport, validate_logical_plan


# ═══════════════════════════════════════════════════════════════════════
# HELPER EXPRESSION CONSTRUCTORS
# ═══════════════════════════════════════════════════════════════════════


def var(name: str, data_type: DataType = DataType.ANY) -> Variable:
    return Variable(name=name, data_type=data_type)


def col(name: str, data_type: DataType = DataType.ANY) -> ValueExpr:
    if "." in name:
        var_part, prop_part = name.split(".", 1)
        return Property(var=var_part, prop=prop_part, data_type=data_type)
    return Variable(name=name, data_type=data_type)


def prop(var_name: str, prop_name: str, data_type: DataType = DataType.ANY) -> Property:
    return Property(var=var_name, prop=prop_name, data_type=data_type)


def lit(val: Any, data_type: DataType = DataType.ANY) -> Literal:
    return Literal(value=val, data_type=data_type)


def and_(*children: BoolExpr) -> And:
    return And(children=children)


def or_(*children: BoolExpr) -> Or:
    return Or(children=children)


def not_(inner: BoolExpr) -> Not:
    return Not(inner=inner)


def eq(lhs: ValueExpr, rhs: ValueExpr) -> Comparison:
    return Comparison(op="=", lhs=lhs, rhs=rhs)


def neq(lhs: ValueExpr, rhs: ValueExpr) -> Comparison:
    return Comparison(op="!=", lhs=lhs, rhs=rhs)


def lt(lhs: ValueExpr, rhs: ValueExpr) -> Comparison:
    return Comparison(op="<", lhs=lhs, rhs=rhs)


def lte(lhs: ValueExpr, rhs: ValueExpr) -> Comparison:
    return Comparison(op="<=", lhs=lhs, rhs=rhs)


def gt(lhs: ValueExpr, rhs: ValueExpr) -> Comparison:
    return Comparison(op=">", lhs=lhs, rhs=rhs)


def gte(lhs: ValueExpr, rhs: ValueExpr) -> Comparison:
    return Comparison(op=">=", lhs=lhs, rhs=rhs)


def is_null(expr: ValueExpr) -> IsNull:
    return IsNull(expr=expr)


def is_not_null(expr: ValueExpr) -> IsNotNull:
    return IsNotNull(expr=expr)


def is_missing(var_name: str, prop_name: str) -> IsMissing:
    return IsMissing(var=var_name, prop=prop_name)


def is_present(var_name: str, prop_name: str) -> IsPresent:
    return IsPresent(var=var_name, prop=prop_name)


def in_(elem: ValueExpr, collection: ValueExpr) -> In:
    return In(element=elem, collection=collection)


def not_in(elem: ValueExpr, collection: ValueExpr) -> NotIn:
    return NotIn(element=elem, collection=collection)


def between(expr: ValueExpr, low: ValueExpr, high: ValueExpr) -> Between:
    return Between(expr=expr, low=low, high=high)


def not_between(expr: ValueExpr, low: ValueExpr, high: ValueExpr) -> NotBetween:
    return NotBetween(expr=expr, low=low, high=high)


def starts_with(string_expr: ValueExpr, pattern_expr: ValueExpr) -> StringMatch:
    return StringMatch(op="STARTS_WITH", string_expr=string_expr, pattern_expr=pattern_expr)


def ends_with(string_expr: ValueExpr, pattern_expr: ValueExpr) -> StringMatch:
    return StringMatch(op="ENDS_WITH", string_expr=string_expr, pattern_expr=pattern_expr)


def contains(string_expr: ValueExpr, pattern_expr: ValueExpr) -> StringMatch:
    return StringMatch(op="CONTAINS", string_expr=string_expr, pattern_expr=pattern_expr)


def regex(string_expr: ValueExpr, pattern: str) -> RegexMatch:
    return RegexMatch(string_expr=string_expr, pattern=pattern)


def pattern(
    source_var: str,
    rel_label: str | None,
    target_var: str,
    direction: str = "out",
    target_label: str | None = None,
    min_hops: int = 1,
    max_hops: int = 1,
    target_filter: BoolExpr | None = None,
) -> PatternExpr:
    return PatternExpr(
        source_var=source_var,
        rel_label=rel_label,
        direction=direction,
        target_var=target_var,
        target_label=target_label,
        min_hops=min_hops,
        max_hops=max_hops,
        target_filter=target_filter,
    )


def exists(subquery_or_pattern: PatternExpr | RelOp) -> Exists:
    return Exists(subquery_or_pattern=subquery_or_pattern)


def not_exists(subquery_or_pattern: PatternExpr | RelOp) -> NotExists:
    return NotExists(subquery_or_pattern=subquery_or_pattern)


def quantified_rel(
    quantifier: str,
    source_var: str,
    rel_label: str | None,
    target_var: str,
    direction: str = "out",
    target_label: str | None = None,
    predicate: BoolExpr | None = None,
    count: int | None = None,
    count_mode: str = "entities",
) -> QuantifiedRel:
    return QuantifiedRel(
        quantifier=quantifier,
        source_var=source_var,
        rel_label=rel_label,
        direction=direction,
        target_var=target_var,
        target_label=target_label,
        predicate=predicate,
        count=count,
        count_mode=count_mode,
    )


def at_least_rel(count: int, source_var: str, rel_label: str | None, target_var: str, predicate: BoolExpr | None = None, **kwargs) -> QuantifiedRel:
    return quantified_rel("AT_LEAST", source_var, rel_label, target_var, predicate=predicate, count=count, **kwargs)


def all_rel(source_var: str, rel_label: str | None, target_var: str, predicate: BoolExpr | None = None, **kwargs) -> QuantifiedRel:
    return quantified_rel("ALL", source_var, rel_label, target_var, predicate=predicate, **kwargs)


def none_rel(source_var: str, rel_label: str | None, target_var: str, predicate: BoolExpr | None = None, **kwargs) -> QuantifiedRel:
    return quantified_rel("NONE", source_var, rel_label, target_var, predicate=predicate, **kwargs)


def any_rel(source_var: str, rel_label: str | None, target_var: str, predicate: BoolExpr | None = None, **kwargs) -> QuantifiedRel:
    return quantified_rel("ANY", source_var, rel_label, target_var, predicate=predicate, **kwargs)


def single_rel(source_var: str, rel_label: str | None, target_var: str, predicate: BoolExpr | None = None, **kwargs) -> QuantifiedRel:
    return quantified_rel("SINGLE", source_var, rel_label, target_var, predicate=predicate, **kwargs)


def count(expr: ValueExpr | None = None, distinct: bool = False) -> AggregateExpr:
    return AggregateExpr(func="COUNT", expr=expr, distinct=distinct)


def sum_(expr: ValueExpr) -> AggregateExpr:
    return AggregateExpr(func="SUM", expr=expr)


def avg(expr: ValueExpr) -> AggregateExpr:
    return AggregateExpr(func="AVG", expr=expr)


def min_(expr: ValueExpr) -> AggregateExpr:
    return AggregateExpr(func="MIN", expr=expr)


def max_(expr: ValueExpr) -> AggregateExpr:
    return AggregateExpr(func="MAX", expr=expr)


def collect(expr: ValueExpr, distinct: bool = False) -> AggregateExpr:
    return AggregateExpr(func="COLLECT", expr=expr, distinct=distinct)


def case_when(cases: tuple[tuple[BoolExpr, ValueExpr], ...] | list[tuple[BoolExpr, ValueExpr]], else_expr: ValueExpr | None = None) -> CaseExpr:
    return CaseExpr(cases=tuple(cases), else_expr=else_expr)


def coalesce(*expressions: ValueExpr) -> CoalesceExpr:
    return CoalesceExpr(expressions=expressions)


# ═══════════════════════════════════════════════════════════════════════
# FLUENT PLAN BUILDER
# ═══════════════════════════════════════════════════════════════════════


class PlanBuilder:
    """Fluent API for programmatically building typed logical query plans."""

    def __init__(self, root: RelOp | None = None) -> None:
        self._current: RelOp | None = root

    @classmethod
    def scan(cls, var_name: str, label: str | None = None, **inline_filters: Any) -> PlanBuilder:
        filters = tuple(inline_filters.items())
        return cls(Scan(var=var_name, label=label, inline_filters=filters))

    def expand(
        self,
        edge_label: str | None = None,
        to_var: str = "",
        to_label: str | None = None,
        direction: str = "out",
        edge_var: str | None = None,
        optional: bool = False,
        from_var: str | None = None,
        **to_filters: Any,
    ) -> PlanBuilder:
        if self._current is None:
            raise ValueError("Cannot expand without an initial scan or input operator")
        # Infer from_var if not explicitly passed
        src_var = from_var
        if src_var is None:
            if isinstance(self._current, Scan):
                src_var = self._current.var
            elif isinstance(self._current, Expand):
                src_var = self._current.to_var
            else:
                src_var = "a"

        op = Expand(
            from_var=src_var,
            edge_var=edge_var,
            edge_label=edge_label,
            direction=direction,
            to_var=to_var,
            to_label=to_label,
            to_inline_filters=tuple(to_filters.items()),
            optional=optional,
        )
        return PlanBuilder(
            Expand(
                input=self._current,
                from_var=src_var,
                edge_var=edge_var,
                edge_label=edge_label,
                direction=direction,
                to_var=to_var,
                to_label=to_label,
                to_inline_filters=tuple(to_filters.items()),
                optional=optional,
            )
        )

    def recursive_expand(
        self,
        edge_label: str | None = None,
        to_var: str = "",
        to_label: str | None = None,
        direction: str = "out",
        min_hops: int = 1,
        max_hops: int | None = None,
        edge_var: str | None = None,
        trail_semantics: bool = True,
        from_var: str | None = None,
    ) -> PlanBuilder:
        if self._current is None:
            raise ValueError("Cannot recursive_expand without an input operator")
        src_var = from_var
        if src_var is None:
            if isinstance(self._current, Scan):
                src_var = self._current.var
            elif isinstance(self._current, (Expand, RecursiveExpand)):
                src_var = self._current.to_var
            else:
                src_var = "a"

        return PlanBuilder(
            RecursiveExpand(
                input=self._current,
                from_var=src_var,
                edge_var=edge_var,
                edge_label=edge_label,
                direction=direction,
                min_hops=min_hops,
                max_hops=max_hops,
                to_var=to_var,
                to_label=to_label,
                trail_semantics=trail_semantics,
            )
        )

    def filter(self, predicate: BoolExpr) -> PlanBuilder:
        if self._current is None:
            raise ValueError("Cannot filter empty plan")
        return PlanBuilder(Filter(input=self._current, predicate=predicate))

    def project(self, *items: tuple[ValueExpr, str] | ProjectItem, distinct: bool = False) -> PlanBuilder:
        if self._current is None:
            raise ValueError("Cannot project empty plan")
        proj_items = []
        for it in items:
            if isinstance(it, ProjectItem):
                proj_items.append(it)
            elif isinstance(it, tuple):
                if len(it) == 2:
                    if isinstance(it[0], str) and isinstance(it[1], ValueExpr):
                        proj_items.append(ProjectItem(expr=it[1], alias=it[0]))
                    else:
                        proj_items.append(ProjectItem(expr=it[0], alias=it[1]))
                else:
                    raise TypeError(f"Invalid projection item tuple: {it}")
            elif isinstance(it, dict):
                for k, v in it.items():
                    if isinstance(v, ValueExpr):
                        proj_items.append(ProjectItem(expr=v, alias=str(k)))
                    elif isinstance(k, ValueExpr):
                        proj_items.append(ProjectItem(expr=k, alias=str(v)))
                    else:
                        raise TypeError(f"Invalid dict projection item: {k}: {v}")
            else:
                raise TypeError(f"Invalid projection item: {it}")
        return PlanBuilder(Project(input=self._current, projections=tuple(proj_items), distinct=distinct))

    def join(self, right: RelOp | PlanBuilder, on: tuple[str, ...], kind: str = "INNER") -> PlanBuilder:
        if self._current is None:
            raise ValueError("Cannot join onto empty plan")
        r_op = right.build() if isinstance(right, PlanBuilder) else right
        return PlanBuilder(Join(left=self._current, right=r_op, on=on, kind=kind))

    def semi_join(self, right: RelOp | PlanBuilder, on: tuple[str, ...]) -> PlanBuilder:
        return self.join(right, on=on, kind="SEMI")

    def anti_join(self, right: RelOp | PlanBuilder, on: tuple[str, ...]) -> PlanBuilder:
        return self.join(right, on=on, kind="ANTI")

    def left_join(self, right: RelOp | PlanBuilder, on: tuple[str, ...]) -> PlanBuilder:
        return self.join(right, on=on, kind="LEFT_OUTER")

    def union(self, right: RelOp | PlanBuilder, all: bool = False) -> PlanBuilder:
        if self._current is None:
            raise ValueError("Cannot union empty plan")
        r_op = right.build() if isinstance(right, PlanBuilder) else right
        return PlanBuilder(Union(left=self._current, right=r_op, all=all))

    def intersect(self, right: RelOp | PlanBuilder, all: bool = False) -> PlanBuilder:
        if self._current is None:
            raise ValueError("Cannot intersect empty plan")
        r_op = right.build() if isinstance(right, PlanBuilder) else right
        return PlanBuilder(Intersect(left=self._current, right=r_op, all=all))

    def except_(self, right: RelOp | PlanBuilder, all: bool = False) -> PlanBuilder:
        if self._current is None:
            raise ValueError("Cannot except empty plan")
        r_op = right.build() if isinstance(right, PlanBuilder) else right
        return PlanBuilder(Except(left=self._current, right=r_op, all=all))

    def group_by(self, keys: tuple[str, ...] | list[str], *aggregates: tuple[ValueExpr, str] | ProjectItem) -> PlanBuilder:
        if self._current is None:
            raise ValueError("Cannot group empty plan")
        agg_items = []
        for it in aggregates:
            if isinstance(it, ProjectItem):
                agg_items.append(it)
            elif isinstance(it, tuple):
                if len(it) == 2:
                    if isinstance(it[0], str) and isinstance(it[1], ValueExpr):
                        agg_items.append(ProjectItem(expr=it[1], alias=it[0]))
                    else:
                        agg_items.append(ProjectItem(expr=it[0], alias=it[1]))
                else:
                    raise TypeError(f"Invalid aggregate item tuple: {it}")
            else:
                raise TypeError(f"Invalid aggregate item: {it}")
        return PlanBuilder(GroupBy(input=self._current, keys=tuple(keys), aggregates=tuple(agg_items)))

    def having(self, predicate: BoolExpr) -> PlanBuilder:
        if self._current is None:
            raise ValueError("Cannot apply having to empty plan")
        return PlanBuilder(Having(input=self._current, predicate=predicate))

    def distinct(self) -> PlanBuilder:
        if self._current is None:
            raise ValueError("Cannot distinct empty plan")
        return PlanBuilder(Distinct(input=self._current))

    def sort(self, *terms: tuple[ValueExpr, str] | SortTerm) -> PlanBuilder:
        if self._current is None:
            raise ValueError("Cannot sort empty plan")
        sterms = []
        for t in terms:
            if isinstance(t, SortTerm):
                sterms.append(t)
            elif isinstance(t, tuple):
                sterms.append(SortTerm(expr=t[0], direction=t[1]))
        return PlanBuilder(Sort(input=self._current, terms=tuple(sterms)))

    def limit(self, count: int, offset: int = 0) -> PlanBuilder:
        if self._current is None:
            raise ValueError("Cannot limit empty plan")
        return PlanBuilder(Limit(input=self._current, count=count, offset=offset))

    def build(self) -> RelOp:
        if self._current is None:
            raise ValueError("Empty plan")
        return self._current

    def validate(self, strict: bool = True) -> ValidationReport:
        return validate_logical_plan(self.build(), strict=strict)

    def optimize(self) -> PlanBuilder:
        return PlanBuilder(optimize_plan(self.build()))

    def execute(self, graph: PropertyGraph) -> list[dict[str, Any]]:
        self.validate(strict=True)
        return execute_physical_plan(self.build(), graph)

    def explain(self) -> str:
        return explain_plan(self.build())

    def to_dict(self) -> dict[str, Any]:
        return plan_to_dict(self.build())

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PlanBuilder:
        return cls(plan_from_dict(d))

    @classmethod
    def from_json(cls, s: str) -> PlanBuilder:
        return cls.from_dict(json.loads(s))
