"""Integration tests: the application against the installed gql-core package.

Expected answers come from a plain-Python breadth-first search over the catalog file, which does
not use gql-core, plus a few hand-checked cases.
"""

from __future__ import annotations

import json
import threading
import urllib.request
from collections import deque
from importlib.metadata import distribution
from pathlib import Path

import pytest

import gql_core
from service_impact import CatalogError, ImpactAnalyzer, UnknownComponent, load_catalog
from service_impact.catalog import RELATIONS, default_catalog_path, validate_catalog
from service_impact.cli import main


@pytest.fixture(scope="module")
def an() -> ImpactAnalyzer:
    return ImpactAnalyzer.from_catalog()


@pytest.fixture(scope="module")
def catalog() -> dict:
    return load_catalog()


def oracle_impact(cat: dict, failed: str) -> dict[str, int]:
    """Component id -> length of its shortest dependency path to ``failed``."""
    reverse: dict[str, list[str]] = {}
    for c in cat["components"]:
        for field in RELATIONS:
            for t in c.get(field, []):
                reverse.setdefault(t, []).append(c["id"])
    dist, queue = {failed: 0}, deque([failed])
    while queue:
        x = queue.popleft()
        for y in reverse.get(x, []):
            if y not in dist:
                dist[y] = dist[x] + 1
                queue.append(y)
    dist.pop(failed)
    return dist


# ── the package under test is the published one ─────────────────────────────────────────


def test_gql_core_is_the_installed_release():
    assert gql_core.__version__ == "0.2.0a4"
    dist = distribution("gql-core")
    assert dist.version == "0.2.0a4"
    installed = Path(str(dist.locate_file("gql_core/__init__.py"))).resolve()
    assert Path(gql_core.__file__).resolve() == installed
    assert "site-packages" in installed.parts, f"gql_core imported from {installed}, not an installed package"


# ── catalog and graph construction ──────────────────────────────────────────────────────


def test_catalog_validation_reports_every_problem(catalog):
    bad = json.loads(json.dumps(catalog))
    bad["components"][0]["owner"] = "team-nobody"
    bad["components"][1]["calls"] = ["does-not-exist"]
    bad["components"].append({"id": "Bad Id", "kind": "mainframe"})
    with pytest.raises(CatalogError) as err:
        validate_catalog(bad)
    text = "\n".join(err.value.problems)
    assert "team-nobody" in text and "does-not-exist" in text and "mainframe" in text and "'Bad Id'" in text


def test_graph_has_every_component_and_relationship(an, catalog):
    n_components = len(catalog["components"])
    rows = gql_core.run("MATCH (c) WHERE c.kind IS NOT NULL RETURN count(c) AS n", an.graph)
    assert rows == [{"n": n_components}]
    stored = sum(len(c.get(f, [])) for c in catalog["components"] for f in RELATIONS)
    rows = gql_core.run("MATCH ()-[r:CALLS|READS_FROM|WRITES_TO|DEPENDS_ON|DEPLOYED_ON]->() RETURN count(r) AS n",
                        an.graph)
    assert rows == [{"n": stored}]


# ── the questions ───────────────────────────────────────────────────────────────────────


def test_dependents_of_a_database(an):
    rows = an.dependents_of_database("orders-db")
    assert [(r["id"], sorted(r["access"])) for r in rows] == [
        ("legacy-reporting", ["READS_FROM"]),
        ("orders-svc", ["READS_FROM", "WRITES_TO"]),
        ("payments-svc", ["READS_FROM"]),
    ]


@pytest.mark.parametrize("failed", [c for c in json.loads(default_catalog_path().read_text())["components"]])
def test_impact_matches_an_independent_search(an, catalog, failed):
    expected = oracle_impact(catalog, failed["id"])
    got = {a.id: a.hops for a in an.impact(failed["id"])}
    assert got == expected


def test_impact_of_orders_db_hand_checked(an):
    affected = {a.id: a for a in an.impact("orders-db")}
    assert set(affected) == {"orders-svc", "payments-svc", "legacy-reporting", "public-gateway",
                             "notification-svc", "web-storefront", "mobile-bff", "fulfillment-worker"}
    assert "analytics-etl" not in affected  # orders-svc writes to the queue; nothing reads back from it
    assert affected["orders-svc"].dependency == "direct" and affected["orders-svc"].derived_by == [
        "reads_from_implies_relies_on"]
    gw = affected["public-gateway"]
    assert gw.dependency == "indirect" and gw.hops == 2
    assert "transitive_RELIES_ON" in gw.derived_by
    assert affected["orders-svc"].team == "Checkout" and affected["orders-svc"].team_lead == "Omar Haddad"
    assert affected["legacy-reporting"].team is None


