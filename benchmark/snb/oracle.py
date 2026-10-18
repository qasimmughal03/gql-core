"""Reference Answer Oracle for LDBC SNB Interactive v1 Queries.

Provides an independent, relational baseline (SQLite) loaded with the identical static
initial CSV snapshot to produce ground-truth results and verify 100% answer correctness
of GQL-Core execution before measuring speed.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DATASET_DIR = Path("benchmark/cache/ldbc_snb_impls/cypher/test-data/vanilla")


class SNBAnswerOracle:
    """Relational SQL Answer Oracle for LDBC SNB benchmark queries."""

    def __init__(self, dataset_dir: Path | str = DEFAULT_DATASET_DIR):
        self.dataset_dir = Path(dataset_dir)
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        cur = self.conn.cursor()

        # Tables
        cur.execute("""
            CREATE TABLE Person (
                id INTEGER PRIMARY KEY,
                firstName TEXT,
                lastName TEXT,
                gender TEXT,
                birthday INTEGER,
                creationDate INTEGER,
                locationIP TEXT,
                browserUsed TEXT
            );
        """)
        cur.execute("""
            CREATE TABLE City (
                id INTEGER PRIMARY KEY,
                name TEXT,
                url TEXT
            );
        """)
        cur.execute("""
            CREATE TABLE Post (
                id INTEGER PRIMARY KEY,
                imageFile TEXT,
                creationDate INTEGER,
                locationIP TEXT,
                browserUsed TEXT,
                language TEXT,
                content TEXT,
                length INTEGER
            );
        """)
        cur.execute("""
            CREATE TABLE Comment (
                id INTEGER PRIMARY KEY,
                creationDate INTEGER,
                locationIP TEXT,
                browserUsed TEXT,
                content TEXT,
                length INTEGER
            );
        """)
        cur.execute("""
            CREATE TABLE person_isLocatedIn_place (
                Person_id INTEGER,
                Place_id INTEGER
            );
        """)
        cur.execute("""
            CREATE TABLE person_knows_person (
                Person1_id INTEGER,
                Person2_id INTEGER,
                creationDate INTEGER
            );
        """)
        cur.execute("""
            CREATE TABLE post_hasCreator_person (
                Post_id INTEGER,
                Person_id INTEGER
            );
        """)
        cur.execute("""
            CREATE TABLE comment_hasCreator_person (
                Comment_id INTEGER,
                Person_id INTEGER
            );
        """)
        cur.execute("""
            CREATE TABLE comment_replyOf_post (
                Comment_id INTEGER,
                Post_id INTEGER
            );
        """)

        # Load data
        # Person
        p_csv = self.dataset_dir / "dynamic" / "person_0_0.csv"
        if p_csv.exists():
            with open(p_csv, "r", encoding="utf-8") as fp:
                r = csv.DictReader(fp, delimiter="|")
                rows = [
                    (
                        int(x["id"]),
                        x.get("firstName", ""),
                        x.get("lastName", ""),
                        x.get("gender", ""),
                        int(x["birthday"]) if x.get("birthday") else 0,
                        int(x["creationDate"]) if x.get("creationDate") else 0,
                        x.get("locationIP", ""),
                        x.get("browserUsed", ""),
                    )
                    for x in r
                ]
                cur.executemany("INSERT INTO Person VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)

        # Place (City)
        pl_csv = self.dataset_dir / "static" / "place_0_0.csv"
        if pl_csv.exists():
            with open(pl_csv, "r", encoding="utf-8") as fp:
                r = csv.DictReader(fp, delimiter="|")
                rows = [
                    (int(x["id"]), x.get("name", ""), x.get("url", ""))
                    for x in r
                    if x.get("type", "").lower() == "city"
                ]
                cur.executemany("INSERT INTO City VALUES (?, ?, ?)", rows)

        # Post
        post_csv = self.dataset_dir / "dynamic" / "post_0_0.csv"
        if post_csv.exists():
            with open(post_csv, "r", encoding="utf-8") as fp:
                r = csv.DictReader(fp, delimiter="|")
                rows = [
                    (
                        int(x["id"]),
                        x.get("imageFile", ""),
                        int(x["creationDate"]) if x.get("creationDate") else 0,
                        x.get("locationIP", ""),
                        x.get("browserUsed", ""),
                        x.get("language", ""),
                        x.get("content", ""),
                        int(x["length"]) if x.get("length") else 0,
                    )
                    for x in r
                ]
                cur.executemany("INSERT INTO Post VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)

        # Comment
        com_csv = self.dataset_dir / "dynamic" / "comment_0_0.csv"
        if com_csv.exists():
            with open(com_csv, "r", encoding="utf-8") as fp:
                r = csv.DictReader(fp, delimiter="|")
                rows = [
                    (
                        int(x["id"]),
                        int(x["creationDate"]) if x.get("creationDate") else 0,
                        x.get("locationIP", ""),
                        x.get("browserUsed", ""),
                        x.get("content", ""),
                        int(x["length"]) if x.get("length") else 0,
                    )
                    for x in r
                ]
                cur.executemany("INSERT INTO Comment VALUES (?, ?, ?, ?, ?, ?)", rows)

        # Relationships
        self._load_rel("dynamic/person_isLocatedIn_place_0_0.csv", "person_isLocatedIn_place", 2)
        self._load_rel("dynamic/person_knows_person_0_0.csv", "person_knows_person", 3)
        self._load_rel("dynamic/post_hasCreator_person_0_0.csv", "post_hasCreator_person", 2)
        self._load_rel("dynamic/comment_hasCreator_person_0_0.csv", "comment_hasCreator_person", 2)
        self._load_rel("dynamic/comment_replyOf_post_0_0.csv", "comment_replyOf_post", 2)

        # Create indices for fast joins
        cur.execute("CREATE INDEX idx_p_loc ON person_isLocatedIn_place(Person_id);")
        cur.execute("CREATE INDEX idx_k1 ON person_knows_person(Person1_id);")
        cur.execute("CREATE INDEX idx_k2 ON person_knows_person(Person2_id);")
        cur.execute("CREATE INDEX idx_post_hc ON post_hasCreator_person(Post_id);")
        cur.execute("CREATE INDEX idx_post_hc_p ON post_hasCreator_person(Person_id);")
        cur.execute("CREATE INDEX idx_com_hc ON comment_hasCreator_person(Comment_id);")
        cur.execute("CREATE INDEX idx_com_rop ON comment_replyOf_post(Post_id);")
        self.conn.commit()

    def _load_rel(self, rel_subpath: str, table_name: str, cols_count: int):
        f = self.dataset_dir / rel_subpath
        if not f.exists():
            return
        cur = self.conn.cursor()
        with open(f, "r", encoding="utf-8") as fp:
            r = csv.reader(fp, delimiter="|")
            next(r, None)
            placeholders = ", ".join(["?"] * cols_count)
            rows = []
            for row in r:
                if len(row) >= cols_count:
                    rows.append(tuple(int(x) if x.isdigit() else x for x in row[:cols_count]))
            cur.executemany(f"INSERT INTO {table_name} VALUES ({placeholders})", rows)

    def execute_is1(self, person_id: int) -> list[dict[str, Any]]:
        sql = """
            SELECT n.firstName AS firstName,
                   n.lastName AS lastName,
                   n.birthday AS birthday,
                   n.locationIP AS locationIP,
                   n.browserUsed AS browserUsed,
                   p.id AS cityId,
                   n.gender AS gender,
                   n.creationDate AS creationDate
            FROM Person n
            JOIN person_isLocatedIn_place edge ON n.id = edge.Person_id
            JOIN City p ON edge.Place_id = p.id
            WHERE n.id = ?;
        """
        cur = self.conn.cursor()
        cur.execute(sql, (person_id,))
        return [dict(r) for r in cur.fetchall()]

    def execute_is3(self, person_id: int) -> list[dict[str, Any]]:
        sql = """
            SELECT friend.id AS personId,
                   friend.firstName AS firstName,
                   friend.lastName AS lastName,
                   k.creationDate AS friendshipCreationDate
            FROM (
                SELECT Person2_id AS friend_id, creationDate FROM person_knows_person WHERE Person1_id = ?
                UNION ALL
                SELECT Person1_id AS friend_id, creationDate FROM person_knows_person WHERE Person2_id = ?
            ) k
            JOIN Person friend ON friend.id = k.friend_id
            ORDER BY friendshipCreationDate DESC, personId ASC;
        """
        cur = self.conn.cursor()
        cur.execute(sql, (person_id, person_id))
        return [dict(r) for r in cur.fetchall()]

    def execute_is5(self, message_id: int) -> list[dict[str, Any]]:
        sql = """
            SELECT p.id AS personId,
                   p.firstName AS firstName,
                   p.lastName AS lastName
            FROM Post m
            JOIN post_hasCreator_person edge ON m.id = edge.Post_id
            JOIN Person p ON edge.Person_id = p.id
            WHERE m.id = ?;
        """
        cur = self.conn.cursor()
        cur.execute(sql, (message_id,))
        return [dict(r) for r in cur.fetchall()]

    def execute_ic2(self, person_id: int, max_date: int) -> list[dict[str, Any]]:
        sql = """
            SELECT friend.id AS personId,
                   friend.firstName AS personFirstName,
                   friend.lastName AS personLastName,
                   message.id AS postOrCommentId,
                   message.content AS postOrCommentContent,
                   message.creationDate AS postOrCommentCreationDate
            FROM (
                SELECT Person2_id AS friend_id FROM person_knows_person WHERE Person1_id = ?
                UNION ALL
                SELECT Person1_id AS friend_id FROM person_knows_person WHERE Person2_id = ?
            ) k
            JOIN Person friend ON friend.id = k.friend_id
            JOIN post_hasCreator_person hc ON hc.Person_id = friend.id
            JOIN Post message ON message.id = hc.Post_id
            WHERE message.creationDate <= ?
            ORDER BY postOrCommentCreationDate DESC, postOrCommentId ASC
            LIMIT 20;
        """
        cur = self.conn.cursor()
        cur.execute(sql, (person_id, person_id, max_date))
        return [dict(r) for r in cur.fetchall()]

    def execute_ic8(self, person_id: int) -> list[dict[str, Any]]:
        sql = """
            SELECT person.id AS personId,
                   person.firstName AS personFirstName,
                   person.lastName AS personLastName,
                   comment.creationDate AS commentCreationDate,
                   comment.id AS commentId,
                   comment.content AS commentContent
            FROM Post post
            JOIN post_hasCreator_person start_edge ON start_edge.Post_id = post.id
            JOIN comment_replyOf_post rop ON rop.Post_id = post.id
            JOIN Comment comment ON comment.id = rop.Comment_id
            JOIN comment_hasCreator_person rep_edge ON rep_edge.Comment_id = comment.id
            JOIN Person person ON person.id = rep_edge.Person_id
            WHERE start_edge.Person_id = ?
            ORDER BY commentCreationDate DESC, commentId ASC
            LIMIT 20;
        """
        cur = self.conn.cursor()
        cur.execute(sql, (person_id,))
        return [dict(r) for r in cur.fetchall()]
