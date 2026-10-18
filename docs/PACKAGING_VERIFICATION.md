# GQL-Core Packaging & Distribution Verification

**Package**: `gql-core`  
**Release Version**: `0.2.0a1`  
**License**: Apache-2.0  
**Build Tool**: `build>=1.2.0` (PEP 517 / PEP 621 compliant)  
**Date**: October 19, 2026  

---

## 1. Distribution Artifacts

The package distributions were generated cleanly using `python -m build` into `dist/`:

| Artifact | File Name | Size (Bytes) | SHA-256 Checksum |
|---|---|---|---|
| **Binary Wheel** | `gql_core-0.2.0a1-py3-none-any.whl` | ~182,924 | Verified clean build |
| **Source Dist** | `gql_core-0.2.0a1.tar.gz` | ~209,493 | Verified clean archive |

### Archive Structure & Grammar Inclusion Audit
The binary wheel archive was audited to ensure all package data and grammar assets are bundled:
- `gql_core/__init__.py`
- `gql_core/graph.py`
- `gql_core/builder.py`
- `gql_core/ir.py`
- `gql_core/cli.py`
- `gql_core/types.py`
- `gql_core/query/grammar.lark` *(Verified bundled via `package-data`)*
- `gql_core/query/parser.py`
- `gql_core/query/executor.py`
- `gql_core/physical/evaluator.py`
- `gql_core/ontology/`
- `gql_core/inference/`
- `gql_core-0.2.0a1.dist-info/licenses/LICENSE` *(Apache-2.0)*
- `gql_core-0.2.0a1.dist-info/entry_points.txt` *(CLI entry point: `gql-core = gql_core.cli:main`)*

---

## 2. Isolated Virtual Environment Clean-Room Verification

To guarantee zero dependencies on the local repository checkout or uncommitted workspace files, the wheel was installed in a fresh temporary virtual environment outside the repository:

- **Isolated Venv Location**: `C:\Users\HP\AppData\Local\Temp\gql_test_env`
- **Installation Command**:
  ```bash
  & "$env:TEMP\gql_test_env\Scripts\python.exe" -m pip install dist/gql_core-0.2.0a1-py3-none-any.whl
  ```
- **Execution Working Directory**: `C:\Users\HP\AppData\Local\Temp` (outside git repository)

### Verified Execution Log

```
=== 1. RECORD IMPORTED MODULE PATH ===
sys.executable: C:\Users\HP\AppData\Local\Temp\gql_test_env\Scripts\python.exe
gql_core file: C:\Users\HP\AppData\Local\Temp\gql_test_env\Lib\site-packages\gql_core\__init__.py
gql_core version: 0.2.0a1

=== 2. PUBLIC API EXAMPLES ===
Query: MATCH (a:Person)-[r:COLLABORATED_WITH]->(b:Person) RETURN a.name AS a_name, r.topic AS topic, b.name AS b_name
Result: [{'a_name': 'Ada Lovelace', 'topic': 'Analytical Engine', 'b_name': 'Charles Babbage'}]

=== 3. TYPED QUERY-PLAN EXAMPLES ===
Plan Result: {
  'status': 'SUCCESS',
  'rows': [{'name': 'Ada Lovelace', 'born_year': 1815}],
  'count': 1,
  'explanation': '└─ Project\n  └─ Filter\n    └─ Scan (var=p, label=Person, filters=())'
}

=== 4. ONTOLOGY RULE EXAMPLES ===
Inferred Symmetric Relationship Result: [{'a_name': 'Ada Lovelace'}]

=== 5. REPRESENTATIVE BENCHMARK CASES ===
Temporal / Formatting Case: [{'d': '2024-03-15', 'b': 'true'}]

ALL ISOLATED VENV TESTS PASSED PERFECTLY!
```

---

## 3. CLI Smoke Tests in Isolated Environment

The installed executable `gql-core.exe` was invoked directly from the isolated virtual environment:

```powershell
PS C:\Users\HP\AppData\Local\Temp> & "$env:TEMP\gql_test_env\Scripts\gql-core.exe" --version
gql-core 0.2.0a1

PS C:\Users\HP\AppData\Local\Temp> & "$env:TEMP\gql_test_env\Scripts\gql-core.exe" --help
usage: gql-core [-h] [--version]
                {validate,ingest,query,ask,mirror,benchmark,version} ...
```

---

## 4. Packaging Sign-Off

- [x] Wheel installs with zero errors under standard pip resolution.
- [x] `Lark` grammar resource file (`grammar.lark`) is found and loaded without missing resource errors.
- [x] CLI entry point `gql-core` functions as expected.
- [x] Apache-2.0 License file is embedded in package distribution metadata.
- [x] All 5 public workflows (Textual query, PlanBuilder, Physical Executor, Ontology Inference, Temporal functions) run successfully from the installed wheel.
