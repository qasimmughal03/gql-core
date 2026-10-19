"""GQL-Core source → Query AST.

Wraps the Lark parser. The transformer collapses the parse tree into
the frozen dataclasses defined in `query.ast`. Use parse(src) for the
AST or parse_tree(src) for a Lark pretty-print.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from lark import Lark, Token, Transformer
from lark.exceptions import UnexpectedToken, UnexpectedCharacters

from gql_core.query.ast import (
    And as ASTAnd,
    CallClause,
    Comparison as ASTComparison,
    CreateClause,
    DeleteClause,
    MatchClause,
    MergeAction,
    MergeClause,
    NodePat,
    Not as ASTNot,
    Or as ASTOr,
    OrderBy,
    OrderTerm,
    Pattern,
    PatternPredicate,
    Projection,
    Query,
    Ref,
    RelPat,
    RemoveClause,
    RemoveItem,
    ReturnClause,
    SetClause,
    SetItem,
    UnwindClause,
    WithClause,
)
from gql_core.ir import (
    AggregateExpr,
    Arithmetic,
    Comparison as IRComparison,
    And as IRAnd,
    Or as IROr,
    Not as IRNot,
    FunctionCall,
    In as IRIn,
    IsNotNull as IRIsNotNull,
    IsNull as IRIsNull,
    ListExpr,
    Literal,
    MapExpr,
    Parameter,
    Property,
    RegexMatch,
    StringMatch,
    Variable,
)

_GRAMMAR = Path(__file__).resolve().parent / "grammar.lark"
from gql_core.ir import CaseExpr


def _unescape_cypher_string(raw: str) -> str:
    i = 0
    res = []
    n = len(raw)
    while i < n:
        if raw[i] == "\\":
            if i + 1 >= n:
                raise SyntaxError("Incomplete escape sequence at end of string")
            nxt = raw[i + 1]
            if nxt == "u":
                hex_part = raw[i + 2 : i + 6]
                if len(hex_part) < 4 or not all(c in "0123456789abcdefABCDEF" for c in hex_part):
                    raise SyntaxError(f"Invalid unicode literal escape: \\u{hex_part}")
                res.append(chr(int(hex_part, 16)))
                i += 6
                continue
            elif nxt == "U":
                hex_part = raw[i + 2 : i + 10]
                if len(hex_part) < 8 or not all(c in "0123456789abcdefABCDEF" for c in hex_part):
                    raise SyntaxError(f"Invalid unicode literal escape: \\U{hex_part}")
                res.append(chr(int(hex_part, 16)))
                i += 10
                continue
            elif nxt == "n":
                res.append("\n")
                i += 2
                continue
            elif nxt == "r":
                res.append("\r")
                i += 2
                continue
            elif nxt == "t":
                res.append("\t")
                i += 2
                continue
            elif nxt == "b":
                res.append("\b")
                i += 2
                continue
            elif nxt == "f":
                res.append("\f")
                i += 2
                continue
            elif nxt in ("'", '"', "\\", "/"):
                res.append(nxt)
                i += 2
                continue
            else:
                res.append(nxt)
                i += 2
                continue
        res.append(raw[i])
        i += 1
    return "".join(res)


class CypherPipelineTransformer(Transformer):
    def __init__(self) -> None:
        super().__init__()
        self._anon_counter = 0
        self._parenthesized_ids: set[int] = set()

    def paren_expr(self, items):
        val = items[0]
        self._parenthesized_ids.add(id(val))
        return val

    def ident(self, items):
        s = str(items[0])
        if s.startswith("`") and s.endswith("`"):
            s = s[1:-1]
        return s

    def label_name(self, items):
        s = str(items[0])
        if s.startswith("`") and s.endswith("`"):
            s = s[1:-1]
        return ("label", s)

    def hex_val(self, items):
        text = str(items[0])
        val = int(text, 16)
        if val > 9223372036854775807 or val < -9223372036854775808:
            raise SyntaxError(f"Hex integer out of 64-bit range: {text}")
        return Literal(val)

    def oct_val(self, items):
        text = str(items[0])
        val = int(text, 8)
        if val > 9223372036854775807 or val < -9223372036854775808:
            raise SyntaxError(f"Octal integer out of 64-bit range: {text}")
        return Literal(val)

    def str_val(self, items):
        return Literal(_unescape_cypher_string(items[0][1:-1]))

    def single_str_val(self, items):
        return Literal(_unescape_cypher_string(items[0][1:-1]))

    def num_val(self, items):
        text = str(items[0])
        if "." in text or "e" in text.lower():
            val = float(text)
            if math.isinf(val):
                raise SyntaxError(f"Float literal overflow: {text}")
            return Literal(val)
        val = int(text)
        if val > 9223372036854775807 or val < -9223372036854775808:
            raise SyntaxError(f"Integer literal out of 64-bit range: {text}")
        return Literal(val)

    def true_val(self, _):
        return Literal(True)

    def false_val(self, _):
        return Literal(False)

    def null_val(self, _):
        return Literal(None)

    def value(self, items):
        return items[0]

    def var_ref(self, items):
        s = str(items[0])
        if s.lower() == "null":
            return Literal(None)
        if s.lower() == "true":
            return Literal(True)
        if s.lower() == "false":
            return Literal(False)
        return Variable(s)

    def param(self, items):
        return Parameter(name=str(items[0]))

    def map_entry(self, items):
        k = str(items[0]).strip('"`\'')
        return (k, items[1])

    def map_lit(self, items):
        entries = tuple(items)
        return MapExpr(entries=entries)

    def list_lit(self, items):
        return ListExpr(elements=tuple(items))

    def node_pat(self, items):
        var = None
        labels = []
        props = None
        for it in items:
            if isinstance(it, tuple) and len(it) == 2 and it[0] == "label":
                labels.append(it[1])
            elif isinstance(it, MapExpr):
                props = it
            elif isinstance(it, tuple) and len(it) == 2 and isinstance(it[0], str) and it[0] != "label":
                props = it
            elif isinstance(it, str):
                var = it
        if var is None:
            self._anon_counter += 1
            var = f"__anon_{self._anon_counter}"
        primary_label = labels[0] if labels else None
        filters = ()
        if props and isinstance(props, MapExpr):
            filters = tuple((k, v.value if isinstance(v, Literal) else v) for k, v in props.entries)
        has_map = props is not None
        return NodePat(var=var, label=primary_label, filters=filters, labels=tuple(labels), has_map=has_map)

    def q_star(self, _):
        return ("star", None)

    def q_plus(self, _):
        return ("plus",)

    def q_exactly(self, items):
        return ("exactly", int(items[0]))

    def q_range(self, items):
        nums = [int(it) for it in items if str(it) != ".."]
        return ("range", nums[0], nums[1])

    def q_range_to(self, items):
        nums = [int(it) for it in items if str(it) != ".."]
        return ("range", 1, nums[0])

    def q_range_from(self, items):
        nums = [int(it) for it in items if str(it) != ".."]
        return ("range", nums[0], 999999)

    def edge_var(self, items):
        return ("edge_var", str(items[0]))

    def edge_label(self, items):
        labels = []
        for it in items:
            if isinstance(it, tuple) and it[0] == "label":
                labels.append(it[1])
            elif it and str(it) not in (":", "|"):
                labels.append(str(it).lstrip(":"))
        return ("edge_label", "|".join(labels) if labels else None)

    def _build_rel(self, items, direction: str) -> RelPat:
        var = None
        label = None
        quant = ("one",)
        filters = ()
        for it in items:
            if isinstance(it, tuple):
                if it[0] == "edge_var":
                    var = it[1]
                elif it[0] == "edge_label":
                    label = it[1]
                else:
                    quant = it
            elif isinstance(it, MapExpr):
                filters = tuple((k, v.value if isinstance(v, Literal) else v) for k, v in it.entries)
            elif isinstance(it, str):
                if var is None:
                    var = it
                else:
                    label = it.lstrip(":")
        return RelPat(var=var, label=label, direction=direction, quantifier=quant, filters=filters)

    def rel_out(self, items):
        return self._build_rel(items, "out")

    def rel_in(self, items):
        return self._build_rel(items, "in")

    def rel_undirected(self, items):
        return self._build_rel(items, "undirected")

    def rel_out_anon(self, _):
        return RelPat(var=None, label=None, direction="out", quantifier=("one",))

    def rel_in_anon(self, _):
        return RelPat(var=None, label=None, direction="in", quantifier=("one",))

    def rel_undirected_anon(self, _):
        return RelPat(var=None, label=None, direction="undirected", quantifier=("one",))

    def pattern(self, items):
        path_var = None
        nodes = []
        rels = []
        for it in items:
            if isinstance(it, NodePat):
                nodes.append(it)
            elif isinstance(it, RelPat):
                rels.append(it)
            elif str(it) != "=" and path_var is None:
                path_var = str(it)
        rel_vars = [r.var for r in rels if r.var]
        if len(rel_vars) != len(set(rel_vars)):
            raise SyntaxError(f"Relationship variable cannot be repeated in the same pattern: {rel_vars}")
        return Pattern(nodes=tuple(nodes), rels=tuple(rels), path_var=path_var)

    def pattern_predicate(self, items):
        pat = self.pattern(items)
        if len(pat.nodes) <= 1 and len(pat.rels) == 0:
            raise SyntaxError("InvalidPattern: Pattern predicate must contain at least one relationship pattern")
        return PatternPredicate(pat)

    def pattern_expr(self, items):
        return self.pattern(items)

    # Expressions
    def add_op(self, items):
        return Arithmetic("+", items[0], items[1])

    def sub_op(self, items):
        return Arithmetic("-", items[0], items[1])

    def mul_op(self, items):
        return Arithmetic("*", items[0], items[1])

    def div_op(self, items):
        return Arithmetic("/", items[0], items[1])

    def mod_op(self, items):
        return Arithmetic("%", items[0], items[1])

    def pow_op(self, items):
        return Arithmetic("^", items[0], items[1])

    def neg_op(self, items):
        return Arithmetic("-", Literal(0), items[0])

    def pos_op(self, items):
        return items[0]

    def _to_ref_or_val(self, item: Any) -> Any:
        if isinstance(item, Ref):
            return item
        if isinstance(item, Variable):
            return Ref(var=item.name)
        return item

    def _make_comparison(self, op: str, lhs_raw: Any, rhs_raw: Any):
        if id(lhs_raw) not in self._parenthesized_ids:
            if isinstance(lhs_raw, (ASTComparison, IRComparison)):
                prev_comp = lhs_raw
                middle = prev_comp.rhs
                curr_comp = self._make_single_comparison(op, middle, rhs_raw)
                return ASTAnd((prev_comp, curr_comp))
            elif (
                isinstance(lhs_raw, ASTAnd)
                and len(lhs_raw.children) > 0
                and isinstance(lhs_raw.children[-1], (ASTComparison, IRComparison))
            ):
                prev_comp = lhs_raw.children[-1]
                middle = prev_comp.rhs
                curr_comp = self._make_single_comparison(op, middle, rhs_raw)
                return ASTAnd(tuple(lhs_raw.children) + (curr_comp,))

        return self._make_single_comparison(op, lhs_raw, rhs_raw)

    def _make_single_comparison(self, op: str, lhs_raw: Any, rhs_raw: Any):
        lhs = self._to_ref_or_val(lhs_raw)
        rhs_val = rhs_raw.value if isinstance(rhs_raw, Literal) else rhs_raw
        if isinstance(lhs, Ref):
            return ASTComparison(lhs, op, rhs_val)
        return IRComparison(op, lhs_raw, rhs_raw)

    def eq_op(self, items):
        return self._make_comparison("=", items[0], items[1])

    def neq_op(self, items):
        return self._make_comparison("!=", items[0], items[1])

    def lt_op(self, items):
        return self._make_comparison("<", items[0], items[1])

    def lte_op(self, items):
        return self._make_comparison("<=", items[0], items[1])

    def gt_op(self, items):
        return self._make_comparison(">", items[0], items[1])

    def gte_op(self, items):
        return self._make_comparison(">=", items[0], items[1])

    def and_op(self, items):
        return ASTAnd(children=tuple(items))

    def or_op(self, items):
        return ASTOr(children=tuple(items))

    def not_op(self, items):
        return ASTNot(inner=items[-1])

    def xor_op(self, items):
        return FunctionCall("XOR", tuple(items))

    def is_null_op(self, items):
        return IRIsNull(items[0])

    def is_not_null_op(self, items):
        return IRIsNotNull(items[0])

    def starts_with_op(self, items):
        return StringMatch("STARTS_WITH", items[0], items[1])

    def ends_with_op(self, items):
        return StringMatch("ENDS_WITH", items[0], items[1])

    def contains_op(self, items):
        return StringMatch("CONTAINS", items[0], items[1])

    def regex_op(self, items):
        pat = items[1].value if isinstance(items[1], Literal) else str(items[1])
        return RegexMatch(items[0], pat)

    def in_op(self, items):
        return IRIn(items[0], items[1])

    def prop_op(self, items):
        base = items[0]
        prop = str(items[-1])
        if isinstance(base, Variable):
            return Ref(var=base.name, prop=prop)
        if isinstance(base, Ref):
            return Ref(var=base.var, prop=f"{base.prop}.{prop}" if base.prop else prop)
        if isinstance(base, str):
            return Ref(var=base, prop=prop)
        return FunctionCall("PROPERTY_ACCESS", (base, Literal(prop)))

    def label_check_op(self, items):
        lbl = items[1][1] if isinstance(items[1], tuple) and items[1][0] == "label" else str(items[1])
        base = items[0]
        def _get_target(x):
            if isinstance(x, FunctionCall) and x.name == "HAS_LABEL":
                return _get_target(x.args[0])
            if isinstance(x, ASTAnd) and x.children:
                return _get_target(x.children[-1])
            return x
        real_base = _get_target(base)
        this_check = FunctionCall("HAS_LABEL", (real_base, Literal(lbl)))
        if real_base != base:
            if isinstance(base, ASTAnd):
                return ASTAnd(children=base.children + (this_check,))
            return ASTAnd(children=(base, this_check))
        return this_check

    def index_op(self, items):
        return FunctionCall("INDEX", (items[0], items[1]))

    def slice_op(self, items):
        base = items[0]
        lo = Literal(None)
        hi = Literal(None)
        for i, it in enumerate(items[1:], 1):
            if (isinstance(it, Token) and it.type == "DOTDOT") or str(it) == "..":
                if i > 1:
                    lo = items[1]
                if i + 1 < len(items):
                    hi = items[i + 1]
                break
        return FunctionCall("SLICE", (base, lo, hi))

    def postfix_call(self, items):
        target = items[0]
        args = []
        distinct = False
        for it in items[1:]:
            if isinstance(it, Token) and it.type == "DISTINCT":
                distinct = True
            elif isinstance(it, Token) and it.type == "STAR":
                args.append(Ref("*"))
            else:
                args.append(it)

        if isinstance(target, Variable):
            target_name = target.name
        elif isinstance(target, Ref):
            target_name = f"{target.var}.{target.prop}" if target.prop else target.var
        elif isinstance(target, str):
            target_name = target
        else:
            target_name = str(target)

        fn_name_up = target_name.upper()
        if fn_name_up in ("COUNT", "SUM", "AVG", "MIN", "MAX", "COLLECT"):
            arg_ref = args[0] if args else Ref("*")
            return Projection(expr=arg_ref, agg=fn_name_up, alias=None, distinct=distinct)
        return FunctionCall(target_name, tuple(args))

    def when_then(self, items):
        return (items[0], items[1])

    def case_expr(self, items):
        base_expr = None
        idx = 0
        if not (isinstance(items[0], tuple) and len(items[0]) == 2):
            base_expr = items[0]
            idx = 1

        cases = []
        else_expr = None
        for it in items[idx:]:
            if isinstance(it, tuple) and len(it) == 2:
                w, t = it
                if base_expr is not None:
                    cond = self._make_comparison("=", base_expr, w)
                else:
                    cond = w
                cases.append((cond, t))
            else:
                else_expr = it
        return CaseExpr(cases=tuple(cases), else_expr=else_expr)

    def quantifier_call(self, items):
        fn_name = str(items[0]).upper()
        ident_var = str(items[1])
        coll_expr = items[2]
        where_cond = items[3] if len(items) > 3 else None
        return FunctionCall(fn_name, (Variable(ident_var), coll_expr, where_cond if where_cond is not None else Literal(True)))

    def list_comp_where(self, items):
        return ("__where__", items[0])

    def list_comp_map(self, items):
        return ("__map__", items[0])

    def list_comprehension(self, items):
        ident_var = str(items[0])
        coll_expr = items[1]
        where_cond = None
        map_expr = Variable(ident_var)
        for it in items[2:]:
            if isinstance(it, tuple) and len(it) == 2:
                if it[0] == "__where__":
                    where_cond = it[1]
                elif it[0] == "__map__":
                    map_expr = it[1]
        return FunctionCall("LIST_COMPREHENSION", (Variable(ident_var), coll_expr, where_cond, map_expr))

    def pattern_comprehension(self, items):
        path_var = None
        pat = None
        idx = 0
        if isinstance(items[0], (str, Token, Variable)):
            path_var = str(items[0])
            idx += 1
        if idx < len(items) and isinstance(items[idx], Pattern):
            pat = items[idx]
            idx += 1
        if path_var and pat:
            pat = Pattern(nodes=pat.nodes, rels=pat.rels, path_var=path_var)

        remaining = items[idx:]
        where_cond = None
        map_expr = None
        if len(remaining) == 2:
            where_cond = remaining[0]
            map_expr = remaining[1]
        elif len(remaining) == 1:
            map_expr = remaining[0]

        args = [pat]
        if where_cond is not None:
            args.append(where_cond)
        if map_expr is not None:
            args.append(map_expr)
        return FunctionCall("PATTERN_COMPREHENSION", tuple(args))

    # Clauses
    def where_clause(self, items):
        return items[0]

    def alias(self, items):
        return str(items[0])

    def proj_item(self, items):
        expr = items[0]
        alias = str(items[1]) if len(items) > 1 else None
        if isinstance(expr, Projection):
            return Projection(expr=expr.expr, agg=expr.agg, alias=alias or expr.alias, distinct=expr.distinct)
        return Projection(expr=expr, agg=None, alias=alias)

    def direction(self, items):
        return str(items[0])

    def order_term(self, items):
        expr = items[0]
        if isinstance(expr, Variable):
            expr = Ref(var=expr.name)
        d = items[1] if len(items) > 1 else "ASC"
        return OrderTerm(ref=expr, direction=d)

    def order_by(self, items):
        return OrderBy(terms=tuple(items))

    def skip(self, items):
        v = items[0]
        return ("skip", v.value if isinstance(v, Literal) else v)

    def limit(self, items):
        v = items[0]
        return ("limit", v.value if isinstance(v, Literal) else v)

    def return_clause(self, items):
        distinct = False
        projs = []
        order = None
        skip_v = None
        limit_v = None
        for it in items:
            if isinstance(it, Token) and it.type == "DISTINCT":
                distinct = True
            elif isinstance(it, Projection):
                projs.append(it)
            elif isinstance(it, Token) and it.type == "STAR":
                projs.append(Projection(expr=Ref("*"), agg=None, alias=None))
            elif isinstance(it, OrderBy):
                order = it
            elif hasattr(it, "terms"):
                order = it
            elif isinstance(it, tuple) and len(it) == 2 and it[0] == "skip":
                skip_v = it[1]
            elif isinstance(it, tuple) and len(it) == 2 and it[0] == "limit":
                limit_v = it[1]
        aliases = [p.alias for p in projs if p.alias]
        if len(aliases) != len(set(aliases)):
            raise SyntaxError(f"Duplicate column name '{aliases}' in RETURN")
        return ReturnClause(items=tuple(projs), order_by=order, skip=skip_v, limit=limit_v, distinct=distinct)

    def with_clause(self, items):
        distinct = False
        projs = []
        order = None
        where = None
        skip_v = None
        limit_v = None
        for it in items:
            if isinstance(it, Token) and it.type == "DISTINCT":
                distinct = True
            elif isinstance(it, Projection):
                projs.append(it)
            elif isinstance(it, Token) and it.type == "STAR":
                projs.append(Projection(expr=Ref("*"), agg=None, alias=None))
            elif isinstance(it, OrderBy):
                order = it
            elif hasattr(it, "terms"):
                order = it
            elif isinstance(it, tuple) and len(it) == 2 and it[0] == "skip":
                skip_v = it[1]
            elif isinstance(it, tuple) and len(it) == 2 and it[0] == "limit":
                limit_v = it[1]
            elif not isinstance(it, (Token, Projection, OrderBy)):
                where = it
        aliases = [p.alias for p in projs if p.alias]
        if len(aliases) != len(set(aliases)):
            raise SyntaxError(f"Duplicate column name '{aliases}' in WITH")
        for p in projs:
            if (isinstance(p.expr, Ref) and p.expr.var == "*") or getattr(p, "raw_expr", "") == "*":
                continue
            is_simple_var = (isinstance(p.expr, Variable) and not p.expr.name.startswith("$")) or (isinstance(p.expr, Ref) and p.expr.prop is None and not p.expr.var.startswith("$"))
            if not is_simple_var and not p.alias:
                raise SyntaxError("Expression in WITH must be aliased (e.g. WITH expr AS alias)")
        return WithClause(items=tuple(projs), where=where, order_by=order, skip=skip_v, limit=limit_v, distinct=distinct)

    def unwind_clause(self, items):
        return UnwindClause(expr=items[0], alias=str(items[1]))

    def clause(self, items):
        return items[0]

    def match_clause(self, items):
        patterns = []
        where = None
        for it in items:
            if isinstance(it, Pattern):
                patterns.append(it)
            else:
                where = it
        return MatchClause(patterns=tuple(patterns), where=where, optional=False)

    def optional_match_clause(self, items):
        patterns = []
        where = None
        for it in items:
            if isinstance(it, Pattern):
                patterns.append(it)
            elif isinstance(it, Token):
                continue
            else:
                where = it
        return MatchClause(patterns=tuple(patterns), where=where, optional=True)

    def create_clause(self, items):
        return CreateClause(patterns=tuple(items))

    def set_prop(self, items):
        return SetItem(kind="prop", target=items[0], value=items[1])

    def set_prop_merge(self, items):
        return SetItem(kind="prop_merge", target=items[0], value=items[1])

    def set_labels(self, items):
        labels = [str(x[1] if isinstance(x, tuple) and x[0] == "label" else x) for x in items[1:]]
        return SetItem(kind="labels", target=items[0], labels=tuple(labels))

    def set_clause(self, items):
        return SetClause(items=tuple(items))

    def delete_clause(self, items):
        detach = False
        exprs = []
        for it in items:
            if isinstance(it, Token) and it.type == "DETACH":
                detach = True
            else:
                exprs.append(it)
        return DeleteClause(items=tuple(exprs), detach=detach)

    def remove_labels(self, items):
        target = items[0]
        labels = [str(x[1] if isinstance(x, tuple) and x[0] == "label" else x) for x in items[1:]]
        return RemoveItem(kind="labels", target=target, labels=tuple(labels))

    def remove_prop(self, items):
        prop = str(items[-1])
        ref = self.prop_op(items)
        return RemoveItem(kind="prop", target=ref, prop_name=prop)

    def remove_clause(self, items):
        return RemoveClause(items=tuple(items))

    def merge_action(self, items):
        return items[0]

    def merge_on_create(self, items):
        return MergeAction(on_event="CREATE", items=tuple(items))

    def merge_on_match(self, items):
        return MergeAction(on_event="MATCH", items=tuple(items))

    def merge_clause(self, items):
        pat = items[0]
        actions = [x for x in items[1:] if isinstance(x, MergeAction)]
        return MergeClause(pattern=pat, actions=tuple(actions))

    def proc_name(self, items):
        return ".".join(str(it) for it in items)

    def yield_item(self, items):
        if str(items[0]) == "*":
            return ("yield_item", "*", None)
        orig = str(items[0])
        alias = str(items[1]) if len(items) > 1 else None
        return ("yield_item", orig, alias)

    def call_clause(self, items):
        proc_name = str(items[0])
        args = []
        yields = []
        for it in items[1:]:
            if isinstance(it, tuple) and len(it) == 3 and it[0] == "yield_item":
                yields.append((it[1], it[2]))
            else:
                args.append(it)
        return CallClause(proc_name=proc_name, args=tuple(args), yield_items=tuple(yields))

    def clause_query(self, items):
        clauses = list(items)
        patterns = ()
        where = None
        projections = ()
        order_by = None
        limit_v = None
        distinct = False
        for cl in clauses:
            if isinstance(cl, MatchClause) and not cl.optional and not patterns:
                patterns = cl.patterns
                where = cl.where
            elif isinstance(cl, ReturnClause):
                projections = cl.items
                order_by = cl.order_by
                limit_v = cl.limit
                distinct = cl.distinct
        return Query(
            patterns=patterns,
            where=where,
            projections=projections,
            order_by=order_by,
            limit=limit_v,
            distinct=distinct,
            clauses=tuple(clauses),
        )

    def union_query(self, items):
        queries = []
        union_types = []
        for it in items:
            if isinstance(it, Query):
                queries.append(it)
            elif isinstance(it, Token):
                if it.type == "UNION_KW":
                    union_types.append("UNION")
                elif it.type == "ALL_KW" and union_types:
                    union_types[-1] = "UNION ALL"

        if len(queries) == 1:
            return queries[0]

        u_distinct = set(union_types)
        if len(u_distinct) > 1:
            raise SyntaxError("Mixing UNION and UNION ALL is not allowed without parentheses")

        def _get_cols(q: Query):
            ret = next((cl for cl in reversed(q.clauses) if isinstance(cl, ReturnClause)), None)
            if ret:
                return tuple(p.alias or (p.expr.var if isinstance(p.expr, Ref) and not p.expr.prop else str(p.expr)) for p in ret.items)
            return ()

        cols0 = _get_cols(queries[0])
        for i, q in enumerate(queries[1:], 1):
            colsi = _get_cols(q)
            if cols0 and colsi and cols0 != colsi:
                raise SyntaxError(f"All subqueries in an UNION must have the same column names, got {cols0} and {colsi}")

        main_q = queries[0]
        unions = []
        for u_type, q in zip(union_types, queries[1:]):
            unions.append((u_type, q))

        return Query(
            patterns=main_q.patterns,
            where=main_q.where,
            projections=main_q.projections,
            order_by=main_q.order_by,
            limit=main_q.limit,
            distinct=main_q.distinct,
            unions=tuple(unions),
            clauses=main_q.clauses,
        )

    def query(self, items):
        return items[0]

    def start(self, items):
        return items[0]


def _extract_raw_projections(source: str) -> list[tuple[str, str | None]]:
    m = re.search(r'\bRETURN\b\s+(.*?)(?:\bORDER\s+BY\b|\bLIMIT\b|\bSKIP\b|\bUNION\b|$)', source, re.I | re.DOTALL)
    if not m:
        return []
    clause = m.group(1).strip()
    if clause.upper().startswith("DISTINCT "):
        clause = clause[9:].strip()
    items = []
    depth = 0
    curr = []
    in_quote = None
    for ch in clause:
        if in_quote:
            curr.append(ch)
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'"):
            in_quote = ch
            curr.append(ch)
        elif ch in '([{':
            depth += 1
            curr.append(ch)
        elif ch in ')]}':
            depth -= 1
            curr.append(ch)
        elif ch == ',' and depth == 0:
            items.append(''.join(curr).strip())
            curr = []
        else:
            curr.append(ch)
    if curr:
        items.append(''.join(curr).strip())

    res = []
    for it in items:
        as_m = re.search(r'\s+AS\s+([a-zA-Z0-9_]+)$', it, re.I)
        if as_m:
            res.append((it[:as_m.start()].strip(), as_m.group(1)))
        else:
            res.append((it, None))
    return res


# Singleton parsers
_PARSER_LALR = Lark.open(str(_GRAMMAR), parser="lalr", maybe_placeholders=False)
_PARSER_AST = Lark.open(
    str(_GRAMMAR), parser="lalr", maybe_placeholders=False, transformer=CypherPipelineTransformer()
)
_PARSER_EARLEY: Lark | None = None


def _get_earley_parser() -> Lark:
    global _PARSER_EARLEY
    if _PARSER_EARLEY is None:
        _PARSER_EARLEY = Lark.open(str(_GRAMMAR), parser="earley", maybe_placeholders=False)
    return _PARSER_EARLEY


def parse(source: str) -> Query:
    """Parse a GQL-Core / openCypher source string into a Query AST."""
    if not isinstance(source, str):
        raise TypeError(f"Expected query string, got {type(source).__name__}")
    try:
        q: Query = _PARSER_AST.parse(source)
    except (UnexpectedToken, UnexpectedCharacters):
        try:
            tree = _get_earley_parser().parse(source)
            q: Query = CypherPipelineTransformer().transform(tree)
        except Exception:
            raise
    raw_items = _extract_raw_projections(source)
    if len(raw_items) == len(q.projections):
        new_projs = []
        for orig_p, (raw_expr, _alias) in zip(q.projections, raw_items):
            new_projs.append(
                Projection(
                    expr=orig_p.expr,
                    agg=orig_p.agg,
                    alias=orig_p.alias,
                    raw_expr=raw_expr if not orig_p.alias else None,
                    distinct=getattr(orig_p, "distinct", False),
                )
            )
        new_clauses = []
        for cl in q.clauses:
            if isinstance(cl, ReturnClause) and len(raw_items) == len(cl.items):
                cl_items = []
                for orig_p, (raw_expr, _alias) in zip(cl.items, raw_items):
                    cl_items.append(
                        Projection(
                            expr=orig_p.expr,
                            agg=orig_p.agg,
                            alias=orig_p.alias,
                            raw_expr=raw_expr if not orig_p.alias else None,
                            distinct=getattr(orig_p, "distinct", False),
                        )
                    )
                new_clauses.append(
                    ReturnClause(
                        items=tuple(cl_items),
                        distinct=cl.distinct,
                        order_by=cl.order_by,
                        skip=cl.skip,
                        limit=cl.limit,
                    )
                )
            else:
                new_clauses.append(cl)
        q = Query(
            patterns=q.patterns,
            where=q.where,
            projections=tuple(new_projs),
            order_by=q.order_by,
            limit=q.limit,
            distinct=q.distinct,
            unions=q.unions,
            clauses=tuple(new_clauses),
        )
    return q


def parse_tree(source: str) -> str:
    """Return Lark's pretty-printed parse tree (no transformer)."""
    return _PARSER_LALR.parse(source).pretty()
