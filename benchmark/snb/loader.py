"""Reproducible LDBC SNB Interactive v1 Dataset Loader for GQL-Core.

Loads the official LDBC SNB static initial snapshot CSV dataset into a PropertyGraph
preserving identifiers, labels, relationship directions, and property types.
Measures loading elapsed time and peak memory consumption.
"""

from __future__ import annotations

import csv
import os
import time
from pathlib import Path
from typing import Any, Tuple

import psutil

from gql_core.graph import Edge, Node, PropertyGraph

DEFAULT_DATASET_DIR = Path("benchmark/cache/ldbc_snb_impls/cypher/test-data/vanilla")


def _try_parse_val(val: str) -> Any:
    val = val.strip()
    if not val:
        return None
    if val.isdigit() or (val.startswith("-") and val[1:].isdigit()):
        return int(val)
    try:
        return float(val)
    except ValueError:
        return val


def load_snb_dataset(
    dataset_dir: Path | str = DEFAULT_DATASET_DIR,
) -> Tuple[PropertyGraph, dict[str, Any]]:
    """Load the LDBC SNB dataset from CSV files into a PropertyGraph.
    
    Returns:
        (graph, stats_dict)
    """
    dataset_dir = Path(dataset_dir)
    if not dataset_dir.exists():
        raise FileNotFoundError(f"LDBC SNB dataset directory not found at {dataset_dir}")

    proc = psutil.Process()
    mem_before = proc.memory_info().rss
    start_time = time.perf_counter()

    graph = PropertyGraph()
    counts = {
        "nodes": 0,
        "edges": 0,
        "nodes_by_label": {},
        "edges_by_label": {},
    }

    def add_node(n_id: str, label: str, props: dict[str, Any]):
        n = Node(id=str(n_id), label=label, props=props)
        graph.add_node(n)
        counts["nodes"] += 1
        counts["nodes_by_label"][label] = counts["nodes_by_label"].get(label, 0) + 1

    def add_edge(e_id: str, label: str, src: str, dst: str, props: dict[str, Any]):
        e = Edge(id=str(e_id), label=label, src=str(src), dst=str(dst), props=props)
        graph.add_edge(e)
        counts["edges"] += 1
        counts["edges_by_label"][label] = counts["edges_by_label"].get(label, 0) + 1

    edge_counter = 0

    # 1. Static Nodes
    # Places (Cities, Countries, Continents)
    place_csv = dataset_dir / "static" / "place_0_0.csv"
    if place_csv.exists():
        with open(place_csv, mode="r", encoding="utf-8") as fp:
            reader = csv.DictReader(fp, delimiter="|")
            for row in reader:
                p_id = row["id"]
                sub_label = row.get("type", "Place").capitalize()
                props = {
                    "id": int(p_id) if p_id.isdigit() else p_id,
                    "name": row.get("name", ""),
                    "url": row.get("url", ""),
                    "type": row.get("type", ""),
                }
                add_node(f"place_{p_id}", sub_label, props)

    # Organisations (Companies, Universities)
    org_csv = dataset_dir / "static" / "organisation_0_0.csv"
    if org_csv.exists():
        with open(org_csv, mode="r", encoding="utf-8") as fp:
            reader = csv.DictReader(fp, delimiter="|")
            for row in reader:
                o_id = row["id"]
                sub_label = row.get("type", "Organisation").capitalize()
                props = {
                    "id": int(o_id) if o_id.isdigit() else o_id,
                    "name": row.get("name", ""),
                    "url": row.get("url", ""),
                    "type": row.get("type", ""),
                }
                add_node(f"org_{o_id}", sub_label, props)

    # Tags
    tag_csv = dataset_dir / "static" / "tag_0_0.csv"
    if tag_csv.exists():
        with open(tag_csv, mode="r", encoding="utf-8") as fp:
            reader = csv.DictReader(fp, delimiter="|")
            for row in reader:
                t_id = row["id"]
                props = {
                    "id": int(t_id) if t_id.isdigit() else t_id,
                    "name": row.get("name", ""),
                    "url": row.get("url", ""),
                }
                add_node(f"tag_{t_id}", "Tag", props)

    # TagClasses
    tc_csv = dataset_dir / "static" / "tagclass_0_0.csv"
    if tc_csv.exists():
        with open(tc_csv, mode="r", encoding="utf-8") as fp:
            reader = csv.DictReader(fp, delimiter="|")
            for row in reader:
                tc_id = row["id"]
                props = {
                    "id": int(tc_id) if tc_id.isdigit() else tc_id,
                    "name": row.get("name", ""),
                    "url": row.get("url", ""),
                }
                add_node(f"tagclass_{tc_id}", "TagClass", props)

    # 2. Dynamic Nodes
    # Persons
    person_csv = dataset_dir / "dynamic" / "person_0_0.csv"
    if person_csv.exists():
        with open(person_csv, mode="r", encoding="utf-8") as fp:
            reader = csv.DictReader(fp, delimiter="|")
            for row in reader:
                p_id = row["id"]
                props = {
                    "id": int(p_id) if p_id.isdigit() else p_id,
                    "firstName": row.get("firstName", ""),
                    "lastName": row.get("lastName", ""),
                    "gender": row.get("gender", ""),
                    "birthday": int(row["birthday"]) if row.get("birthday") else 0,
                    "creationDate": int(row["creationDate"]) if row.get("creationDate") else 0,
                    "locationIP": row.get("locationIP", ""),
                    "browserUsed": row.get("browserUsed", ""),
                }
                add_node(f"person_{p_id}", "Person", props)

    # Forums
    forum_csv = dataset_dir / "dynamic" / "forum_0_0.csv"
    if forum_csv.exists():
        with open(forum_csv, mode="r", encoding="utf-8") as fp:
            reader = csv.DictReader(fp, delimiter="|")
            for row in reader:
                f_id = row["id"]
                props = {
                    "id": int(f_id) if f_id.isdigit() else f_id,
                    "title": row.get("title", ""),
                    "creationDate": int(row["creationDate"]) if row.get("creationDate") else 0,
                }
                add_node(f"forum_{f_id}", "Forum", props)

    # Posts
    post_csv = dataset_dir / "dynamic" / "post_0_0.csv"
    if post_csv.exists():
        with open(post_csv, mode="r", encoding="utf-8") as fp:
            reader = csv.DictReader(fp, delimiter="|")
            for row in reader:
                p_id = row["id"]
                props = {
                    "id": int(p_id) if p_id.isdigit() else p_id,
                    "imageFile": row.get("imageFile", ""),
                    "creationDate": int(row["creationDate"]) if row.get("creationDate") else 0,
                    "locationIP": row.get("locationIP", ""),
                    "browserUsed": row.get("browserUsed", ""),
                    "language": row.get("language", ""),
                    "content": row.get("content", ""),
                    "length": int(row["length"]) if row.get("length") else 0,
                }
                add_node(f"post_{p_id}", "Post", props)

    # Comments
    comment_csv = dataset_dir / "dynamic" / "comment_0_0.csv"
    if comment_csv.exists():
        with open(comment_csv, mode="r", encoding="utf-8") as fp:
            reader = csv.DictReader(fp, delimiter="|")
            for row in reader:
                c_id = row["id"]
                props = {
                    "id": int(c_id) if c_id.isdigit() else c_id,
                    "creationDate": int(row["creationDate"]) if row.get("creationDate") else 0,
                    "locationIP": row.get("locationIP", ""),
                    "browserUsed": row.get("browserUsed", ""),
                    "content": row.get("content", ""),
                    "length": int(row["length"]) if row.get("length") else 0,
                }
                add_node(f"comment_{c_id}", "Comment", props)

    # 3. Edges
    # Edge file mappings: (path, label, is_symmetric, src_prefix, dst_prefix)
    edge_specs = [
        (dataset_dir / "dynamic" / "person_knows_person_0_0.csv", "KNOWS", False, "person_", "person_"),
        (dataset_dir / "dynamic" / "person_isLocatedIn_place_0_0.csv", "IS_LOCATED_IN", False, "person_", "place_"),
        (dataset_dir / "dynamic" / "post_hasCreator_person_0_0.csv", "HAS_CREATOR", False, "post_", "person_"),
        (dataset_dir / "dynamic" / "comment_hasCreator_person_0_0.csv", "HAS_CREATOR", False, "comment_", "person_"),
        (dataset_dir / "dynamic" / "comment_replyOf_post_0_0.csv", "REPLY_OF", False, "comment_", "post_"),
        (dataset_dir / "dynamic" / "comment_replyOf_comment_0_0.csv", "REPLY_OF", False, "comment_", "comment_"),
        (dataset_dir / "dynamic" / "forum_containerOf_post_0_0.csv", "CONTAINER_OF", False, "forum_", "post_"),
        (dataset_dir / "dynamic" / "forum_hasModerator_person_0_0.csv", "HAS_MODERATOR", False, "forum_", "person_"),
        (dataset_dir / "dynamic" / "forum_hasMember_person_0_0.csv", "HAS_MEMBER", False, "forum_", "person_"),
        (dataset_dir / "dynamic" / "post_isLocatedIn_place_0_0.csv", "IS_LOCATED_IN", False, "post_", "place_"),
        (dataset_dir / "dynamic" / "comment_isLocatedIn_place_0_0.csv", "IS_LOCATED_IN", False, "comment_", "place_"),
        (dataset_dir / "dynamic" / "person_hasInterest_tag_0_0.csv", "HAS_INTEREST", False, "person_", "tag_"),
        (dataset_dir / "dynamic" / "forum_hasTag_tag_0_0.csv", "HAS_TAG", False, "forum_", "tag_"),
        (dataset_dir / "dynamic" / "post_hasTag_tag_0_0.csv", "HAS_TAG", False, "post_", "tag_"),
        (dataset_dir / "dynamic" / "comment_hasTag_tag_0_0.csv", "HAS_TAG", False, "comment_", "tag_"),
        (dataset_dir / "dynamic" / "person_likes_post_0_0.csv", "LIKES", False, "person_", "post_"),
        (dataset_dir / "dynamic" / "person_likes_comment_0_0.csv", "LIKES", False, "person_", "comment_"),
        (dataset_dir / "dynamic" / "person_studyAt_organisation_0_0.csv", "STUDY_AT", False, "person_", "org_"),
        (dataset_dir / "dynamic" / "person_workAt_organisation_0_0.csv", "WORK_AT", False, "person_", "org_"),
        (dataset_dir / "static" / "organisation_isLocatedIn_place_0_0.csv", "IS_LOCATED_IN", False, "org_", "place_"),
        (dataset_dir / "static" / "place_isPartOf_place_0_0.csv", "IS_PART_OF", False, "place_", "place_"),
        (dataset_dir / "static" / "tag_hasType_tagclass_0_0.csv", "HAS_TYPE", False, "tag_", "tagclass_"),
        (dataset_dir / "static" / "tagclass_isSubclassOf_tagclass_0_0.csv", "IS_SUBCLASS_OF", False, "tagclass_", "tagclass_"),
    ]

    for f_path, label, is_symmetric, src_pre, dst_pre in edge_specs:
        if not f_path.exists():
            continue
        with open(f_path, mode="r", encoding="utf-8") as fp:
            reader = csv.reader(fp, delimiter="|")
            header = next(reader, None)
            if not header or len(header) < 2:
                continue
            for row in reader:
                if len(row) < 2:
                    continue
                src = f"{src_pre}{row[0]}"
                dst = f"{dst_pre}{row[1]}"
                edge_props: dict[str, Any] = {}
                if len(row) > 2 and len(header) > 2:
                    for k, v in zip(header[2:], row[2:]):
                        edge_props[k] = _try_parse_val(v)

                edge_counter += 1
                add_edge(f"e_{edge_counter}", label, src, dst, edge_props)
                if is_symmetric:
                    edge_counter += 1
                    add_edge(f"e_{edge_counter}", label, dst, src, edge_props)

    elapsed = time.perf_counter() - start_time
    mem_after = proc.memory_info().rss
    peak_rss_mb = (mem_after - mem_before) / (1024 * 1024)

    counts["load_time_seconds"] = round(elapsed, 3)
    counts["peak_memory_rss_mb"] = round(peak_rss_mb, 2)

    return graph, counts


if __name__ == "__main__":
    print("Loading LDBC SNB vanilla dataset...")
    g, stats = load_snb_dataset()
    print(f"Loaded in {stats['load_time_seconds']}s")
    print(f"Total Nodes: {stats['nodes']}")
    print(f"Total Edges: {stats['edges']}")
    print(f"Memory RSS increase: {stats['peak_memory_rss_mb']} MB")
    print("Node Labels:", stats["nodes_by_label"])
    print("Edge Labels:", stats["edges_by_label"])
