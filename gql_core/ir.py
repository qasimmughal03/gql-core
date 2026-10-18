"""Canonical Typed Query Intermediate Representation (IR) for GQL-Core.

This module defines an immutable, composable, strongly typed logical AST / IR
that cleanly separates:
1. Value expressions (Literal, Variable, Property, Parameter, Arithmetic, FunctionCall,
   ListExpr, MapExpr, TemporalExpr, AggregateExpr, CaseExpr, CoalesceExpr)
2. Boolean predicates (And, Or, Not, Comparison, IsNull, IsNotNull, IsMissing, IsPresent,
   In, NotIn, Between, NotBetween, StringMatch, RegexMatch, Exists, NotExists,
   QuantifiedRel, CollectionQuantifier, TypePredicate)
3. Relational and graph operations (Scan, Expand, RecursiveExpand, Filter, Project,
   Join, SemiJoin, AntiJoin, LeftOuterJoin, Union, Intersect, Except,
   GroupBy, Having, Distinct, Sort, Limit)
4. Ontology expressions (TypeMembershipExpr, SubtypeMembershipExpr, RelExistenceExpr,
   InverseRelExpr, SymmetricRelExpr, TransitiveClosureExpr, DerivedRelExpr,
   CardinalityConstraintExpr, TypedInferenceRuleExpr)

Includes safe, versioned JSON serialization and deserialization (zero eval/exec).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gql_core.temporal import Date, DateTime, Duration, Interval, Time
from gql_core.types import DataType


# ═══════════════════════════════════════════════════════════════════════
# 1. VALUE EXPRESSIONS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ValueExpr:
    """Base class for all typed value expressions."""


@dataclass(frozen=True)
class Literal(ValueExpr):
    value: Any
    data_type: DataType = DataType.ANY


@dataclass(frozen=True)
class Variable(ValueExpr):
    name: str
    data_type: DataType = DataType.ANY


@dataclass(frozen=True)
class Property(ValueExpr):
    var: str
    prop: str
    data_type: DataType = DataType.ANY


@dataclass(frozen=True)
class Parameter(ValueExpr):
    name: str
    data_type: DataType = DataType.ANY


@dataclass(frozen=True)
class Arithmetic(ValueExpr):
    op: str  # '+', '-', '*', '/', '%'
    lhs: ValueExpr
    rhs: ValueExpr


@dataclass(frozen=True)
class FunctionCall(ValueExpr):
    name: str
    args: tuple[ValueExpr, ...]


@dataclass(frozen=True)
class ListExpr(ValueExpr):
    elements: tuple[ValueExpr, ...]


@dataclass(frozen=True)
class MapExpr(ValueExpr):
    entries: tuple[tuple[str, ValueExpr], ...]


@dataclass(frozen=True)
class TemporalExpr(ValueExpr):
    type_name: str  # 'DATE' | 'TIME' | 'DATETIME' | 'DURATION' | 'INTERVAL'
    args: tuple[ValueExpr, ...]


@dataclass(frozen=True)
class AggregateExpr(ValueExpr):
    func: str  # 'COUNT' | 'SUM' | 'AVG' | 'MIN' | 'MAX' | 'COLLECT'
    expr: ValueExpr | None = None
    distinct: bool = False


@dataclass(frozen=True)
class CaseExpr(ValueExpr):
    cases: tuple[tuple[BoolExpr, ValueExpr], ...]
    else_expr: ValueExpr | None = None


@dataclass(frozen=True)
class CoalesceExpr(ValueExpr):
    expressions: tuple[ValueExpr, ...]


# ═══════════════════════════════════════════════════════════════════════
# 2. BOOLEAN PREDICATES
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class BoolExpr:
    """Base class for all typed Boolean expressions."""


@dataclass(frozen=True)
class And(BoolExpr):
    children: tuple[BoolExpr, ...]


@dataclass(frozen=True)
class Or(BoolExpr):
    children: tuple[BoolExpr, ...]


@dataclass(frozen=True)
class Not(BoolExpr):
    inner: BoolExpr


@dataclass(frozen=True)
class Comparison(BoolExpr):
    op: str  # '=', '!=', '<', '<=', '>', '>='
    lhs: ValueExpr
    rhs: ValueExpr


@dataclass(frozen=True)
class IsNull(BoolExpr):
    expr: ValueExpr


@dataclass(frozen=True)
class IsNotNull(BoolExpr):
    expr: ValueExpr


@dataclass(frozen=True)
class IsMissing(BoolExpr):
    var: str
    prop: str


@dataclass(frozen=True)
class IsPresent(BoolExpr):
    var: str
    prop: str


@dataclass(frozen=True)
class In(BoolExpr):
    element: ValueExpr
    collection: ValueExpr


@dataclass(frozen=True)
class NotIn(BoolExpr):
    element: ValueExpr
    collection: ValueExpr


@dataclass(frozen=True)
class Between(BoolExpr):
    expr: ValueExpr
    low: ValueExpr
    high: ValueExpr


@dataclass(frozen=True)
class NotBetween(BoolExpr):
    expr: ValueExpr
    low: ValueExpr
    high: ValueExpr


@dataclass(frozen=True)
class StringMatch(BoolExpr):
    op: str  # 'STARTS_WITH' | 'ENDS_WITH' | 'CONTAINS'
    string_expr: ValueExpr
    pattern_expr: ValueExpr


@dataclass(frozen=True)
class RegexMatch(BoolExpr):
    string_expr: ValueExpr
    pattern: str


@dataclass(frozen=True)
class PatternExpr:
    """A graph pattern component used in EXISTS/NOT_EXISTS or quantified relations."""
    source_var: str
    rel_label: str | None
    direction: str  # 'out' | 'in' | 'undirected'
    target_var: str
    target_label: str | None = None
    min_hops: int = 1
    max_hops: int = 1
    target_filter: BoolExpr | None = None


@dataclass(frozen=True)
class Exists(BoolExpr):
    """EXISTS predicate over a graph pattern or subquery."""
    subquery_or_pattern: PatternExpr | RelOp


@dataclass(frozen=True)
class NotExists(BoolExpr):
    """NOT EXISTS predicate over a graph pattern or subquery."""
    subquery_or_pattern: PatternExpr | RelOp


@dataclass(frozen=True)
class QuantifiedRel(BoolExpr):
    """Quantified reasoning over related entities.

    quantifier: 'ANY' | 'ALL' | 'NONE' | 'SINGLE' | 'AT_LEAST' | 'AT_MOST' | 'EXACTLY' | 'COUNT_SATISFYING'
    count_mode: 'entities' | 'relationships' | 'paths' | 'rows'
    """
    quantifier: str
    source_var: str
    rel_label: str | None
    direction: str
    target_var: str
    target_label: str | None = None
    predicate: BoolExpr | None = None
    count: int | None = None
    count_mode: str = "entities"


@dataclass(frozen=True)
class CollectionQuantifier(BoolExpr):
    """Quantification over a collection: ANY/ALL/NONE/SINGLE(elem IN list WHERE predicate)."""
    quantifier: str  # 'ANY' | 'ALL' | 'NONE' | 'SINGLE'
    elem_var: str
    collection_expr: ValueExpr
    predicate: BoolExpr


@dataclass(frozen=True)
class TypePredicate(BoolExpr):
    """Type / label check on a graph entity."""
    var: str
    target_type: str
    is_exact: bool = False  # False allows subtypes; True requires exact type


# ═══════════════════════════════════════════════════════════════════════
# 3. RELATIONAL AND GRAPH OPERATIONS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ProjectItem:
    expr: ValueExpr
    alias: str


@dataclass(frozen=True)
class SortTerm:
    expr: ValueExpr
    direction: str = "ASC"  # 'ASC' or 'DESC'


@dataclass(frozen=True)
class RelOp:
    """Base class for all relational / graph operations."""


@dataclass(frozen=True)
class Scan(RelOp):
    var: str
    label: str | None = None
    inline_filters: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class Expand(RelOp):
    from_var: str
    edge_var: str | None = None
    edge_label: str | None = None
    direction: str = "out"  # 'out' | 'in' | 'undirected'
    quantifier: tuple = ("one",)
    to_var: str = ""
    to_label: str | None = None
    to_inline_filters: tuple[tuple[str, Any], ...] = ()
    optional: bool = False
    input: RelOp | None = None


@dataclass(frozen=True)
class RecursiveExpand(RelOp):
    from_var: str
    edge_var: str | None = None
    edge_label: str | None = None
    direction: str = "out"
    min_hops: int = 1
    max_hops: int | None = 1
    to_var: str = ""
    to_label: str | None = None
    trail_semantics: bool = True
    input: RelOp | None = None


@dataclass(frozen=True)
class Filter(RelOp):
    input: RelOp
    predicate: BoolExpr


@dataclass(frozen=True)
class Project(RelOp):
    input: RelOp
    projections: tuple[ProjectItem, ...]
    distinct: bool = False


@dataclass(frozen=True)
class Join(RelOp):
    left: RelOp
    right: RelOp
    on: tuple[str, ...]
    kind: str = "INNER"  # 'INNER' | 'LEFT_OUTER' | 'SEMI' | 'ANTI' | 'CROSS'


@dataclass(frozen=True)
class SemiJoin(RelOp):
    left: RelOp
    right: RelOp
    on: tuple[str, ...]


@dataclass(frozen=True)
class AntiJoin(RelOp):
    left: RelOp
    right: RelOp
    on: tuple[str, ...]


@dataclass(frozen=True)
class LeftOuterJoin(RelOp):
    left: RelOp
    right: RelOp
    on: tuple[str, ...]


@dataclass(frozen=True)
class Union(RelOp):
    left: RelOp
    right: RelOp
    all: bool = False


@dataclass(frozen=True)
class Intersect(RelOp):
    left: RelOp
    right: RelOp
    all: bool = False


@dataclass(frozen=True)
class Except(RelOp):
    left: RelOp
    right: RelOp
    all: bool = False


@dataclass(frozen=True)
class GroupBy(RelOp):
    input: RelOp
    keys: tuple[str, ...]
    aggregates: tuple[ProjectItem, ...]


@dataclass(frozen=True)
class Having(RelOp):
    input: RelOp
    predicate: BoolExpr


@dataclass(frozen=True)
class Distinct(RelOp):
    input: RelOp


@dataclass(frozen=True)
class Sort(RelOp):
    input: RelOp
    terms: tuple[SortTerm, ...]


@dataclass(frozen=True)
class Limit(RelOp):
    input: RelOp
    count: int
    offset: int = 0


# ═══════════════════════════════════════════════════════════════════════
# 4. ONTOLOGY EXPRESSIONS
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class OntologyExpr:
    """Base class for ontology-level expressions."""


@dataclass(frozen=True)
class TypeMembershipExpr(OntologyExpr):
    var: str
    entity_type: str


@dataclass(frozen=True)
class SubtypeMembershipExpr(OntologyExpr):
    var: str
    supertype: str


@dataclass(frozen=True)
class RelExistenceExpr(OntologyExpr):
    source_var: str
    rel_type: str
    target_var: str


@dataclass(frozen=True)
class InverseRelExpr(OntologyExpr):
    rel_type: str
    inverse_name: str


@dataclass(frozen=True)
class SymmetricRelExpr(OntologyExpr):
    rel_type: str


@dataclass(frozen=True)
class TransitiveClosureExpr(OntologyExpr):
    source_var: str
    rel_type: str
    target_var: str


@dataclass(frozen=True)
class DerivedRelExpr(OntologyExpr):
    name: str
    premises: tuple[Any, ...]


@dataclass(frozen=True)
class CardinalityConstraintExpr(OntologyExpr):
    rel_type: str
    min_outgoing: int | None = None
    max_outgoing: int | None = None
    min_incoming: int | None = None
    max_incoming: int | None = None


@dataclass(frozen=True)
class TypedInferenceRuleExpr(OntologyExpr):
    name: str
    head: Any
    body: tuple[Any, ...]


# ═══════════════════════════════════════════════════════════════════════
# 5. SAFE VERSIONED SERIALIZATION / DESERIALIZATION
# ═══════════════════════════════════════════════════════════════════════

IR_FORMAT_VERSION = "1.0"


def expr_to_dict(expr: Any) -> dict[str, Any]:
    """Serialize any ValueExpr or BoolExpr to a safe, versioned dict."""
    if expr is None:
        return {"_type": "None"}
    if isinstance(expr, Literal):
        val = expr.value
        if isinstance(val, (Date, Time, DateTime, Duration)):
            val = str(val)
        return {"_type": "Literal", "value": val, "data_type": expr.data_type.value}
    if isinstance(expr, Variable):
        return {"_type": "Variable", "name": expr.name, "data_type": expr.data_type.value}
    if isinstance(expr, Property):
        return {"_type": "Property", "var": expr.var, "prop": expr.prop, "data_type": expr.data_type.value}
    if isinstance(expr, Parameter):
        return {"_type": "Parameter", "name": expr.name, "data_type": expr.data_type.value}
    if isinstance(expr, Arithmetic):
        return {"_type": "Arithmetic", "op": expr.op, "lhs": expr_to_dict(expr.lhs), "rhs": expr_to_dict(expr.rhs)}
    if isinstance(expr, FunctionCall):
        return {"_type": "FunctionCall", "name": expr.name, "args": [expr_to_dict(a) for a in expr.args]}
    if isinstance(expr, ListExpr):
        return {"_type": "ListExpr", "elements": [expr_to_dict(e) for e in expr.elements]}
    if isinstance(expr, MapExpr):
        return {"_type": "MapExpr", "entries": [[k, expr_to_dict(v)] for k, v in expr.entries]}
    if isinstance(expr, AggregateExpr):
        return {
            "_type": "AggregateExpr",
            "func": expr.func,
            "expr": expr_to_dict(expr.expr) if expr.expr else None,
            "distinct": expr.distinct,
        }
    if isinstance(expr, CaseExpr):
        return {
            "_type": "CaseExpr",
            "cases": [[expr_to_dict(c), expr_to_dict(r)] for c, r in expr.cases],
            "else_expr": expr_to_dict(expr.else_expr) if expr.else_expr else None,
        }
    if isinstance(expr, CoalesceExpr):
        return {"_type": "CoalesceExpr", "expressions": [expr_to_dict(e) for e in expr.expressions]}
    if isinstance(expr, And):
        return {"_type": "And", "children": [expr_to_dict(c) for c in expr.children]}
    if isinstance(expr, Or):
        return {"_type": "Or", "children": [expr_to_dict(c) for c in expr.children]}
    if isinstance(expr, Not):
        return {"_type": "Not", "inner": expr_to_dict(expr.inner)}
    if isinstance(expr, Comparison):
        return {"_type": "Comparison", "op": expr.op, "lhs": expr_to_dict(expr.lhs), "rhs": expr_to_dict(expr.rhs)}
    if isinstance(expr, IsNull):
        return {"_type": "IsNull", "expr": expr_to_dict(expr.expr)}
    if isinstance(expr, IsNotNull):
        return {"_type": "IsNotNull", "expr": expr_to_dict(expr.expr)}
    if isinstance(expr, IsMissing):
        return {"_type": "IsMissing", "var": expr.var, "prop": expr.prop}
    if isinstance(expr, IsPresent):
        return {"_type": "IsPresent", "var": expr.var, "prop": expr.prop}
    if isinstance(expr, In):
        return {"_type": "In", "element": expr_to_dict(expr.element), "collection": expr_to_dict(expr.collection)}
    if isinstance(expr, NotIn):
        return {"_type": "NotIn", "element": expr_to_dict(expr.element), "collection": expr_to_dict(expr.collection)}
    if isinstance(expr, Between):
        return {"_type": "Between", "expr": expr_to_dict(expr.expr), "low": expr_to_dict(expr.low), "high": expr_to_dict(expr.high)}
    if isinstance(expr, NotBetween):
        return {"_type": "NotBetween", "expr": expr_to_dict(expr.expr), "low": expr_to_dict(expr.low), "high": expr_to_dict(expr.high)}
    if isinstance(expr, StringMatch):
        return {"_type": "StringMatch", "op": expr.op, "string_expr": expr_to_dict(expr.string_expr), "pattern_expr": expr_to_dict(expr.pattern_expr)}
    if isinstance(expr, RegexMatch):
        return {"_type": "RegexMatch", "string_expr": expr_to_dict(expr.string_expr), "pattern": expr.pattern}
    if isinstance(expr, PatternExpr):
        return {
            "_type": "PatternExpr",
            "source_var": expr.source_var,
            "rel_label": expr.rel_label,
            "direction": expr.direction,
            "target_var": expr.target_var,
            "target_label": expr.target_label,
            "min_hops": expr.min_hops,
            "max_hops": expr.max_hops,
            "target_filter": expr_to_dict(expr.target_filter) if expr.target_filter else None,
        }
    if isinstance(expr, Exists):
        return {"_type": "Exists", "target": expr_to_dict(expr.subquery_or_pattern) if isinstance(expr.subquery_or_pattern, PatternExpr) else plan_to_dict(expr.subquery_or_pattern)}
    if isinstance(expr, NotExists):
        return {"_type": "NotExists", "target": expr_to_dict(expr.subquery_or_pattern) if isinstance(expr.subquery_or_pattern, PatternExpr) else plan_to_dict(expr.subquery_or_pattern)}
    if isinstance(expr, QuantifiedRel):
        return {
            "_type": "QuantifiedRel",
            "quantifier": expr.quantifier,
            "source_var": expr.source_var,
            "rel_label": expr.rel_label,
            "direction": expr.direction,
            "target_var": expr.target_var,
            "target_label": expr.target_label,
            "predicate": expr_to_dict(expr.predicate) if expr.predicate else None,
            "count": expr.count,
            "count_mode": expr.count_mode,
        }
    if isinstance(expr, CollectionQuantifier):
        return {
            "_type": "CollectionQuantifier",
            "quantifier": expr.quantifier,
            "elem_var": expr.elem_var,
            "collection_expr": expr_to_dict(expr.collection_expr),
            "predicate": expr_to_dict(expr.predicate),
        }
    if isinstance(expr, TypePredicate):
        return {"_type": "TypePredicate", "var": expr.var, "target_type": expr.target_type, "is_exact": expr.is_exact}
    raise TypeError(f"Unknown expression type for serialization: {type(expr).__name__}")


def expr_from_dict(d: dict[str, Any]) -> Any:
    """Deserialize a ValueExpr or BoolExpr from a safe dict."""
    if not isinstance(d, dict) or "_type" not in d:
        return d
    t = d["_type"]
    if t == "None":
        return None
    if t == "Literal":
        return Literal(value=d["value"], data_type=DataType(d.get("data_type", "ANY")))
    if t == "Variable":
        return Variable(name=d["name"], data_type=DataType(d.get("data_type", "ANY")))
    if t == "Property":
        return Property(var=d["var"], prop=d["prop"], data_type=DataType(d.get("data_type", "ANY")))
    if t == "Parameter":
        return Parameter(name=d["name"], data_type=DataType(d.get("data_type", "ANY")))
    if t == "Arithmetic":
        return Arithmetic(op=d["op"], lhs=expr_from_dict(d["lhs"]), rhs=expr_from_dict(d["rhs"]))
    if t == "FunctionCall":
        return FunctionCall(name=d["name"], args=tuple(expr_from_dict(a) for a in d["args"]))
    if t == "ListExpr":
        return ListExpr(elements=tuple(expr_from_dict(e) for e in d["elements"]))
    if t == "MapExpr":
        return MapExpr(entries=tuple((k, expr_from_dict(v)) for k, v in d["entries"]))
    if t == "AggregateExpr":
        return AggregateExpr(
            func=d["func"],
            expr=expr_from_dict(d["expr"]) if d.get("expr") else None,
            distinct=d.get("distinct", False),
        )
    if t == "CaseExpr":
        return CaseExpr(
            cases=tuple((expr_from_dict(c), expr_from_dict(r)) for c, r in d["cases"]),
            else_expr=expr_from_dict(d["else_expr"]) if d.get("else_expr") else None,
        )
    if t == "CoalesceExpr":
        return CoalesceExpr(expressions=tuple(expr_from_dict(e) for e in d["expressions"]))
    if t == "And":
        return And(children=tuple(expr_from_dict(c) for c in d["children"]))
    if t == "Or":
        return Or(children=tuple(expr_from_dict(c) for c in d["children"]))
    if t == "Not":
        return Not(inner=expr_from_dict(d["inner"]))
    if t == "Comparison":
        return Comparison(op=d["op"], lhs=expr_from_dict(d["lhs"]), rhs=expr_from_dict(d["rhs"]))
    if t == "IsNull":
        return IsNull(expr=expr_from_dict(d["expr"]))
    if t == "IsNotNull":
        return IsNotNull(expr=expr_from_dict(d["expr"]))
    if t == "IsMissing":
        return IsMissing(var=d["var"], prop=d["prop"])
    if t == "IsPresent":
        return IsPresent(var=d["var"], prop=d["prop"])
    if t == "In":
        return In(element=expr_from_dict(d["element"]), collection=expr_from_dict(d["collection"]))
    if t == "NotIn":
        return NotIn(element=expr_from_dict(d["element"]), collection=expr_from_dict(d["collection"]))
    if t == "Between":
        return Between(expr=expr_from_dict(d["expr"]), low=expr_from_dict(d["low"]), high=expr_from_dict(d["high"]))
    if t == "NotBetween":
        return NotBetween(expr=expr_from_dict(d["expr"]), low=expr_from_dict(d["low"]), high=expr_from_dict(d["high"]))
    if t == "StringMatch":
        return StringMatch(op=d["op"], string_expr=expr_from_dict(d["string_expr"]), pattern_expr=expr_from_dict(d["pattern_expr"]))
    if t == "RegexMatch":
        return RegexMatch(string_expr=expr_from_dict(d["string_expr"]), pattern=d["pattern"])
    if t == "PatternExpr":
        return PatternExpr(
            source_var=d["source_var"],
            rel_label=d.get("rel_label"),
            direction=d.get("direction", "out"),
            target_var=d["target_var"],
            target_label=d.get("target_label"),
            min_hops=d.get("min_hops", 1),
            max_hops=d.get("max_hops", 1),
            target_filter=expr_from_dict(d["target_filter"]) if d.get("target_filter") else None,
        )
    if t == "Exists":
        target = d["target"]
        sub = expr_from_dict(target) if target.get("_type") == "PatternExpr" else plan_from_dict(target)
        return Exists(subquery_or_pattern=sub)
    if t == "NotExists":
        target = d["target"]
        sub = expr_from_dict(target) if target.get("_type") == "PatternExpr" else plan_from_dict(target)
        return NotExists(subquery_or_pattern=sub)
    if t == "QuantifiedRel":
        return QuantifiedRel(
            quantifier=d["quantifier"],
            source_var=d["source_var"],
            rel_label=d.get("rel_label"),
            direction=d.get("direction", "out"),
            target_var=d["target_var"],
            target_label=d.get("target_label"),
            predicate=expr_from_dict(d["predicate"]) if d.get("predicate") else None,
            count=d.get("count"),
            count_mode=d.get("count_mode", "entities"),
        )
    if t == "CollectionQuantifier":
        return CollectionQuantifier(
            quantifier=d["quantifier"],
            elem_var=d["elem_var"],
            collection_expr=expr_from_dict(d["collection_expr"]),
            predicate=expr_from_dict(d["predicate"]),
        )
    if t == "TypePredicate":
        return TypePredicate(var=d["var"], target_type=d["target_type"], is_exact=d.get("is_exact", False))
    raise ValueError(f"Unknown serialized expression type: {t!r}")


def plan_to_dict(op: RelOp) -> dict[str, Any]:
    """Serialize a RelOp plan tree to a safe, versioned dict."""
    d: dict[str, Any] = {"version": IR_FORMAT_VERSION, "_type": type(op).__name__}
    if isinstance(op, Scan):
        d["var"] = op.var
        d["label"] = op.label
        d["inline_filters"] = [list(f) for f in op.inline_filters]
    elif isinstance(op, Expand):
        if op.input:
            d["input"] = plan_to_dict(op.input)
        d["from_var"] = op.from_var
        d["edge_var"] = op.edge_var
        d["edge_label"] = op.edge_label
        d["direction"] = op.direction
        d["quantifier"] = list(op.quantifier)
        d["to_var"] = op.to_var
        d["to_label"] = op.to_label
        d["to_inline_filters"] = [list(f) for f in op.to_inline_filters]
        d["optional"] = op.optional
    elif isinstance(op, RecursiveExpand):
        if op.input:
            d["input"] = plan_to_dict(op.input)
        d["from_var"] = op.from_var
        d["edge_var"] = op.edge_var
        d["edge_label"] = op.edge_label
        d["direction"] = op.direction
        d["min_hops"] = op.min_hops
        d["max_hops"] = op.max_hops
        d["to_var"] = op.to_var
        d["to_label"] = op.to_label
        d["trail_semantics"] = op.trail_semantics
    elif isinstance(op, Filter):
        d["input"] = plan_to_dict(op.input)
        d["predicate"] = expr_to_dict(op.predicate)
    elif isinstance(op, Project):
        d["input"] = plan_to_dict(op.input)
        d["projections"] = [{"expr": expr_to_dict(p.expr), "alias": p.alias} for p in op.projections]
        d["distinct"] = op.distinct
    elif isinstance(op, Join):
        d["left"] = plan_to_dict(op.left)
        d["right"] = plan_to_dict(op.right)
        d["on"] = list(op.on)
        d["kind"] = op.kind
    elif isinstance(op, SemiJoin):
        d["left"] = plan_to_dict(op.left)
        d["right"] = plan_to_dict(op.right)
        d["on"] = list(op.on)
    elif isinstance(op, AntiJoin):
        d["left"] = plan_to_dict(op.left)
        d["right"] = plan_to_dict(op.right)
        d["on"] = list(op.on)
    elif isinstance(op, LeftOuterJoin):
        d["left"] = plan_to_dict(op.left)
        d["right"] = plan_to_dict(op.right)
        d["on"] = list(op.on)
    elif isinstance(op, (Union, Intersect, Except)):
        d["left"] = plan_to_dict(op.left)
        d["right"] = plan_to_dict(op.right)
        d["all"] = op.all
    elif isinstance(op, GroupBy):
        d["input"] = plan_to_dict(op.input)
        d["keys"] = list(op.keys)
        d["aggregates"] = [{"expr": expr_to_dict(p.expr), "alias": p.alias} for p in op.aggregates]
    elif isinstance(op, Having):
        d["input"] = plan_to_dict(op.input)
        d["predicate"] = expr_to_dict(op.predicate)
    elif isinstance(op, Distinct):
        d["input"] = plan_to_dict(op.input)
    elif isinstance(op, Sort):
        d["input"] = plan_to_dict(op.input)
        d["terms"] = [{"expr": expr_to_dict(t.expr), "direction": t.direction} for t in op.terms]
    elif isinstance(op, Limit):
        d["input"] = plan_to_dict(op.input)
        d["count"] = op.count
        d["offset"] = op.offset
    else:
        raise TypeError(f"Unknown operator for serialization: {type(op).__name__}")
    return d


def plan_from_dict(d: dict[str, Any]) -> RelOp:
    """Deserialize a RelOp plan tree from a safe dict."""
    if not isinstance(d, dict) or "_type" not in d:
        raise ValueError(f"Invalid plan dictionary format: {d}")
    t = d["_type"]
    if t == "Scan":
        return Scan(
            var=d["var"],
            label=d.get("label"),
            inline_filters=tuple(tuple(f) for f in d.get("inline_filters", ())),
        )
    if t == "Expand":
        return Expand(
            from_var=d["from_var"],
            edge_var=d.get("edge_var"),
            edge_label=d.get("edge_label"),
            direction=d.get("direction", "out"),
            quantifier=tuple(d.get("quantifier", ("one",))),
            to_var=d.get("to_var", ""),
            to_label=d.get("to_label"),
            to_inline_filters=tuple(tuple(f) for f in d.get("to_inline_filters", ())),
            optional=d.get("optional", False),
            input=plan_from_dict(d["input"]) if d.get("input") else None,
        )
    if t == "RecursiveExpand":
        return RecursiveExpand(
            from_var=d["from_var"],
            edge_var=d.get("edge_var"),
            edge_label=d.get("edge_label"),
            direction=d.get("direction", "out"),
            min_hops=d.get("min_hops", 1),
            max_hops=d.get("max_hops"),
            to_var=d["to_var"],
            to_label=d.get("to_label"),
            trail_semantics=d.get("trail_semantics", True),
            input=plan_from_dict(d["input"]) if d.get("input") else None,
        )
    if t == "Filter":
        return Filter(
            input=plan_from_dict(d["input"]),
            predicate=expr_from_dict(d["predicate"]),
        )
    if t == "Project":
        return Project(
            input=plan_from_dict(d["input"]),
            projections=tuple(ProjectItem(expr=expr_from_dict(p["expr"]), alias=p["alias"]) for p in d["projections"]),
            distinct=d.get("distinct", False),
        )
    if t == "Join":
        return Join(
            left=plan_from_dict(d["left"]),
            right=plan_from_dict(d["right"]),
            on=tuple(d.get("on", ())),
            kind=d.get("kind", "INNER"),
        )
    if t == "SemiJoin":
        return SemiJoin(
            left=plan_from_dict(d["left"]),
            right=plan_from_dict(d["right"]),
            on=tuple(d.get("on", ())),
        )
    if t == "AntiJoin":
        return AntiJoin(
            left=plan_from_dict(d["left"]),
            right=plan_from_dict(d["right"]),
            on=tuple(d.get("on", ())),
        )
    if t == "LeftOuterJoin":
        return LeftOuterJoin(
            left=plan_from_dict(d["left"]),
            right=plan_from_dict(d["right"]),
            on=tuple(d.get("on", ())),
        )
    if t == "Union":
        return Union(
            left=plan_from_dict(d["left"]),
            right=plan_from_dict(d["right"]),
            all=d.get("all", False),
        )
    if t == "Intersect":
        return Intersect(
            left=plan_from_dict(d["left"]),
            right=plan_from_dict(d["right"]),
            all=d.get("all", False),
        )
    if t == "Except":
        return Except(
            left=plan_from_dict(d["left"]),
            right=plan_from_dict(d["right"]),
            all=d.get("all", False),
        )
    if t == "GroupBy":
        return GroupBy(
            input=plan_from_dict(d["input"]),
            keys=tuple(d.get("keys", ())),
            aggregates=tuple(ProjectItem(expr=expr_from_dict(p["expr"]), alias=p["alias"]) for p in d["aggregates"]),
        )
    if t == "Having":
        return Having(
            input=plan_from_dict(d["input"]),
            predicate=expr_from_dict(d["predicate"]),
        )
    if t == "Distinct":
        return Distinct(input=plan_from_dict(d["input"]))
    if t == "Sort":
        return Sort(
            input=plan_from_dict(d["input"]),
            terms=tuple(SortTerm(expr=expr_from_dict(t["expr"]), direction=t.get("direction", "ASC")) for t in d["terms"]),
        )
    if t == "Limit":
        return Limit(
            input=plan_from_dict(d["input"]),
            count=d["count"],
            offset=d.get("offset", 0),
        )
    raise ValueError(f"Unknown operator in serialized plan: {t!r}")
