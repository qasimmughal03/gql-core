"""Natural-Language query interface for GQL-Core.

Bridges human natural language to formal GQL-Core execution using a two-tier
architecture:
  1. Translate natural-language question -> formal GQL-Core query.
  2. Execute formal query on PropertyGraph with 100% deterministic precision.

Supports pluggable LLM backends:
  - Custom callable: client(prompt) -> str
  - Local Ollama: client="ollama" or OLLAMA_URL env var
  - Direct execution via ask(graph, question)
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections import defaultdict
from typing import Any, Callable

from gql_core.graph import PropertyGraph
from gql_core.query.executor import run as run_query
from gql_core.nl import execution_feedback, feedback_prompt, keep_revision, repair_query, value_hints
from gql_core.query.directions import schema_triples
from gql_core.query.parser import parse as parse_query


def extract_schema_summary(graph: PropertyGraph) -> dict[str, Any]:
    """Inspect a PropertyGraph and extract its dynamic schema.

    Discovers all node labels, their observed properties, edge labels,
    endpoint relationships, and edge properties.
    """
    node_props: dict[str, set[str]] = defaultdict(set)
    for label, nids in graph._by_label.items():
        for nid in list(nids)[:50]:  # Sample up to 50 nodes per label
            node = graph._nodes.get(nid)
            if node:
                node_props[label].update(node.props.keys())

    edge_info: dict[str, dict[str, Any]] = defaultdict(lambda: {"connections": set(), "props": set()})
    # Every (source label, target label) pair that occurs, counting all labels of a node,
    # so the prompt never shows a direction the graph does not have.
    for rel, src_label, dst_label in schema_triples(graph):
        edge_info[rel]["connections"].add((src_label, dst_label))
    for label, eids in graph._edge_by_label.items():
        for eid in list(eids)[:100]:  # Sample up to 100 edges per label for property names
            edge = graph._edges.get(eid)
            if edge:
                edge_info[label]["props"].update(edge.props.keys())

    return {
        "node_labels": {k: sorted(v) for k, v in node_props.items()},
        "edge_labels": {
            k: {
                "connections": [f"(:{src})-[:{k}]->(:{dst})" for src, dst in sorted(v["connections"])],
                "props": sorted(v["props"]),
            }
            for k, v in edge_info.items()
        },
    }


def format_schema_prompt(graph: PropertyGraph) -> str:
    """Format the dynamic schema of a PropertyGraph into a system prompt."""
    schema = extract_schema_summary(graph)
    lines = [
        "You are a GQL-Core query generator.",
        "Your job: translate the user's natural-language question into a single valid GQL-Core query.",
        "Output ONLY the raw GQL-Core query. Do not wrap in markdown fences. Do not explain.",
        "",
        "=== GRAPH SCHEMA ===",
        "NODE LABELS AND OBSERVED PROPERTIES:",
    ]
    for label, props in schema["node_labels"].items():
        props_str = ", ".join(props) if props else "(no properties)"
        lines.append(f"  ({label}) : {props_str}")

    lines.append("\nRELATIONSHIPS AND PATTERNS:")
    for label, info in schema["edge_labels"].items():
        conns_str = ", ".join(info["connections"]) if info["connections"] else f"[:{label}]"
        props_str = f" [props: {', '.join(info['props'])}]" if info["props"] else ""
        lines.append(f"  {conns_str}{props_str}")

    lines.extend([
        "",
        "=== GQL-CORE GRAMMAR RULES ===",
        "- MATCH pattern (e.g. MATCH (a:Person)-[:KNOWS]->(b:Person))",
        "- Bounded regular path queries: [:CONNECTED*1..3] or [:CONNECTED*]",
        "- Undirected patterns: (a)-[:CONNECTED]-(b)",
        "- WHERE clause with AND, OR, NOT, comparisons (=, !=, <, <=, >, >=)",
        "- RETURN clause with projections, aliases (AS), aggregations (COUNT, SUM, AVG, MIN, MAX)",
        "- ORDER BY and LIMIT (e.g. ORDER BY count DESC LIMIT 5)",
        "- String values in double quotes: \"value\"",
    ])
    hints = value_hints(graph)
    if hints:
        lines.extend(["", "=== STORED VALUES (use exactly as written) ===", hints])
    return "\n".join(lines)


def clean_generated_gql(raw: str) -> str:
    """Clean LLM output, removing markdown fences and surrounding commentary."""
    text = raw.strip()
    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:gql|cypher)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()
    # If multiple lines, extract first MATCH query block
    lines = text.splitlines()
    query_lines = [l for l in lines if not l.startswith("#") and not l.startswith("//")]
    cleaned = " ".join(" ".join(query_lines).split())
    # Strip leading/trailing quotes
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1]
    return cleaned.strip()


def _call_ollama(prompt: str, question: str, model: str = "llama3", base_url: str = "http://localhost:11434") -> str:
    """Send question to a local Ollama instance."""
    url = f"{base_url.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "options": {"temperature": 0.0},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("message", {}).get("content", "")


def translate_to_gql(
    graph: PropertyGraph,
    question: str,
    *,
    client: Callable[[str], str] | str | None = None,
    model: str = "llama3",
    correct_directions: bool = True,
) -> str:
    """Translate a natural-language question into a valid GQL-Core query string.

    Parameters
    ----------
    graph : PropertyGraph
        The target graph (used to dynamically derive the schema prompt).
    question : str
        The user's natural language question.
    client : callable or "ollama" or None
        LLM backend. If None, checks for OLLAMA_URL or default localhost.
    model : str
        Model name (default: "llama3").
    correct_directions : bool
        Repair the generated query with :func:`gql_core.nl.repair_query`: reverse
        relationship arrows that are impossible in this graph (for example
        ``(:Person)-[:written_by]->(:Movie)`` when every ``written_by`` edge goes from a
        Movie to a Person), and ground string literals to stored values (``'Center'`` to
        ``'center'``) when exactly one stored value matches ignoring case.
    """
    system_prompt = format_schema_prompt(graph)
    full_prompt = f"{system_prompt}\n\nUSER QUESTION: {question}\nGQL-CORE QUERY:"
    raw_output = _generate(full_prompt, system_prompt, question, client=client, model=model)
    return _finish(raw_output, graph, correct_directions)


def _generate(full_prompt: str, system_prompt: str, user_text: str, *,
              client: Callable[[str], str] | str | None, model: str) -> str:
    if callable(client):
        return client(full_prompt)
    if client == "ollama" or client is None:
        base_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        try:
            return _call_ollama(system_prompt, user_text, model=model, base_url=base_url)
        except Exception as exc:
            raise ConnectionError(
                f"Could not reach Ollama at {base_url} ({exc}). "
                "Ensure Ollama is running or pass a custom callable client=..."
            ) from exc
    raise ValueError(f"Unsupported client type: {type(client).__name__}")


def _finish(raw_output: str, graph: PropertyGraph, repair: bool) -> str:
    cleaned_gql = clean_generated_gql(raw_output)
    # Validate syntax early
    try:
        parse_query(cleaned_gql)
    except Exception as exc:
        raise ValueError(f"Generated query is not valid GQL-Core: {cleaned_gql!r} ({exc})") from exc
    if repair:
        cleaned_gql = repair_query(cleaned_gql, graph).query
    return cleaned_gql


def ask(
    graph: PropertyGraph,
    question: str,
    *,
    client: Callable[[str], str] | str | None = None,
    model: str = "llama3",
    explain: bool = False,
    correct_directions: bool = True,
    max_retries: int = 1,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Ask a natural-language question against a PropertyGraph.

    Translates the question to GQL-Core, executes it on the graph, and returns
    the exact query results.

    Parameters
    ----------
    graph : PropertyGraph
        Target graph.
    question : str
        Natural language question (e.g., 'Who are Alice's friends?').
    client : callable or 'ollama', optional
        LLM backend.
    model : str, optional
        Model identifier.
    explain : bool, optional
        If True, returns a dict with 'query', 'results', and 'count'.
    correct_directions : bool, optional
        Repair relationship directions and string literals (default True); see
        :func:`translate_to_gql`.
    max_retries : int, optional
        If the query fails, returns no rows, or returns duplicate rows, show the model
        what happened and let it revise the query, up to this many times (default 1).
        With ``explain=True`` every attempt is listed under ``attempts``.

    Returns
    -------
    list[dict] or dict
        Deterministic query results.
    """
    system_prompt = format_schema_prompt(graph)
    full_prompt = f"{system_prompt}\n\nUSER QUESTION: {question}\nGQL-CORE QUERY:"
    attempts: list[dict[str, Any]] = []

    def attempt(raw: str) -> dict[str, Any]:
        rec: dict[str, Any] = {"query": None, "results": None, "error": None}
        try:
            rec["query"] = _finish(raw, graph, correct_directions)
            rec["results"] = run_query(rec["query"], graph)
        except Exception as exc:  # noqa: BLE001 - reported back to the model
            rec["error"] = f"{type(exc).__name__}: {exc}"
            rec["query"] = rec["query"] or clean_generated_gql(raw)
        rec["feedback"] = execution_feedback(rec["results"], rec["error"])
        attempts.append(rec)
        return rec

    best = attempt(_generate(full_prompt, system_prompt, question, client=client, model=model))
    for _ in range(max_retries):
        if best["feedback"] is None:
            break
        retry_prompt = feedback_prompt(full_prompt + " ", best["query"], best["feedback"])
        retry_user = feedback_prompt(f"USER QUESTION: {question}\nGQL-CORE QUERY: ", best["query"], best["feedback"])
        rec = attempt(_generate(retry_prompt, system_prompt, retry_user, client=client, model=model))
        if keep_revision(best["results"], best["error"], rec["results"], rec["error"]):
            best = rec

    if best["error"] is not None and not explain:
        raise ValueError(f"Generated query failed: {best['query']!r} ({best['error']})")
    results = best["results"] or []
    if explain:
        return {
            "question": question,
            "query": best["query"],
            "count": len(results),
            "results": results,
            "attempts": attempts,
        }
    return results
