"""NL building blocks (gql_core.nl) and ask()'s repair + feedback retry."""

from gql_core import Edge, Node, PropertyGraph, ask
from gql_core.ai import format_schema_prompt
from gql_core.nl import execution_feedback, feedback_prompt, repair_query, value_hints


def _graph() -> PropertyGraph:
    g = PropertyGraph()
    for i, name in enumerate(["center", "guard"]):
        g.add_node(Node(f"pos{i}", "Position", {"name": name}))
    for i in range(40):  # 40 distinct player names: too many to list as hints
        g.add_node(Node(f"p{i}", "Player", {"name": f"Player {i}"}))
    g.add_node(Node("t1", "Team", {"name": "Kings"}))
    g.add_edge(Edge("e1", "playsPosition", "p1", "pos0"))
    g.add_edge(Edge("e2", "playsPosition", "p2", "pos0"))
    g.add_edge(Edge("e3", "playsFor", "p1", "t1"))
    g.add_edge(Edge("e4", "playsFor", "p2", "t1"))
    return g


def test_value_hints_list_only_low_cardinality_strings():
    hints = value_hints(_graph())
    assert "Position.name: 'center', 'guard'" in hints
    assert "Team.name: 'Kings'" in hints
    assert "Player.name" not in hints
    assert "STORED VALUES" in format_schema_prompt(_graph())


def test_schema_prompt_shows_every_direction_and_all_labels():
    g = PropertyGraph()
    g.add_node(Node("m", "Movie", {"name": "Hold Back the Dawn"}))
    g.add_node(Node("y", "Movie", {"name": "1941"}, labels=("Movie", "Year")))
    g.add_edge(Edge("e", "release_year", "m", "y"))
    assert "(:Movie)-[:release_year]->(:Year)" in format_schema_prompt(g)


def test_repair_query_combines_direction_and_value_fixes():
    r = repair_query("MATCH (p:Position {name: 'Center'})-[:playsPosition]->(x:Player) RETURN x.name", _graph())
    assert r.query == "MATCH (p:Position {name: 'center'})<-[:playsPosition]-(x:Player) RETURN x.name"
    assert len(r.changes) == 2


def test_execution_feedback():
    assert execution_feedback(None, "SyntaxError: bad") == "Running it failed with this error: SyntaxError: bad"
    assert execution_feedback([]) == "It ran but returned no rows."
    assert "1 of which repeat" in execution_feedback([{"n": "Kings"}, {"n": "Kings"}])
    assert execution_feedback([{"n": "Kings"}, {"n": "Queens"}]) is None
    p = feedback_prompt("PROMPT ", "MATCH (n) RETURN n", "It ran but returned no rows.")
    assert p.startswith("PROMPT MATCH (n) RETURN n") and "returned no rows" in p


def test_ask_retries_once_with_feedback_on_duplicates():
    prompts = []

    def llm(prompt: str) -> str:
        prompts.append(prompt)
        if len(prompts) == 1:
            return "MATCH (p:Player)-[:playsFor]->(t:Team) RETURN t.name AS team"
        return "MATCH (p:Player)-[:playsFor]->(t:Team) RETURN DISTINCT t.name AS team"

    out = ask(_graph(), "Which teams have players?", client=llm, explain=True)
    assert out["results"] == [{"team": "Kings"}]
    assert len(out["attempts"]) == 2 and "repeat an earlier row" in prompts[1]


def test_ask_does_not_retry_a_good_answer():
    calls = []
    llm = lambda p: calls.append(p) or "MATCH (t:Team) RETURN t.name AS team"  # noqa: E731
    assert ask(_graph(), "Teams?", client=llm) == [{"team": "Kings"}]
    assert len(calls) == 1


def test_ask_keeps_a_working_query_if_the_retry_breaks():
    answers = iter(["MATCH (t:Team {name: 'Nobody'}) RETURN t.name AS team", "MATCH (t:Team RETURN t"])
    out = ask(_graph(), "Teams?", client=lambda p: next(answers), explain=True)
    assert out["query"] == "MATCH (t:Team {name: 'Nobody'}) RETURN t.name AS team"
    assert out["results"] == [] and out["attempts"][1]["error"]


def test_ask_retry_can_be_turned_off():
    calls = []
    llm = lambda p: calls.append(p) or "MATCH (t:Team {name: 'Nobody'}) RETURN t.name AS team"  # noqa: E731
    assert ask(_graph(), "Teams?", client=llm, max_retries=0) == []
    assert len(calls) == 1


def test_keep_revision_rules():
    from gql_core.nl import keep_revision
    rows = [{"n": 1}]
    assert keep_revision(rows, None, [{"n": 2}], None)          # ran -> ran: take the revision
    assert not keep_revision(rows, None, None, "boom")          # never trade a working query for an error
    assert keep_revision(None, "boom", None, "bang")            # both fail: take the latest
    assert not keep_revision(rows, None, [], None)              # never trade rows for no rows
    assert keep_revision([], None, [], None)                    # empty -> empty: take the revision
    assert keep_revision(None, "boom", [], None)                # error -> runs: take the revision
