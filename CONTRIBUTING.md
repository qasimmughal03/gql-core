# Contributing to GQL-Core

## Reporting a bug

Open an issue with a minimal graph, the exact query or plan, the expected and actual output, your
Python version, and the stack trace if there is one. A wrong answer is the most useful kind of
report: if Neo4j or the openCypher TCK gives a different result, say which.

## Setting up

```bash
git clone https://github.com/qasimmughal03/gql-core.git
cd gql-core
python -m pip install -e ".[dev,benchmark]"
python -m pytest tests/
```

## Branches and pull requests

- `main` is the release branch. It only changes through pull requests, and CI must pass.
- Work on a branch named for the change (`fix/exists-subqueries`, `feat/typed-joins`,
  `docs/quickstart`), and open a pull request against `main`.
- Every bug fix comes with a regression test that fails without the fix. Bugs found by a
  benchmark go in `tests/test_cypherbench_regressions.py` or the matching benchmark test file.
- A change to query behaviour must not change the openCypher TCK result. Run
  `python -m benchmark.tck.runner` and compare `benchmark/results/tck_compatibility_results.json`.

## Benchmarks

Only published benchmarks (openCypher TCK, CypherBench, MetaQA, LDBC SNB), or checks against
independently computed ground truth, are reported. Do not add benchmarks scored against
hand-written expected answers.

For the natural-language evaluations, nothing in the pipeline may see a gold query or a gold
answer. Develop on the dev sample (`--seed 1 --exclude-sample-seed 0`) and run the seed-0 test
sample once. Results files record the commit, model, decoding settings and sample; commit them
together with the code that produced them.

Large datasets and model caches stay out of git and out of the package (`benchmark/cache/`,
`data/`). The harnesses download them on demand.

## Versioning and releases

- Engine or API changes get a new package version (`0.2.0a3` → `0.2.0a4` …), with an entry in
  `CHANGELOG.md` and `docs/RELEASE_NOTES_<version>.md`.
- A change only to benchmark data, prompts or harnesses does not change the package version; its
  results files carry the commit that produced them.
- The version is set in `pyproject.toml` and `gql_core/__init__.py`, and checked in
  `.github/workflows/ci.yml`.

To release, a maintainer:

1. merges the release pull request into `main`;
2. tags it: `git tag -a v0.2.0a4 -m "GQL-Core 0.2.0a4"` and `git push origin v0.2.0a4`;
3. approves the `pypi` deployment in GitHub Actions. The release workflow builds, tests and
   publishes with PyPI Trusted Publishing; no API token is stored anywhere.
