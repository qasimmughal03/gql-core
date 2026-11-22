"""Building blocks for asking a property graph questions in natural language.

An LLM writes the Cypher; GQL-Core makes it more likely to be the query that was
meant, using only the graph itself and the engine's own results:

* :func:`value_hints` lists the stored values of low-cardinality string properties
  (for example every ``Position.name``), so the model can use them verbatim;
* :func:`repair_query` reverses relationship arrows the schema makes impossible and
  grounds string literals to stored values;
* :func:`execution_feedback` describes a failed, empty or duplicate-laden result,
  so the model can be asked once to revise its query (:func:`feedback_prompt`).

None of these sees an expected answer. :func:`gql_core.ask` uses all of them.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from gql_core.graph import PropertyGraph
from gql_core.query.directions import correct_relationship_directions, schema_triples
from gql_core.query.values import ValueIndex, ground_values, value_index


def value_hints(graph: PropertyGraph, labels: Iterable[str] | None = None, *,
                max_distinct: int = 30, max_len: int = 60) -> str:
    """One line per ``Label.property`` whose string values have at most ``max_distinct``
    distinct values, listing them exactly as stored. Empty if there are none."""
    lines = []
    nodes = graph._nodes
    for label in sorted(labels if labels is not None else graph._by_label):
        values: dict[str, set[str]] = {}
        dropped: set[str] = set()
        for nid in graph._by_label.get(label, ()):
            for prop, v in nodes[nid].props.items():
                if prop in dropped or not isinstance(v, str):
                    continue
                vs = values.setdefault(prop, set())
                vs.add(v)
                if len(vs) > max_distinct or len(v) > max_len:
                    dropped.add(prop)
                    values.pop(prop, None)
        for prop in sorted(values):
            vals = ", ".join(repr(v) for v in sorted(values[prop]))
            lines.append(f"{label}.{prop}: {vals}")
    return "\n".join(lines)


@dataclass
class Repair:
    """Result of :func:`repair_query`."""

    query: str
    original: str
    changes: list[str] = field(default_factory=list)


def repair_query(query: str, graph: PropertyGraph, *, triples: set | None = None,
                 index: ValueIndex | None = None) -> Repair:
    """Correct relationship directions, then ground string literals to stored values.

    ``triples`` (from :func:`gql_core.schema_triples`) and ``index`` can be passed to
    avoid rescanning a large graph for every query.
    """
    d = correct_relationship_directions(query, triples if triples is not None else schema_triples(graph))
    v = ground_values(d.query, graph, index or value_index(graph))
    return Repair(query=v.query, original=query, changes=d.changes + v.changes)


def execution_feedback(rows: list[dict] | None, error: str | None = None) -> str | None:
    """A short description of a result worth a second look, or None if it looks fine."""
    if error is not None:
        return f"Running it failed with this error: {error}"
    if not rows:
        return "It ran but returned no rows."
    keys = [tuple(sorted((k, repr(v)) for k, v in r.items())) for r in rows]
    dupes = len(keys) - len(set(keys))
    if dupes:
        return (f"It returned {len(rows)} rows, {dupes} of which repeat an earlier row exactly. "
                "If the question asks for distinct entities, each should appear once.")
    return None


def keep_revision(prev_rows: list[dict] | None, prev_error: str | None,
                  new_rows: list[dict] | None, new_error: str | None) -> bool:
    """Whether a revised query should replace the previous one.

    A revision that fails never replaces one that ran, and one that returns no rows
    never replaces one that returned rows; otherwise the revision is kept.
    """
    if new_error is not None:
        return prev_error is not None
    if not new_rows and prev_error is None and prev_rows:
        return False
    return True


FEEDBACK_TEMPLATE ="""{prompt}{previous}

That query was run on the graph. {feedback}
If the query does not answer the question, write a corrected query. If it already does, repeat it unchanged.
Output only the Cypher query in a single line.
Cypher: """


def feedback_prompt(prompt: str, previous_query: str, feedback: str) -> str:
    """The original prompt, the model's query, and what happened when it ran."""
    return FEEDBACK_TEMPLATE.format(prompt=prompt, previous=previous_query, feedback=feedback)