def test_evidence_paths_are_stored_relationships_ending_at_the_failed_component(an, catalog):
    stored = {(c["id"], rel, t) for c in catalog["components"] for f, rel in RELATIONS.items() for t in c.get(f, [])}
    for a in an.impact("sessions-cache"):
        path = a.evidence_path
        assert path[0].src == a.id and path[-1].dst == "sessions-cache" and len(path) == a.hops
        assert all(path[i].dst == path[i + 1].src for i in range(len(path) - 1))
        assert all((s.src, s.rel, s.dst) in stored for s in path)
        # The inference's own derivation is also a chain of stored facts from a.id to the failure.
        d = a.derivation
        assert d[0].src == a.id and d[-1].dst == "sessions-cache"
        assert all((s.src, s.rel, s.dst) in stored for s in d)


def test_inferred_edges_are_marked_and_stored_ones_are_not(an):
    rows = gql_core.run("MATCH ()-[r:RELIES_ON]->() RETURN count(r) AS n, collect(DISTINCT r.is_inferred) AS flags",
                        an.graph)
    assert rows[0]["n"] > 0 and rows[0]["flags"] == [True]
    rows = gql_core.run("MATCH ()-[r:CALLS]->() WHERE r.is_inferred = true RETURN count(r) AS n", an.graph)
    assert rows == [{"n": 0}]


def test_a_dependency_cycle_does_not_report_the_failed_component(an):
    # orders-svc calls notification-svc, and notification-svc calls orders-svc.
    ids = {a.id for a in an.impact("orders-svc")}
    assert "orders-svc" not in ids and "notification-svc" in ids


def test_a_cluster_failure_reaches_everything_deployed_on_it(an, catalog):
    on_us = {c["id"] for c in catalog["components"] if "k8s-prod-us" in c.get("deployed_on", [])}
    ids = {a.id for a in an.impact("k8s-prod-us")}
    assert on_us <= ids and "web-storefront" in ids  # via recommendation-svc


def test_teams_to_notify_and_unowned(an):
    teams = an.teams_to_notify("orders-db")
    assert teams[0]["team"] == "Growth" and teams[0]["components"] == 3
    assert sum(t["components"] for t in teams) == 7  # 8 affected, one has no owner
    assert an.unowned_affected("orders-db") == ["legacy-reporting"]


def test_typed_plans(an):
    # public-gateway calls five components but is an API, not a Service, so the Scan excludes it.
    assert an.fan_out_hotspots(3) == [{"id": "orders-svc", "name": "Orders service"}]
    assert [r["id"] for r in an.fan_out_hotspots(2)] == ["cart-svc", "fulfillment-worker", "orders-svc",
                                                         "web-storefront"]
    owners = an.tier_owners(1)
    assert {"service": "orders-svc", "team": "Checkout"} in owners
    assert all(set(r) == {"service", "team"} for r in owners)


def test_unknown_and_unsafe_ids_are_rejected(an):
    for bad in ["nope", "orders-db' OR 1=1 //", "team-checkout"]:
        with pytest.raises(UnknownComponent):
            an.impact(bad)
    with pytest.raises(UnknownComponent):
        an.dependents_of_database("orders-svc")  # a service, not a database


# ── interfaces ──────────────────────────────────────────────────────────────────────────


def test_http_api(an):
    from service_impact.api import make_server
    server = make_server(an, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        body = json.loads(urllib.request.urlopen(f"{base}/impact/catalog-db").read())
        assert body["failed"] == "catalog-db" and {"catalog-svc", "search-svc", "inventory-svc"} <= {
            a["id"] for a in body["affected"]}
        health = json.loads(urllib.request.urlopen(f"{base}/health").read())
        assert health == {"status": "ok", "gql_core": "0.2.0a4"}
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f"{base}/impact/nope")
        assert err.value.code == 404
    finally:
        server.shutdown()


def test_cli(capsys):
    assert main(["impact", "orders-db"]) == 0
    out = capsys.readouterr().out
    assert "8 components are affected" in out and "NO OWNER" in out and "Teams to notify" in out
    assert main(["impact", "nope"]) == 2
    capsys.readouterr()
    assert main(["plan", "--tier", "1"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["_type"] == "Sort" and '"_type": "Scan"' in json.dumps(plan)
    # The JSON plan round-trips and runs to the same rows: what an agent would send.
    an = ImpactAnalyzer.from_catalog()
    assert gql_core.execute_plan(plan, an.graph)["rows"] == an.tier_owners(1)
