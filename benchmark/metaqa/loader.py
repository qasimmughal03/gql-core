"""MetaQA KB and question loading.

The KB is a list of ``subject|relation|object`` triples whose entities are plain
strings: the same string is the same entity everywhere (a person, a tag and a
film title can coincide). We therefore build exactly one node per distinct
string, keyed by the string, with a ``name`` property, and give it every label
implied by the roles it plays (``Movie`` for triple subjects; Person, Year,
Language, Genre, Tag, Votes or Rating for objects, by relation). Every triple
becomes one directed edge Movie -[relation]-> object. No triple is dropped or
added.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from gql_core.graph import Edge, Node, PropertyGraph

REPO_ID = "camazlucas/MetaQA"
CACHE_DIR = Path("benchmark/cache/metaqa")
HOPS = (1, 2, 3)

OBJECT_LABEL = {
    "directed_by": "Person",
    "written_by": "Person",
    "starred_actors": "Person",
    "release_year": "Year",
    "in_language": "Language",
    "has_genre": "Genre",
    "has_tags": "Tag",
    "has_imdb_votes": "Votes",
    "has_imdb_rating": "Rating",
}

_TOPIC_RE = re.compile(r"\[([^\]]+)\]")


@dataclass
class MetaQAQuestion:
    qid: str
    hops: int
    question: str
    topic: str
    answers: list[str]


def download(cache_dir: Path = CACHE_DIR) -> None:
    from huggingface_hub import hf_hub_download

    for f in ["kb/kb.txt"] + [f"{h}-hop/vanilla/qa_test.txt" for h in HOPS]:
        hf_hub_download(REPO_ID, f, repo_type="dataset", local_dir=str(cache_dir))


def read_triples(cache_dir: Path = CACHE_DIR) -> list[tuple[str, str, str]]:
    triples = []
    with open(cache_dir / "kb" / "kb.txt", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            s, r, o = line.split("|", 2)
            triples.append((s, r, o))
    return triples


def load_graph(cache_dir: Path = CACHE_DIR) -> tuple[PropertyGraph, list[tuple[str, str, str]]]:
    triples = read_triples(cache_dir)
    labels: dict[str, set[str]] = {}
    for s, r, o in triples:
        labels.setdefault(s, set()).add("Movie")
        labels.setdefault(o, set()).add(OBJECT_LABEL[r])
    graph = PropertyGraph()
    for name, lbls in labels.items():
        ordered = tuple(sorted(lbls))
        graph.add_node(Node(name, ordered[0], {"name": name}, labels=ordered))
    for i, (s, r, o) in enumerate(triples):
        graph.add_edge(Edge(f"t{i}", r, s, o))
    return graph, triples


def load_questions(hops: int, cache_dir: Path = CACHE_DIR) -> list[MetaQAQuestion]:
    out = []
    with open(cache_dir / f"{hops}-hop" / "vanilla" / "qa_test.txt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.rstrip("\n")
            if not line:
                continue
            q, ans = line.split("\t")
            m = _TOPIC_RE.search(q)
            out.append(MetaQAQuestion(qid=f"{hops}hop-{i}", hops=hops, question=q,
                                      topic=m.group(1) if m else "", answers=ans.split("|")))
    return out
