"""NL → GQL-Core translator using a local Ollama model.

Sends a schema-grounded system prompt + the natural-language question to
Ollama's REST API and returns the generated GQL-Core query string.

Usage (standalone):
    python -m benchmark.nl_to_gql "How many Test matches are in the dataset?"

Configuration:
    OLLAMA_URL   default: http://localhost:11434
    OLLAMA_MODEL default: llama3
    Override via env vars or pass explicitly to translate().
"""

from __future__ import annotations

import json
import os
import re
import sys
import textwrap
import urllib.error
import urllib.request
from pathlib import Path

# ── Schema prompt ────────────────────────────────────────────────────────────
#
# This is what the model sees.  It must cover:
#   • Every node label and its queryable properties
#   • Every edge label, direction, and its properties
#   • The GQL-Core grammar subset (what IS and is NOT supported)
#   • Worked examples for each query class

_SCHEMA_PROMPT = textwrap.dedent("""\
You are a GQL-Core query generator for a cricket knowledge graph.
Your job: translate a natural-language cricket question into a single valid
GQL-Core query.  Output ONLY the query — no explanation, no markdown fences.

════════════════════════════════════════════════════════
GRAPH SCHEMA
════════════════════════════════════════════════════════

NODE LABELS AND PROPERTIES
  Match      : id, format ("Test"|"ODI"|"T20"|"IT20"), gender, season,
               date, city, outcome_winner (full name e.g. "Pakistan"), outcome_method, venue_id
               ← Match has NO runs/wickets/batting/bowling properties; those live on edges
  Player     : id, name, country  (ISO codes: "PAK","AUS","IND","ENG","SRI","BAN","NZ","WI","ZIM","AFG")
               ← Player has NO runs/wickets properties; those live on edges
  Venue      : id, name, city
  Team       : id, name, country_code, type
  Tournament : id, name, match_type, season
  Innings    : id, match_id, innings_idx
  Delivery   : id, over, ball, runs_total, runs_batter, runs_extras,
               batter_id, bowler_id, wicket_kind, player_out

EDGE LABELS, DIRECTION, AND PROPERTIES
  (Player)  -[b:BATTED_IN]->   (Match)      props: b.runs, b.balls_faced, b.fours, b.sixes
  (Player)  -[bw:BOWLED_IN]->  (Match)      props: bw.overs, bw.runs_conceded, bw.wickets, bw.maidens
  (Player)  -[:CAPTAINED]->    (Match)      props: (none)
  (Player)  -[:PLAYED_FOR]->   (Team)       props: first_match_date, last_match_date
  (Match)   -[:PLAYED_AT]->    (Venue)      props: (none)
  (Match)   -[:PART_OF_TOURNAMENT]-> (Tournament)  props: (none)
  (Player)  -[tw:TEAMMATES_WITH]- (Player)  props: tw.match_count  (UNDIRECTED)
  (Delivery)-[:IN_INNINGS]->   (Innings)    props: (none)
  (Delivery)-[:NEXT_DELIVERY]-> (Delivery)  props: (none)

KEY FACTS:
  • outcome_winner is a STRING property on Match (e.g. "Pakistan"), NOT an edge.
    Use: WHERE m.outcome_winner = "Pakistan"   NOT: -[:OUTCOME_WINNER]->
  • TEAMMATES_WITH edge stores tw.match_count. Use it directly; do NOT use COUNT(tw).
  • To reach a city, traverse -[:PLAYED_AT]->(v:Venue) then use v.city.

NOTE: Player.country stores ISO codes, NOT full country names.
  "Pakistani players" → WHERE p.country = "PAK"
  "Australian players" → WHERE p.country = "AUS"
  "Indian players" → WHERE p.country = "IND"
  "English players" → WHERE p.country = "ENG"
  outcome_winner stores full team name: "Pakistan", "Australia", etc.

════════════════════════════════════════════════════════
GQL-CORE GRAMMAR — WHAT IS SUPPORTED
════════════════════════════════════════════════════════

MATCH clause:
  MATCH (var:Label)                          — node scan
  MATCH (a:Label)-[:EDGE]->(b:Label)         — directed edge
  MATCH (a:Label)<-[:EDGE]-(b:Label)         — reverse edge
  MATCH (a:Label)-[:EDGE]-(b:Label)          — undirected edge (TEAMMATES_WITH)
  MATCH (a)-[e:EDGE]->(b)                    — bind edge variable e
  MATCH p1, p2                               — multiple comma-separated patterns
  Inline node filter: (a:Label {prop: "val"})

RPQ quantifiers on edges:
  -[:EDGE*]->        unbounded Kleene (lo=1, hi=∞)
  -[:EDGE+]->        one-or-more  (same as *)
  -[:EDGE*N]->       exactly N hops
  -[:EDGE*M..N]->    range M to N hops
  -[:EDGE*0..N]->    zero-or-more (includes start node)

WHERE clause:
  Comparisons: var.prop OP value   (OP is =, !=, <, <=, >, >=)
  value types: "string", 42, 3.14, true, false, null
  Boolean:     AND, OR, NOT

RETURN clause:
  var.prop AS alias
  COUNT(var) AS alias
  SUM(e.prop) AS alias
  AVG(e.prop) AS alias
  MIN(e.prop) AS alias
  MAX(e.prop) AS alias
  GROUP BY is implicit: non-aggregate refs become group keys
  ORDER BY alias DESC / ASC   (use the alias from RETURN, not var.prop)
  LIMIT N

════════════════════════════════════════════════════════
⚠ HARD RULES — VIOLATING THESE CAUSES A PARSE ERROR ⚠
════════════════════════════════════════════════════════

RULE 1 — NO DISTINCT. Never write DISTINCT anywhere.
  ✗ WRONG:  RETURN COUNT(DISTINCT p) AS cnt
  ✓ RIGHT:  RETURN COUNT(p) AS cnt

RULE 2 — NO IN operator. Use OR for multiple values.
  ✗ WRONG:  WHERE m.format IN ("Test", "T20")
  ✓ RIGHT:  WHERE m.format = "Test" OR m.format = "T20"

RULE 3 — NO arithmetic inside aggregates. Use separate SUM calls.
  ✗ WRONG:  RETURN SUM(b.fours + b.sixes) AS boundaries
  ✓ RIGHT:  RETURN SUM(b.fours) AS total_fours, SUM(b.sixes) AS total_sixes

RULE 4 — ONE MATCH clause only. Use commas for multiple patterns.
  ✗ WRONG:  MATCH (p:Player)-[:BATTED_IN]->(m:Match)
            MATCH (p)-[:BOWLED_IN]->(m)
  ✓ RIGHT:  MATCH (p:Player)-[:BATTED_IN]->(m:Match), (p)-[:BOWLED_IN]->(m)

RULE 5 — NO IS NULL / IS NOT NULL. Cannot test for missing values.

RULE 6 — NO WITH clause. Cannot chain sub-queries or filter aggregates.

RULE 7 — NO UNION / UNION ALL. Cannot combine result sets.

RULE 8 — Comparisons must be ref OP literal, never ref OP ref.
  ✗ WRONG:  WHERE b.runs > b.balls_faced
  ✓ RIGHT:  WHERE b.runs > 50

RULE 9 — Inline node filters use ":" not "=".
  ✗ WRONG:  MATCH (p:Player {country = "PAK"})
  ✓ RIGHT:  MATCH (p:Player) WHERE p.country = "PAK"
  ✓ ALSO:   MATCH (p:Player {id: "some_id"})   — colon for inline filters
  Prefer WHERE for all property filters; use inline {prop: val} only for id lookups.

RULE 10 — Edge properties belong to the EDGE variable, NEVER to the node variable.
  Bind the edge with a variable name and use that variable to access its properties.
  ✗ WRONG:  MATCH (p:Player)-[:BATTED_IN]->(m:Match) RETURN SUM(m.runs)
  ✓ RIGHT:  MATCH (p:Player)-[b:BATTED_IN]->(m:Match) RETURN SUM(b.runs)
  ✗ WRONG:  MATCH (p:Player)-[:BOWLED_IN]->(m:Match) RETURN SUM(m.runs_conceded)
  ✓ RIGHT:  MATCH (p:Player)-[bw:BOWLED_IN]->(m:Match) RETURN SUM(bw.runs_conceded)
  Properties on BATTED_IN edge: b.runs  b.balls_faced  b.fours  b.sixes
  Properties on BOWLED_IN edge: bw.overs  bw.runs_conceded  bw.wickets  bw.maidens
  Properties on TEAMMATES_WITH edge: tw.match_count

RULE 11 — Use SUM to total a numeric property; use COUNT to count matched rows.
  ✗ WRONG:  RETURN COUNT(b.wickets) AS total_wickets   ← counts non-null rows, not sum
  ✓ RIGHT:  RETURN SUM(b.wickets) AS total_wickets     ← adds up the wicket values
  ✗ WRONG:  RETURN COUNT(b.maidens) AS total_maidens
  ✓ RIGHT:  RETURN SUM(b.maidens) AS total_maidens
  Rule of thumb: if the question uses "total / sum / how many [runs/wickets/sixes/...]", use SUM.

RULE 12 — Use MATCH edge traversal to reach related nodes; never access an edge as a property.
  ✗ WRONG:  WHERE m.played_at = "Karachi"      (played_at is an edge, not a node property)
  ✓ RIGHT:  MATCH (...)-[:PLAYED_AT]->(v:Venue) WHERE v.city = "Karachi"
  ✗ WRONG:  WHERE m.venue = "Karachi"
  ✓ RIGHT:  MATCH (m:Match)-[:PLAYED_AT]->(v:Venue) WHERE v.city = "Karachi"

════════════════════════════════════════════════════════
WORKED EXAMPLES
════════════════════════════════════════════════════════

Q: How many Test matches are in the dataset?
A: MATCH (m:Match) WHERE m.format = "Test" RETURN COUNT(m) AS test_matches

Q: How many unique players are in the dataset?
A: MATCH (p:Player) RETURN COUNT(p) AS total_players

Q: How many Pakistani players are there?
A: MATCH (p:Player) WHERE p.country = "PAK" RETURN COUNT(p) AS pak_players

Q: Who are the top 10 run scorers?
A: MATCH (p:Player)-[b:BATTED_IN]->(m:Match)
   RETURN p.name AS name, SUM(b.runs) AS total_runs
   ORDER BY total_runs DESC LIMIT 10

Q: Which players batted at Karachi and in how many matches?
A: MATCH (p:Player)-[:BATTED_IN]->(m:Match)-[:PLAYED_AT]->(v:Venue)
   WHERE v.city = "Karachi"
   RETURN p.name AS name, COUNT(m) AS matches_at_venue
   ORDER BY matches_at_venue DESC

Q: Which players both batted and bowled in the same match?
A: MATCH (p:Player)-[:BATTED_IN]->(m:Match), (p)-[:BOWLED_IN]->(m)
   RETURN p.name AS name, COUNT(m) AS allrounder_matches
   ORDER BY allrounder_matches DESC

Q: Who are Babar Azam's teammates?
A: MATCH (p:Player)-[tw:TEAMMATES_WITH]-(t:Player)
   WHERE p.name = "Babar Azam"
   RETURN t.name AS teammate, tw.match_count AS shared_matches
   ORDER BY shared_matches DESC

Q: How many deliveries are reachable within 5 hops from delivery "1000001:1:0.1"?
A: MATCH (d:Delivery {id: "1000001:1:0.1"})-[:NEXT_DELIVERY*1..5]->(e:Delivery)
   RETURN COUNT(e) AS reachable_count

Q: How many wicketless bowling innings are there per player?
A: MATCH (p:Player)-[b:BOWLED_IN]->(m:Match) WHERE b.wickets = 0
   RETURN p.name AS name, COUNT(m) AS wicketless_innings
   ORDER BY wicketless_innings DESC LIMIT 10

Q: Which players both batted and bowled at Karachi?
A: MATCH (p:Player)-[b:BATTED_IN]->(m:Match),
         (p)-[bw:BOWLED_IN]->(m),
         (m)-[:PLAYED_AT]->(v:Venue)
   WHERE v.city = "Karachi"
   RETURN p.name AS name, SUM(b.runs) AS runs, SUM(bw.wickets) AS wickets
   ORDER BY runs DESC

Q: How many Test or ODI matches are in the dataset?
A: MATCH (m:Match) WHERE m.format = "Test" OR m.format = "ODI"
   RETURN COUNT(m) AS test_or_odi_matches

Q: Who scored the most fours and sixes combined?
A: MATCH (p:Player)-[b:BATTED_IN]->(m:Match)
   RETURN p.name AS name, SUM(b.fours) AS total_fours, SUM(b.sixes) AS total_sixes
   ORDER BY total_fours DESC LIMIT 10

Q: How many runs did each team captain score in matches they captained? Top 10.
A: MATCH (p:Player)-[:CAPTAINED]->(m:Match), (p)-[b:BATTED_IN]->(m)
   RETURN p.name AS name, SUM(b.runs) AS captain_runs
   ORDER BY captain_runs DESC LIMIT 10

Q: How many wickets did each team captain take in matches they captained? Top 10.
A: MATCH (p:Player)-[:CAPTAINED]->(m:Match), (p)-[bw:BOWLED_IN]->(m)
   RETURN p.name AS name, SUM(bw.wickets) AS captain_wickets
   ORDER BY captain_wickets DESC LIMIT 10

Q: How many matches did Pakistan NOT win?
A: MATCH (m:Match) WHERE m.outcome_winner != "Pakistan"
   RETURN COUNT(m) AS not_won

Q: How many matches of each format are there, ordered by count?
A: MATCH (m:Match)
   RETURN m.format AS format, COUNT(m) AS match_count
   ORDER BY match_count DESC

Q: How many deliveries within 5 hops from delivery "64939:2:35.2" had batter runs > 0?
A: MATCH (d:Delivery {id: "64939:2:35.2"})-[:NEXT_DELIVERY*1..5]->(e:Delivery)
   WHERE e.runs_batter > 0
   RETURN COUNT(e) AS scoring_deliveries

Q: What are the ids of all deliveries reachable from delivery "64939:2:35.2"?
A: MATCH (d:Delivery {id: "64939:2:35.2"})-[:NEXT_DELIVERY*]->(e:Delivery)
   RETURN e.id AS delivery_id ORDER BY delivery_id ASC

Q: List Babar Azam's teammates and how many matches they shared.
A: MATCH (p:Player)-[tw:TEAMMATES_WITH]-(t:Player)
   WHERE p.name = "Babar Azam"
   RETURN t.name AS teammate, tw.match_count AS shared_matches
   ORDER BY shared_matches DESC LIMIT 10

Q: How many wickets did Pakistani bowlers take at each tournament? Order by wickets descending.
A: MATCH (p:Player)-[bw:BOWLED_IN]->(m:Match)-[:PART_OF_TOURNAMENT]->(t:Tournament)
   WHERE p.country = "PAK"
   RETURN t.name AS tournament, SUM(bw.wickets) AS pak_wickets
   ORDER BY pak_wickets DESC

Q: How many runs did each player score at Lahore?
A: MATCH (p:Player)-[b:BATTED_IN]->(m:Match)-[:PLAYED_AT]->(v:Venue)
   WHERE v.city = "Lahore"
   RETURN p.name AS name, SUM(b.runs) AS lahore_runs
   ORDER BY lahore_runs DESC

════════════════════════════════════════════════════════
NOW TRANSLATE THE FOLLOWING QUESTION
════════════════════════════════════════════════════════
""")


