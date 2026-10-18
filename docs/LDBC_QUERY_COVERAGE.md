# LDBC SNB Interactive v1 Query Coverage & Semantic Compatibility Report

**Benchmark Suite**: LDBC Social Network Benchmark (SNB) Interactive v1 (Read-Only)  
**Specification Version**: v1.0.0  
**GQL-Core Engine Version**: `0.2.0`  
**Evaluation Dataset**: LDBC SNB Official SF0.1 Initial Snapshot (327,588 nodes, 1,477,965 edges)  

> [!IMPORTANT]
> **Mandatory Benchmark Disclaimer**:  
> *Unaudited read-only performance study using LDBC SNB Interactive v1 queries.*  
> This evaluation is an independent engineering study for query correctness, semantic compatibility, and execution latency. It does not constitute an officially audited or certified LDBC benchmark result.

---

## 1. Executive Summary

The LDBC SNB Interactive workload consists of **21 read operations** (7 Interactive Short reads: `IS1`–`IS7`, and 14 Interactive Complex reads: `IC1`–`IC14`).

To ensure rigorous scientific integrity, this audit establishes a strict **four-tier semantic compatibility classification**:
- **Category A (Exact Supported Official Operation)**: Matches the official query syntax and semantics with zero modification. (**1 query: `IS1`**)
- **Category B (Semantically Equivalent Translation)**: Adapts minor language idiosyncrasies while preserving 100% identical logical semantics and results across all valid inputs. (**1 query: `IS3`**)
- **Category C (Simplified / Partially Equivalent Adaptation)**: Rewrites or restricts domain semantics (e.g., substituting concrete `Post` for polymorphic `Message`). **These are tracked as exploratory performance studies and explicitly NOT counted as official benchmark passes.** (**3 queries: `IS5`, `IC2`, `IC8`**)
- **Category D (Unsupported Operation)**: Queries requiring language capabilities outside GQL-Core v0.2.0 (e.g. multi-clause pipelines `WITH`, scalar functions, or shortest path). (**16 queries**)

**Key Results Summary**:
- **Official Query Passes (Categories A & B)**: **2 / 2 queries (100% pass rate, 4/4 parameter runs)** verified with exact answer equality against the SQLite Answer Oracle.
- **Simplified Adaptations (Category C)**: **3 queries** verified against an equivalent adapted relational baseline.
- **Official Coverage of Total LDBC SNB Workload**: **9.52% (2 / 21 official queries)**.

---

## 2. Complete 21-Query Semantic Compatibility Matrix

