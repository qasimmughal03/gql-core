"""Official CypherBench execution-accuracy metric, without the Neo4j driver.

Adapted from megagonlabs/cypherbench ``cypherbench/metrics/execution_accuracy.py``
(Apache-2.0), which itself adapts taoyds/test-suite-sql-eval. The comparison
logic (``to_hashable``, ``result_eq`` and helpers) is unchanged; only the
Neo4j-specific parts are replaced so results produced by GQL-Core can be
compared with the gold answers stored in CypherBench's ``answer_json``.

Like the original, order matters only when the gold query contains ORDER BY,
and columns may be permuted.
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from itertools import product
from typing import Any, List, Set, Tuple


def to_hashable(obj: Any, unorder_list: bool = True) -> Any:
    if isinstance(obj, str):
        return str(obj)  # CypherTemporalValue -> plain ISO string (== neo4j Date.iso_format())
    if isinstance(obj, (tuple, int, float, bool, type(None))):
        return obj
    if isinstance(obj, (list, tuple)):
        if unorder_list:
            return tuple(sorted(to_hashable(item) for item in obj))
        return tuple(to_hashable(item) for item in obj)
    if isinstance(obj, set):
        return tuple(sorted(to_hashable(item) for item in obj))
    if isinstance(obj, dict):
        return tuple(sorted((to_hashable(k), to_hashable(v)) for k, v in obj.items()))
    raise TypeError(f"Unhashable type: {type(obj)}")


def permute_tuple(element: Tuple, perm: Tuple) -> Tuple:
    assert len(element) == len(perm)
    return tuple([element[i] for i in perm])


def unorder_row(row: Tuple) -> Tuple:
    return tuple(sorted(row, key=lambda x: str(x) + str(type(x))))


def quick_rej(result1: List[Tuple], result2: List[Tuple], order_matters: bool) -> bool:
    s1 = [unorder_row(row) for row in result1]
    s2 = [unorder_row(row) for row in result2]
    if order_matters:
        return s1 == s2
    return set(s1) == set(s2)


def multiset_eq(l1: List, l2: List) -> bool:
    if len(l1) != len(l2):
        return False
    d: dict = defaultdict(int)
    for e in l1:
        d[e] += 1
    for e in l2:
        d[e] -= 1
        if d[e] < 0:
            return False
    return True


def get_constraint_permutation(tab1_sets_by_columns: List[Set], result2: List[Tuple]):
    num_cols = len(result2[0])
    perm_constraints = [{i for i in range(num_cols)} for _ in range(num_cols)]
    if num_cols <= 3:
        return product(*perm_constraints)
    rng = random.Random(0)
    for _ in range(20):
        random_tab2_row = rng.choice(result2)
        for tab1_col in range(num_cols):
            for tab2_col in set(perm_constraints[tab1_col]):
                if random_tab2_row[tab2_col] not in tab1_sets_by_columns[tab1_col]:
                    perm_constraints[tab1_col].remove(tab2_col)
    return product(*perm_constraints)


def result_eq(result1: List[Tuple], result2: List[Tuple], order_matters: bool) -> bool:
    if len(result1) == 0 and len(result2) == 0:
        return True
    if len(result1) != len(result2):
        return False
    num_cols = len(result1[0])
    if len(result2[0]) != num_cols:
        return False
    if not quick_rej(result1, result2, order_matters):
        return False
    tab1_sets_by_columns = [{row[i] for row in result1} for i in range(num_cols)]
    for perm in get_constraint_permutation(tab1_sets_by_columns, result2):
        if len(perm) != len(set(perm)):
            continue
        result2_perm = result2 if num_cols == 1 else [permute_tuple(e, perm) for e in result2]
        if order_matters:
            if result1 == result2_perm:
                return True
        elif set(result1) == set(result2_perm) and multiset_eq(result1, result2_perm):
            return True
    return False


def gold_tuples(answer_json: str) -> List[Tuple]:
    """CypherBench stores gold results as a JSON list of rows (lists of values)."""
    rows = json.loads(answer_json)
    return [tuple(to_hashable(v) for v in row) for row in rows]


def pred_tuples(rows: list[dict]) -> List[Tuple]:
    if not rows:
        return []
    keys = list(rows[0].keys())
    return [tuple(to_hashable(row.get(k)) for k in keys) for row in rows]


def execution_accuracy(pred_rows: list[dict], answer_json: str, gold_cypher: str) -> float:
    """1.0 if the predicted result equals the gold result under CypherBench's rules."""
    gold = gold_tuples(answer_json)
    pred = pred_tuples(pred_rows)
    if not pred and not gold:
        return 1.0
    if not pred or not gold:
        return 0.0
    return float(result_eq(gold, pred, order_matters="order by" in gold_cypher.lower()))