# ── Ollama client ────────────────────────────────────────────────────────────

def translate(
    question: str,
    *,
    model: str | None = None,
    ollama_url: str | None = None,
    timeout: int = 120,
) -> str:
    """Call Ollama to translate a natural-language question into GQL-Core.

    Returns the raw GQL string (may need light post-processing to strip
    accidental markdown fences — use extract_gql() for that).

    Raises:
        ConnectionError  if Ollama is not reachable.
        RuntimeError     if the model returns an error response.
    """
    url = (ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
    mdl = model or os.environ.get("OLLAMA_MODEL", "llama3")

    prompt = _SCHEMA_PROMPT + question + "\nA:"

    payload = json.dumps({
        "model": mdl,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,   # deterministic — we want exact GQL, not creative prose
            "num_predict": 256,
        },
    }).encode()

    req = urllib.request.Request(
        f"{url}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read())
    except urllib.error.URLError as exc:
        raise ConnectionError(
            f"Cannot reach Ollama at {url}. Is it running? ({exc})"
        ) from exc

    if "error" in body:
        raise RuntimeError(f"Ollama error: {body['error']}")

    return body.get("response", "").strip()


def _fix_generated_gql(gql: str) -> str:
    """Deterministic repairs for common small-model grammar mistakes.

    These patterns are unambiguous and safe to fix without understanding context.
    """
    # 1. Inline node filter uses = instead of : e.g. {country = "PAK"} → {country: "PAK"}
    def _fix_prop_block(m: re.Match) -> str:
        content = re.sub(r'(\w+)\s*=\s*', r'\1: ', m.group(1))
        return "{" + content + "}"
    gql = re.sub(r"\{([^}]+)\}", _fix_prop_block, gql)

    # 2. COUNT(DISTINCT var) or COUNT(DISTINCT var.prop) → COUNT(var) / COUNT(var.prop)
    gql = re.sub(
        r"COUNT\s*\(\s*DISTINCT\s+(\w+(?:\.\w+)?)\s*\)",
        r"COUNT(\1)",
        gql,
        flags=re.IGNORECASE,
    )

    # 3. var IN ("a", "b") → var = "a" OR var = "b"  (only literal lists, not subqueries)
    def _fix_in_list(m: re.Match) -> str:
        ref = m.group(1)
        values = re.findall(r'"[^"]*"|\'[^\']*\'|\d+(?:\.\d+)?', m.group(2))
        if not values:
            return m.group(0)
        return " OR ".join(f"{ref} = {v}" for v in values)
    gql = re.sub(
        r"(\w+(?:\.\w+)?)\s+IN\s*\(([^)]+)\)",
        _fix_in_list,
        gql,
        flags=re.IGNORECASE,
    )

    # 4. Remove IS NULL / IS NOT NULL conditions (not supported by GQL-Core grammar)
    gql = re.sub(
        r"\s+AND\s+\w+(?:\.\w+)?\s+IS\s+(?:NOT\s+)?NULL\b",
        "",
        gql,
        flags=re.IGNORECASE,
    )
    gql = re.sub(
        r"\s+OR\s+\w+(?:\.\w+)?\s+IS\s+(?:NOT\s+)?NULL\b",
        "",
        gql,
        flags=re.IGNORECASE,
    )
    gql = re.sub(
        r"\bWHERE\s+\w+(?:\.\w+)?\s+IS\s+(?:NOT\s+)?NULL\b",
        "",
        gql,
        flags=re.IGNORECASE,
    )

    # 5. TEAMMATES_WITH:  (a) bind edge variable if absent
    #                     (b) make undirected (TEAMMATES_WITH has no direction)
    #                     (c) replace COUNT(edge_var) with edge_var.match_count when
    #                         the alias suggests "shared matches" (e.g. shared_matches)
    if "TEAMMATES_WITH" in gql.upper():
        if not re.search(r"\[\w+:TEAMMATES_WITH\]", gql, flags=re.IGNORECASE):
            gql = re.sub(r"\[:TEAMMATES_WITH\]", "[tw:TEAMMATES_WITH]", gql, flags=re.IGNORECASE)
        # Directed → undirected
        gql = re.sub(r"-(\[\w+:TEAMMATES_WITH\])->", r"-\1-", gql, flags=re.IGNORECASE)
        tw_m = re.search(r"\[(\w+):TEAMMATES_WITH\]", gql, flags=re.IGNORECASE)
        if tw_m:
            ev = tw_m.group(1)
            # COUNT(ev) AS shared_*/match_* aliases → ev.match_count
            gql = re.sub(
                rf"COUNT\s*\(\s*\w+(?:\.\w+)?\s*\)\s*(AS\s+\w*(?:shared|match)\w*)",
                rf"{ev}.match_count \1",
                gql,
                flags=re.IGNORECASE,
            )

    # 6. Auto-bind common edge variables when referenced in aggregates but not bound.
    #    e.g. SUM(b.runs) used but MATCH has [:BATTED_IN] without a variable → add [b:BATTED_IN]
    for ev, label in (("b", "BATTED_IN"), ("bw", "BOWLED_IN")):
        if re.search(rf"\b{ev}\.\w+", gql) and not re.search(rf"\[{ev}:{label}\]", gql, flags=re.IGNORECASE):
            gql = re.sub(rf"\[:{label}\]", f"[{ev}:{label}]", gql, flags=re.IGNORECASE)

    return gql.strip()


def extract_gql(raw: str) -> str:
    """Strip markdown fences, apply deterministic grammar repairs, and strip whitespace."""
    fenced = re.sub(r"```[a-zA-Z]*\n?", "", raw)
    fenced = fenced.replace("```", "")
    return _fix_generated_gql(fenced.strip())


def translate_clean(question: str, *, max_retries: int = 2, **kwargs) -> str:
    """translate() + extract_gql() with up to max_retries parse-error corrections."""
    from query.parser import parse as _parse

    gql = extract_gql(translate(question, **kwargs))
    for attempt in range(max_retries):
        try:
            _parse(gql)
            return gql
        except Exception as exc:
            # Include the full schema prompt so the model has all constraints.
            correction_suffix = (
                f"The GQL-Core query you generated had a parse error:\n"
                f"  {exc}\n\n"
                f"Re-read ALL the hard rules above, then re-translate this question "
                f"producing a syntactically valid GQL-Core query:\n"
                f"{question}"
            )
            gql = extract_gql(translate(correction_suffix, **kwargs))
    return gql


# ── Available models helper ──────────────────────────────────────────────────

def list_models(ollama_url: str | None = None) -> list[str]:
    """Return model names available in the local Ollama instance."""
    url = (ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")).rstrip("/")
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=10) as resp:
            body = json.loads(resp.read())
        return [m["name"] for m in body.get("models", [])]
    except Exception:
        return []


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m benchmark.nl_to_gql \"<natural language question>\"")
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    print(f"Question : {question}")
    print(f"Model    : {os.environ.get('OLLAMA_MODEL', 'llama3')}")
    print()

    try:
        gql = translate_clean(question)
        print("GQL-Core :")
        print(gql)
    except ConnectionError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