| Query ID | Name | Official Family | Category | Status in GQL-Core | Reason for Category / Unsupported Feature |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **IS1** | Profile of a person | 1-hop lookup | **A** | **Executable** | **Exact match**: Single-hop pattern lookup with property projection. |
| **IS2** | Recent messages of a person | Chained pipeline | **D** | Unsupported | Requires `WITH ... ORDER BY ... LIMIT` pipeline and `coalesce()`. |
| **IS3** | Friends of a person | 1-hop undirected join | **B** | **Executable** | **Semantically equivalent**: `ORDER BY friendshipCreationDate DESC, personId ASC` is equivalent to `toInteger(personId)` because IDs are native 64-bit integers. |
| **IS4** | Content of a message | 1-node lookup | **D** | Unsupported | Requires `coalesce(m.content, m.imageFile)` over polymorphic message node. |
| **IS5** | Creator of a message | 1-hop lookup | **C** | *Adapted Study* | **Partial adaptation**: Official query matches `(m:Message)` (covering `Post` and `Comment`). Adapted to `(m:Post)` only. |
| **IS6** | Forum of a message | Multi-hop RPQ | **D** | Unsupported | Requires zero-depth RPQ composition `(:REPLY_OF*0..)` from Comment to root Post. |
| **IS7** | Replies of a message | Optional join | **D** | Unsupported | Requires `OPTIONAL MATCH` and `CASE WHEN` for author relationship test. |
| **IC1** | Friends with certain name | Variable path | **D** | Unsupported | Requires `shortestPath((:Person)-[:KNOWS*1..3]-(:Person))` and `WITH` pipeline. |
| **IC2** | Recent messages by friends | 2-hop filtered join | **C** | *Adapted Study* | **Partial adaptation**: Adapts `Message` to `Post` only; omits comments and `coalesce(content, imageFile)`. |
| **IC3** | Friends visiting X and Y | Multi-hop grouping | **D** | Unsupported | Requires 2-hop path, `WITH` aggregation, and `collect()` list operations. |
| **IC4** | New topics | Aggregation | **D** | Unsupported | Requires `WITH` aggregation, `CASE WHEN`, and date range arithmetic. |
| **IC5** | New groups | Grouping / Aggregation | **D** | Unsupported | Requires `WITH`, `OPTIONAL MATCH`, and `count()` aggregation on member posts. |
| **IC6** | Tag co-occurrence | Multi-hop aggregation | **D** | Unsupported | Requires 2-hop `KNOWS` path, `WITH` clause, and tag co-occurrence aggregation. |
| **IC7** | Recent likes | Multi-hop join | **D** | Unsupported | Requires `WITH` clause, `head()` list function, and date difference arithmetic. |
| **IC8** | Recent replies | 3-hop join | **C** | *Adapted Study* | **Partial adaptation**: Official query matches `(:Message)<-[:REPLY_OF]-(comment:Comment)`. Adapted to `(post:Post)` only, dropping nested replies to Comments. |
| **IC9** | Messages by friend network | Recursive path | **D** | Unsupported | Requires variable-length path (1..2), `WITH` clause, and `UNWIND`. |
| **IC10** | Friend recommendation | Scoring / Path | **D** | Unsupported | Requires 2-hop path, `OPTIONAL MATCH`, and birthday month calculation. |
| **IC11** | Job referral | Temporal path | **D** | Unsupported | Requires variable path (1..2), `WORK_AT` relationship filtering, and `WITH`. |
| **IC12** | Expert search | Subquery / Path | **D** | Unsupported | Requires 1-hop `KNOWS`, tag hierarchy traversal, and `collect()` aggregation. |
| **IC13** | Single-pair shortest path | Shortest path | **D** | Unsupported | Requires `shortestPath((p1)-[:KNOWS*]-(p2))` built-in function. |
| **IC14** | Weighted paths | Shortest path | **D** | Unsupported | Requires `allShortestPaths()`, `UNWIND`, and dynamic path weight summation. |

---

## 3. Deep Dive: Message Polymorphism (`Post` vs `Comment`)

In the LDBC SNB schema specification, the concept of a `Message` is polymorphic:

```
          ┌───────────────────────────┐
          │          Message          │
          │  (Abstract Super-Entity)  │
          └─────────────┬─────────────┘
                        │
         ┌──────────────┴──────────────┐
         ▼                             ▼
┌──────────────────┐          ┌──────────────────┐
│       Post       │          │     Comment      │
│                  │          │                  │
│ • content        │          │ • content        │
│ • imageFile      │          │ • length         │
│ • language       │          │ • creationDate   │
└──────────────────┘          └──────────────────┘
```

### Why Category C Queries Differ from Official Queries:
1. **Interactive Short 5 (`IS5`)**:
   - *Official Query*: `MATCH (m:Message {id: $messageId})-[:HAS_CREATOR]->(p:Person)`
   - *Behavior on Comments*: In LDBC graphs, `Comment` nodes outnumber `Post` nodes (151,043 Comments vs 135,701 Posts in SF0.1). When `$messageId` is a Comment, the official query returns the comment author.
   - *GQL-Core Adaptation*: Restricting the pattern to `(m:Post)` immediately returns `[]` (0 rows) for all comment IDs.
2. **Interactive Complex 2 (`IC2`)**:
   - *Official Query*: Fetches recent messages created by friends.
   - *Impact of Restriction*: All comments written by friends are silently excluded, and posts with image files but no text content return `null` instead of the image path.
3. **Interactive Complex 8 (`IC8`)**:
   - *Official Query*: Fetches recent replies to messages created by a person: `(person)<-[:HAS_CREATOR]-(:Message)<-[:REPLY_OF]-(comment)`.
   - *Impact of Restriction*: Restricting the intermediate node to `Post` drops all nested discussion replies (where a user replied to a comment rather than the root post).

