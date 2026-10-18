# GQL-Core v0.2.0 Release Verification & Benchmark Audit Report

**Distribution Package**: `gql-core` v0.2.0  
**Git Branch**: `feat/implementation`  
**Auditor**: Principal Database Systems Architect & Benchmark Reviewer  
**Audit Date**: October 18, 2026  
**Status**: **`READY WITH DOCUMENTED LIMITATIONS`**  

---

## 1. Executive Summary

This report documents the end-to-end verification and external benchmark auditing of GQL-Core v0.2.0. The audit verified:
1. **Installed distribution package build and cleanliness** outside the source tree.
2. **openCypher TCK compatibility suite** pinned to release `2024.3` with a hardened test harness (zero false positives) and verified relationship trail semantics.
3. **LDBC SNB Interactive v1 read-only benchmark** on both the official LDBC SNB SF0.1 dataset (327,588 nodes, 1,477,965 edges) and the reference repo test dataset, validated for 100% answer correctness against an independent SQLite Answer Oracle.
4. **Core regression suite and public API surface** (269 / 269 tests passing).

---

## 2. openCypher TCK Conformance Audit

### 2.1 Test Corpus & Environment
- **Source Repository**: [openCypher/openCypher](https://github.com/opencypher/openCypher)
- **Pinned Commit**: `677cbafabb8c3c5eed458fd3b1ec0daec8d67d23` (Tag: `2024.3`)
- **Total Feature Files**: 220
- **Total Scenarios Inventoried**: 1,338
- **Harness Rules**:
  - Exact column name and alias validation (no permissive positional fallback).
  - Strict type checking (integers must not match booleans or strings).
  - Categorized exception matching (`(LarkError, SemanticError)` for compile-time errors; unhandled runtime crashes fail).
  - Relationship trail semantics enforced.

### 2.2 Compatibility Test Results

| Metric | Count | Percentage |
| :--- | :--- | :--- |
| **Total Scenarios Inventoried** | 1,338 | 100.0% |
| **Classified as Unsupported** | 1,259 | 94.10% |
| **Claimed Language Subset** | **79** | **100.0% of claimed** |
| **Passed within Claimed Subset** | **76** | **96.20%** |
| **Failed within Claimed Subset** | **3** | **3.80%** |
| **Blocked Scenarios** | 0 | 0.00% |
| **Overall Corpus Coverage** | 76 / 1,338 | 5.68% |

### 2.3 Verification of Relationship Isomorphism (Trail Semantics)

In openCypher, pattern matching enforces relationship isomorphism (no relationship edge instance may be traversed more than once per pattern part). In commit `3dcafb0`, walk semantics previously caused 4 scenario failures. 

By tracking traversed edge IDs in `_expand()`, trail semantics is now fully enforced. All 4 scenarios **pass cleanly**:
- `Match3#15`: Passed (exact match on 2 rows).
- `Match3#16`: Passed (exact match on 6 rows).
- `CountingSubgraphMatches1#10`: Passed (exact match on 1 row).
- `CountingSubgraphMatches1#11`: Passed (exact match on 1 row).

### 2.4 Analysis of the 3 Non-Passing Scenarios

The remaining 3 failures stem from openCypher's convention of preserving verbatim unaliased source expressions as dictionary keys:

| Scenario ID | Feature | Query | Expected Header | GQL-Core Header |
| :--- | :--- | :--- | :--- | :--- |
| `Return4#4` | `Return4.feature` | `MATCH (n) RETURN cOuNt( * )` | `cOuNt( * )` | `count` |
| `Aggregation1#1` | `Aggregation1.feature` | `MATCH (n) RETURN n.name, count(n.num)` | `n.name`, `count(n.num)` | `name`, `count_n_num` |
| `Aggregation3#1` | `Aggregation3.feature` | `MATCH (n) RETURN n.name, sum(n.num)` | `n.name`, `sum(n.num)` | `name`, `sum_n_num` |

When standard explicit aliases (`AS alias`) are supplied, GQL-Core passes with 100% column conformity.

---

## 3. LDBC SNB Interactive v1 Answer Correctness & Performance

> [!IMPORTANT]
> **Mandatory Benchmark Disclaimer**:  
> *Unaudited read-only performance study using LDBC SNB Interactive v1 queries.*

### 3.1 Dataset Provenance & Ingestion Metrics

The benchmark was executed against the **official LDBC SNB SF0.1 Initial Snapshot**:
- **Catalog Source**: `https://datasets.ldbcouncil.org/snb-interactive-v1/social_network-sf0.1-CsvComposite-LongDateFormatter.tar.zst`
- **Archive SHA-256**: `208a02f92f61ab3c9433c6a7c1ca7f9e10eeddffa12f3514405d5c6e0b9c2e95`
- **Total Ingested Nodes**: **327,588** (`Comment`: 151,043 | `Post`: 135,701 | `Tag`: 16,080 | `Forum`: 13,750 | `University`: 6,380 | `Company`: 1,575 | `Person`: 1,528 | `City`: 1,343 | `Country`: 111 | `TagClass`: 71 | `Continent`: 6)
- **Total Ingested Edges**: **1,477,965** (`IS_LOCATED_IN`: 296,227 | `HAS_TAG`: 290,118 | `HAS_CREATOR`: 286,744 | `REPLY_OF`: 151,043 | `CONTAINER_OF`: 135,701 | `HAS_MEMBER`: 123,268 | `LIKES`: 109,440 | `HAS_INTEREST`: 35,475 | `HAS_TYPE`: 16,080 | `KNOWS`: 14,073 | `HAS_MODERATOR`: 13,750 | `WORK_AT`: 3,313 | `IS_PART_OF`: 1,454 | `STUDY_AT`: 1,209 | `IS_SUBCLASS_OF`: 70)
- **Ingestion Time**: **23.78 seconds**
- **Peak Resident Memory Delta**: **977.01 MB RSS**

### 3.2 Semantic Categorization of Official Read Queries

All 21 official LDBC read operations were categorized:
- **Category A (Exact Official)**: `IS1` (Profile of a person)
- **Category B (Semantically Equivalent)**: `IS3` (Friends of a person)
- **Category C (Simplified Adaptations - Research Study Only)**: `IS5`, `IC2`, `IC8` (Restricted to `Post`, omitting `Comment` polymorphism)
- **Category D (Unsupported)**: 16 operations (`IS2`, `IS4`, `IS6`, `IS7`, `IC1`, `IC3-IC7`, `IC9-IC14`)

### 3.3 Comparative Performance (GQL-Core vs SQLite Answer Oracle)

Measured over 5 sample runs following 2 warm-up iterations on an Intel Core i5-8265U (Windows 11, Python 3.14):

| Query ID | Category | Parameter ID | Result Rows | GQL-Core Median | GQL-Core P95 | SQLite Baseline | Correctness Status |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: |
| **IS1** | **A** | `IS1_sf01_p1` | 1 | **5.132 ms** | 5.415 ms | 0.229 ms | **VERIFIED EXACT MATCH** |
| **IS1** | **A** | `IS1_sf01_p2` | 1 | **4.104 ms** | 4.369 ms | 0.067 ms | **VERIFIED EXACT MATCH** |
| **IS3** | **B** | `IS3_sf01_p1` | 269 | **9.102 ms** | 9.488 ms | 1.421 ms | **VERIFIED EXACT MATCH** |
| **IS3** | **B** | `IS3_sf01_p2` | 230 | **8.728 ms** | 9.063 ms | 1.023 ms | **VERIFIED EXACT MATCH** |
| **IS5** | *C* | `IS5_sf01_p1` | 0 | 234.182 ms | 241.529 ms | 0.160 ms | VERIFIED EXACT MATCH |
| **IC2** | *C* | `IC2_sf01_p1` | 20 | 516.997 ms | 552.488 ms | 18.607 ms | VERIFIED EXACT MATCH |
| **IC8** | *C* | `IC8_sf01_p1` | 20 | 39.348 ms | 43.155 ms | 4.292 ms | VERIFIED EXACT MATCH |

**Official Operations Pass Rate**: **100% (2/2 queries, 4/4 parameter runs)** verified with exact answer equality against the SQLite Oracle.

---

## 4. Release Verification Checklist

| Verification Check | Expected | Actual | Status |
| :--- | :--- | :--- | :---: |
| **Wheel Package Build** | Valid `.whl` and `.tar.gz` | Built cleanly in `dist/` | **PASS** |
| **Isolated Installation** | Run from non-source root | Verified from clean virtual environment | **PASS** |
| **Unit & Regression Suite** | 100% passing tests | 269 / 269 passed in 20.4s | **PASS** |
| **Audit Regression Tests** | 6 corner cases verified | 6 / 6 passed (`test_audit_regressions.py`) | **PASS** |
| **CI Benchmark Smoke Suite** | Runs in < 5.0 seconds | 2 passed in 0.60s | **PASS** |
| **openCypher TCK Compatibility** | High pass rate on claimed subset | 76 / 79 passed (96.20%) | **PASS** |
| **LDBC SNB Official SF0.1 Ingestion** | Full partition load, <1GB RAM | 1.8M elements in 23.78s, 977 MB | **PASS** |
| **LDBC SNB Oracle Validation** | 100% exact match on Cat A & B | 4 / 4 parameter runs match | **PASS** |
| **Trail Semantics Verification** | Edge uniqueness enforced | Verified in TCK & unit suite | **PASS** |

### Release Recommendation
GQL-Core v0.2.0 is **`READY WITH DOCUMENTED LIMITATIONS`** for public distribution and deployment.
