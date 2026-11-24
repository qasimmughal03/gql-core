"""Build the baseline systems from the generator's records: SQLite (in memory) and NetworkX.

SQLite gets primary keys and foreign-key indexes (``knows.src``, ``knows.dst``,
``works_at.person``, ``works_at.company``, ``company.parent``) and nothing on filtered
properties, matching GQL-Core, which has a label index but no property index.
NetworkX gets one ``DiGraph`` per relationship type, since it has no typed adjacency.
"""

from __future__ import annotations

import sqlite3
from typing import Any


def build_sqlite(data: dict[str, Any]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE person (id TEXT PRIMARY KEY, name TEXT, age INTEGER, score REAL, active INTEGER, city TEXT);
        CREATE TABLE company (id TEXT PRIMARY KEY, name TEXT, industry TEXT, size INTEGER, city TEXT, parent TEXT);
        CREATE TABLE city (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE knows (src TEXT, dst TEXT);
        CREATE TABLE works_at (person TEXT, company TEXT, since INTEGER);
    """)
    lives = dict(data["lives_in"])
    located = dict(data["located_in"])
    parent = dict(data["subsidiary_of"])
    cur.executemany("INSERT INTO person VALUES (?,?,?,?,?,?)",
                    [(p["id"], p["name"], p["age"], p["score"], int(p["active"]), lives[p["id"]]) for p in data["persons"]])
    cur.executemany("INSERT INTO company VALUES (?,?,?,?,?,?)",
                    [(c["id"], c["name"], c["industry"], c["size"], located[c["id"]], parent.get(c["id"]))
                     for c in data["companies"]])
    cur.executemany("INSERT INTO city VALUES (?,?)", [(c["id"], c["name"]) for c in data["cities"]])
    cur.executemany("INSERT INTO knows VALUES (?,?)", data["knows"])
    cur.executemany("INSERT INTO works_at VALUES (?,?,?)", data["works_at"])
    cur.executescript("""
        CREATE INDEX knows_src ON knows(src);
        CREATE INDEX knows_dst ON knows(dst);
        CREATE INDEX works_person ON works_at(person);
        CREATE INDEX works_company ON works_at(company);
        CREATE INDEX company_parent ON company(parent);
        CREATE INDEX person_city ON person(city);
        ANALYZE;
    """)
    conn.commit()
    return conn


def build_networkx(data: dict[str, Any]) -> dict[str, Any]:
    import networkx as nx

    everything = nx.DiGraph()
    everything.add_nodes_from((p["id"], {"label": "Person", **p}) for p in data["persons"])
    everything.add_nodes_from((c["id"], {"label": "Company", **c}) for c in data["companies"])
    everything.add_nodes_from((c["id"], {"label": "City", **c}) for c in data["cities"])
    knows = nx.DiGraph()
    knows.add_nodes_from(p["id"] for p in data["persons"])
    knows.add_edges_from(data["knows"])
    works = nx.DiGraph()
    works.add_edges_from((p, c) for p, c, _ in data["works_at"])
    subsidiary = nx.DiGraph()
    subsidiary.add_nodes_from(c["id"] for c in data["companies"])
    subsidiary.add_edges_from(data["subsidiary_of"])
    return {"all": everything, "knows": knows, "works": works, "subsidiary": subsidiary}