**Conclusion**: These queries demonstrate GQL-Core's fast multi-hop join capabilities over concrete types, but cannot be presented as official passes of the LDBC SNB specification.

---

## 4. Performance Study: Official LDBC SNB SF0.1 Dataset

### 4.1 Ingestion Telemetry
- **Dataset**: `social_network-sf0.1-CsvComposite-LongDateFormatter`
- **Total Ingestion Time**: **23.78 seconds**
- **Nodes Loaded**: **327,588**
- **Edges Loaded**: **1,477,965**
- **Peak Resident Memory Delta (RSS)**: **977.01 MB**
- **Data Integrity**: 100% partition ingestion across all 62 CSV files; zero missing records; zero identifier collisions.

### 4.2 Latency Results (GQL-Core v0.2.0 vs SQLite Baseline)

Measured over 5 sample runs following 2 warm-up iterations on an Intel Core i5-8265U (Windows 11, Python 3.14):

| Query ID | Category | Parameter ID | Result Rows | GQL-Core Median (ms) | GQL-Core P95 (ms) | SQLite Baseline (ms) | Speedup / Ratio | Parity Status |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **IS1** | **A** | `IS1_sf01_p1` (`id=2199023256816`) | 1 | **5.132** | 5.415 | 0.229 | Relational baseline faster | **VERIFIED EXACT MATCH** |
| **IS1** | **A** | `IS1_sf01_p2` (`id=6597069767242`) | 1 | **4.104** | 4.369 | 0.067 | Relational baseline faster | **VERIFIED EXACT MATCH** |
| **IS3** | **B** | `IS3_sf01_p1` (`id=2199023256816`) | 269 | **9.102** | 9.488 | 1.421 | Relational baseline faster | **VERIFIED EXACT MATCH** |
| **IS3** | **B** | `IS3_sf01_p2` (`id=6597069767242`) | 230 | **8.728** | 9.063 | 1.023 | Relational baseline faster | **VERIFIED EXACT MATCH** |
| **IS5** | *C* | `IS5_sf01_p1` (`id=206158430209`) | 0 | 234.182 | 241.529 | 0.160 | Relational baseline faster | VERIFIED EXACT MATCH |
| **IC2** | *C* | `IC2_sf01_p1` (`id=2199023256816`) | 20 | 516.997 | 552.488 | 18.607 | Relational baseline faster | VERIFIED EXACT MATCH |
| **IC8** | *C* | `IC8_sf01_p1` (`id=2199023256816`) | 20 | 39.348 | 43.155 | 4.292 | Relational baseline faster | VERIFIED EXACT MATCH |

### 4.3 Detailed Phase Breakdown

GQL-Core separates query processing into compilation (parsing + AST generation), planning (relational operator tree construction), and execution:

| Operation | Query ID | Parse Phase | Plan Phase | Execution Phase | Total Median |
| :--- | :--- | :---: | :---: | :---: | :---: |
| **Point Lookup** | `IS1_sf01_p1` | 1.28 ms | 0.05 ms | 3.80 ms | **5.13 ms** |
| **Point Lookup** | `IS1_sf01_p2` | 1.15 ms | 0.04 ms | 2.91 ms | **4.10 ms** |
| **Undirected Join + Sort** | `IS3_sf01_p1` | 1.34 ms | 0.05 ms | 7.71 ms | **9.10 ms** |
| **Undirected Join + Sort** | `IS3_sf01_p2` | 1.26 ms | 0.05 ms | 7.42 ms | **8.73 ms** |

---

## 5. Architectural Insights & Future Evolution

1. **In-Memory Join Efficiency**: For 1-hop and 2-hop joins (`IS1`, `IS3`), GQL-Core delivers single-digit millisecond latency (4–9 ms) on a 1.8-million element graph in pure Python without native C extensions.
2. **Path to Category C Full Compliance**: Supporting polymorphic `Message` requires adding label union / disjunction expressions (`:Post|Comment`) to the parser and executor, which is planned for v0.3.0.
3. **Reproducibility Guarantee**: Anyone can replicate this benchmark with the provided script:
   ```bash
   python -m benchmark.snb.runner --dataset official_sf01
   ```
