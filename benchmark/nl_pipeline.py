"""The GQL-Core NL pipeline as used by the NL->Cypher benchmarks (``--pipeline``).

Same steps as :func:`gql_core.ask`, applied to a benchmark's own prompt:

1. the prompt's schema is followed by :func:`gql_core.nl.value_hints` (stored values of
   low-cardinality string properties);
2. the model's query is repaired with :func:`gql_core.nl.repair_query` (relationship
   directions the schema forbids, string literals that match a stored value only
   when case is ignored);
3. it is executed; if it fails, returns no rows, or returns exact duplicate rows, the
   model sees :func:`gql_core.nl.execution_feedback` once and may revise the query,
   which is repaired and executed the same way. A revision that fails never replaces
   a query that ran, and one that returns no rows never replaces one that returned rows.

Nothing here sees a gold query or a gold answer.
"""

from __future__ import annotations

from typing import Any, Callable

from gql_core.nl import execution_feedback, feedback_prompt, keep_revision, repair_query

STORED_VALUES_HEADER = "\n\nStored values of some string properties (use exactly as written):\n"


def schema_with_hints(schema_str: str, hints: str) -> str:
    return schema_str + (STORED_VALUES_HEADER + hints if hints else "")


def answer(prompt: str, *, graph: Any, triples: set, index: Any, generate: Callable[[str, str], dict],
           execute: Callable[[str], list[dict]], clean: Callable[[str], str], qid: str,
           max_retries: int = 1) -> dict[str, Any]:
    """Run the pipeline for one question.

    ``generate(prompt, cache_key)`` returns a cached-or-fresh generation record with
    ``raw``; ``execute(query)`` runs a query (raising on error or timeout).
    Returns the final query, its rows (or error), and every attempt.
    """
    attempts: list[dict[str, Any]] = []

    def attempt(raw: str) -> dict[str, Any]:
        model_query = clean(raw)
        fix = repair_query(model_query, graph, triples=triples, index=index)
        rec: dict[str, Any] = {"model_query": model_query, "query": fix.query, "repairs": fix.changes,
                               "rows": None, "error": None}
        try:
            rec["rows"] = execute(fix.query)
        except Exception as exc:  # noqa: BLE001
            rec["error"] = f"{type(exc).__name__}: {exc}"[:300]
        rec["feedback"] = execution_feedback(rec["rows"], rec["error"])
        attempts.append(rec)
        return rec

    best = attempt(generate(prompt, qid)["raw"])
    for i in range(max_retries):
        if best["feedback"] is None:
            break
        rec = attempt(generate(feedback_prompt(prompt, best["query"], best["feedback"]), f"{qid}#retry{i + 1}")["raw"])
        if keep_revision(best["rows"], best["error"], rec["rows"], rec["error"]):
            best = rec
    return {"best": best, "attempts": attempts}
