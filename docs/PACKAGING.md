# Packaging and distribution

GQL-Core is an **experimental** Python package (`0.2.0a1`). Packaging correctness is independent of the project's query-language compatibility score.

## Local development

```bash
python -m pip install -e ".[dev,benchmark]"
python examples/quickstart.py
python -m pytest tests/
```

The full pytest suite includes tests that read the external openCypher TCK corpus at `benchmark/cache/openCypher/tck/features`. Populate it before running those tests:

```bash
git clone --depth 1 --branch 2024.3 https://github.com/opencypher/openCypher.git benchmark/cache/openCypher
cd benchmark/cache/openCypher
git sparse-checkout init --cone
git sparse-checkout set tck/features
cd ../../..
```

For an exact reproducible corpus pin, consult `docs/RELEASE_CORRECTNESS_REPORT.md` and check out its recorded upstream commit. The upstream corpus is excluded from wheel and sdist.

## Build and metadata check

```bash
python -m pip install -U build twine
python -m build
python -m twine check dist/*
```

Expected filenames:
- `dist/gql_core-0.2.0a1-py3-none-any.whl`
- `dist/gql_core-0.2.0a1.tar.gz`

## Installed-package smoke test

Run from **outside** the repository so that a local checkout cannot mask missing files.

```bash
python -m venv /tmp/gql-core-wheel-test
/tmp/gql-core-wheel-test/bin/python -m pip install dist/gql_core-0.2.0a1-py3-none-any.whl
cd /tmp
/tmp/gql-core-wheel-test/bin/python -c "import gql_core; print(gql_core.__version__, gql_core.__file__)"
/tmp/gql-core-wheel-test/bin/gql-core --version
```

On Windows PowerShell, use `$env:TEMP` and `Scriptspython.exe` / `Scriptsgql-core.exe` instead of the Unix paths.

For tests of the actual installed wheel, use an isolated checkout-free smoke script and verify that `gql_core.__file__` comes from `site-packages`.

## Benchmarks

`python -m benchmark.tck.runner` requires the separately pinned openCypher TCK fixture tree.

`python -m benchmark.snb.runner` requires the separately downloaded LDBC SNB data and optional benchmark dependencies. The LDBC study is **unaudited** and tests a small subset of official operations; do not present its numbers as a complete LDBC result.

See `docs/SUPPORTED_QUERY_CONTRACT.md`, `docs/RELEASE_CORRECTNESS_REPORT.md`, and `docs/LDBC_QUERY_COVERAGE.md` for methodology and limits.

## Release process

1. Finalize and review source changes and documentation.
2. Confirm `__version__` matches `pyproject.toml`.
3. Re-run CI on a clean clone, with upstream fixtures available to the test jobs.
4. Build wheel and sdist from the exact release commit and check metadata.
5. Inspect artifacts and verify installed API/CLI without source-path fallback.
6. Upload to TestPyPI only when authorized; test `pip install` from TestPyPI.
7. Publish to PyPI or create a GitHub release **only with explicit approval**.

A package existing on GitHub does not imply an available PyPI release. The Apache-2.0 license and third-party attribution should be reviewed before publication.
