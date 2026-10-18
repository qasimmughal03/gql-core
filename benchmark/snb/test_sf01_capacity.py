"""Capacity and memory measurement for official LDBC SNB SF0.1 dataset.
"""

import csv
import os
import psutil
import time
from pathlib import Path
from gql_core import PropertyGraph, Node, Edge

DATASET_DIR = Path("benchmark/cache/sf01/social_network-sf0.1-CsvComposite-LongDateFormatter")


def measure_sf01_ingestion():
    proc = psutil.Process()
    m0 = proc.memory_info().rss / (1024 * 1024)
    print(f"Initial RSS: {m0:.1f} MB")
    t0 = time.perf_counter()

    graph = PropertyGraph()

    # Dynamic nodes
    print("Loading Person...")
    with open(DATASET_DIR / "dynamic" / "person_0_0.csv", "r", encoding="utf-8") as fp:
        for r in csv.DictReader(fp, delimiter="|"):
            graph.add_node(Node(f"person_{r['id']}", "Person", {"id": int(r['id']), "firstName": r["firstName"], "lastName": r["lastName"]}))
    print(f"Persons: {len(graph._nodes)}, RSS: {proc.memory_info().rss/1024/1024:.1f} MB")

    print("Loading Post...")
    with open(DATASET_DIR / "dynamic" / "post_0_0.csv", "r", encoding="utf-8") as fp:
        for r in csv.DictReader(fp, delimiter="|"):
            graph.add_node(Node(f"post_{r['id']}", "Post", {"id": int(r['id']), "creationDate": int(r["creationDate"])}))
    print(f"Posts + Persons: {len(graph._nodes)}, RSS: {proc.memory_info().rss/1024/1024:.1f} MB")

    print("Loading Comment...")
    with open(DATASET_DIR / "dynamic" / "comment_0_0.csv", "r", encoding="utf-8") as fp:
        for r in csv.DictReader(fp, delimiter="|"):
            graph.add_node(Node(f"comment_{r['id']}", "Comment", {"id": int(r['id']), "creationDate": int(r["creationDate"])}))
    print(f"Total dynamic nodes: {len(graph._nodes)}, RSS: {proc.memory_info().rss/1024/1024:.1f} MB")

    # Static nodes
    print("Loading City...")
    with open(DATASET_DIR / "static" / "place_0_0.csv", "r", encoding="utf-8") as fp:
        for r in csv.DictReader(fp, delimiter="|"):
            sub_label = r.get("type", "Place").capitalize()
            graph.add_node(Node(f"place_{r['id']}", sub_label, {"id": int(r['id']), "name": r["name"]}))
    print(f"Total nodes: {len(graph._nodes)}, RSS: {proc.memory_info().rss/1024/1024:.1f} MB")

    # Relationships
    print("Loading KNOWS edges...")
    e_cnt = 0
    with open(DATASET_DIR / "dynamic" / "person_knows_person_0_0.csv", "r", encoding="utf-8") as fp:
        r = csv.reader(fp, delimiter="|")
        next(r, None)
        for row in r:
            e_cnt += 1
            graph.add_edge(Edge(f"e_k_{e_cnt}", "KNOWS", f"person_{row[0]}", f"person_{row[1]}", {"creationDate": int(row[2])}))
    print(f"KNOWS edges: {e_cnt}, RSS: {proc.memory_info().rss/1024/1024:.1f} MB")

    print("Loading IS_LOCATED_IN edges...")
    with open(DATASET_DIR / "dynamic" / "person_isLocatedIn_place_0_0.csv", "r", encoding="utf-8") as fp:
        r = csv.reader(fp, delimiter="|")
        next(r, None)
        for row in r:
            e_cnt += 1
            graph.add_edge(Edge(f"e_loc_{e_cnt}", "IS_LOCATED_IN", f"person_{row[0]}", f"place_{row[1]}", {}))

    print("Loading HAS_CREATOR edges...")
    with open(DATASET_DIR / "dynamic" / "post_hasCreator_person_0_0.csv", "r", encoding="utf-8") as fp:
        r = csv.reader(fp, delimiter="|")
        next(r, None)
        for row in r:
            e_cnt += 1
            graph.add_edge(Edge(f"e_hc_{e_cnt}", "HAS_CREATOR", f"post_{row[0]}", f"person_{row[1]}", {}))

    print(f"Total edges loaded: {e_cnt}, Total time: {time.perf_counter()-t0:.2f}s, Final RSS: {proc.memory_info().rss/1024/1024:.1f} MB")


if __name__ == "__main__":
    measure_sf01_ingestion()
