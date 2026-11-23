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
- `dist/gql_core-0.2.0a3-py3-none-any.whl`
- `dist/gql_core-0.2.0a3.tar.gz`

## Installed-package smoke test

Run from **outside** the repository so that a local checkout cannot mask missing files.

```bash
python -m venv /tmp/gql-core-wheel-test
/tmp/gql-core-wheel-test/bin/python -m pip install dist/gql_core-0.2.0a3-py3-none-any.whl
cd /tmp
/tmp/gql-core-wheel-test/bin/python -c "import gql_core; print(gql_core.__version__, gql_core.__file__)"
/tmp/gql-core-wheel-test/bin/gql-core --version
```

On Windows PowerShell, use `$env:TEMP` and `Scripts/python.exe` / `Scripts/gql-core.exe` instead of the Unix paths.

For tests of the actual installed wheel, use an isolated checkout-free smoke script and verify that `gql_core.__file__` comes from `site-packages`.

## Benchmarks

`python -m benchmark.tck.runner` requires the separately pinned openCypher TCK fixture tree.

`python -m benchmark.snb.runner` requires the separately downloaded LDBC SNB data and optional benchmark dependencies. The LDBC study is **unaudited** and tests a small subset of official operations; do not present its numbers as a complete LDBC result.

See `docs/SUPPORTED_QUERY_CONTRACT.md`, `docs/RELEASE_CORRECTNESS_REPORT.md`, and `docs/LDBC_QUERY_COVERAGE.md` for methodology and limits.

## What the package contains

The wheel contains only `gql_core` (CI checks this). The benchmark harnesses, the legacy
top-level modules (`query/`, `graph/`, `ingestion/`), examples, tests, datasets and model caches
stay in the repository. 0.2.0a1 also installed top-level `benchmark`, `query`, `graph` and
`ingestion` packages; 0.2.0a3 no longer does.

## Release process

Releases are built and published by `.github/workflows/release.yml` when a `v*` tag is pushed.

1. Merge the release pull request into `main`. It bumps the version in `pyproject.toml` and
   `gql_core/__init__.py`, and adds `docs/RELEASE_NOTES_<version>.md` and a `CHANGELOG.md` entry.
2. Tag the merge commit and push the tag:
   `git tag -a v0.2.0a4 -m "GQL-Core 0.2.0a4"` then `git push origin v0.2.0a4`.
3. The workflow runs the full CI (tests on 3.11–3.13, the TCK gate, the isolated wheel check),
   checks that the tag, `pyproject.toml`, `__init__`, release notes and changelog agree, builds
   the distributions and records their SHA-256.
4. The `pypi` job waits for a maintainer to approve it, then publishes with Trusted Publishing.
5. A GitHub release is created with the release notes, the distributions and `SHA256SUMS`.

A manual run of the workflow (Actions → Release → Run workflow) publishes to TestPyPI instead.

### Trusted Publishing: one-time setup

No PyPI token is stored in GitHub. Instead, PyPI trusts this repository's release workflow:

1. On PyPI, open *gql-core → Manage → Publishing* and add a GitHub publisher: owner
   `qasimmughal03`, repository `gql-core`, workflow `release.yml`,
   environment `pypi`. Do the same on TestPyPI with environment `testpypi`.
2. On GitHub, open *Settings → Environments*, create `pypi` and `testpypi`, add yourself as a
   required reviewer, and limit deployments to tags matching `v*`.
3. Delete any PyPI API tokens that are no longer needed.

### Verifying a published release

```bash
python -m pip download gql-core==0.2.0a3 --no-deps -d check/
sha256sum check/*        # compare with SHA256SUMS on the GitHub release and the hashes on PyPI
```

0.2.0a1 was verified this way: the wheel and sdist on PyPI have SHA-256
`71eb9ca2…f29b` and `79c625a1…814a`, and the wheel's files are identical, apart from line endings,
to a build of tag `v0.2.0a1` (`4f1283c`).

The Apache-2.0 license and third-party attribution should be reviewed before publication.
