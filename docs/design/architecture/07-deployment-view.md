---
created: 13.11.2026 02:25
type: architecture
status: living
tags:
  - architecture
---
# 7. Deployment view

> Living document. Where it runs. Open questions are marked **[OPEN]** inline.

## 7.1 What the user gets

bashwalker is deployed as a package on PyPI, which callers install and pin exactly
(`pip install bashwalker==X.Y.Z`), from 0.1.5 on. Earlier releases are on GitHub only;
install one from git, pinned to its full commit hash:

```
# v0.1.4
bashwalker @ git+https://github.com/getwyrd/bashwalker@57abac30f45269508425e51339b379cc6d3924cc
```

A release is published by `.github/workflows/release.yml`, run by hand from `main` after
the release PR (the version bump) has merged (CONTRIBUTING.md, "Releasing"):

| Job | What it does |
|---|---|
| `check` | Refuses unless it runs on `main`, the version is new (no `vX.Y.Z` tag, not on PyPI) and the `ci` run on the commit passed (`.github/release/preflight.py`) |
| `build` | Builds the sdist and the pure-Python wheel with hash-pinned build tools (`.github/release/requirements.txt`) |
| `test the wheel`, `test the sdist` | Installs each built file (the wheel on Python 3.11 and 3.14, the sdist on 3.14) and runs the tests against the installed package, not against `src/` |
| `attest` | Signs a Sigstore build-provenance attestation for each file (`actions/attest-build-provenance`) |
| `publish` | Waits for the maintainer's approval on the `pypi` environment, then uploads with PyPI's trusted publishing (OIDC, no stored token), which adds PEP 740 attestations |
| `release` | Publishes the GitHub release with the same files, which tags the built commit `vX.Y.Z` |

`check` also refuses unless the `pypi` environment has a required reviewer and a branch
rule: a run that names a missing environment would create it unprotected. The last two
jobs can be re-run after a failure part-way (`.github/release/release_steps.py`): `publish`
uploads only the files PyPI lacks and refuses one PyPI holds with another hash, and
`release` resumes its draft, checks every file's digest and refuses a `vX.Y.Z` tag that
points at another commit.

Each job gets only the permissions it needs; only `publish` can reach PyPI and only
`release` can write to the repository. Release tags can't be moved or deleted (the
`release tags` ruleset) and releases are immutable; `scripts/repo-settings.py` checks both,
and the `pypi` environment. A caller can check a file with
`gh attestation verify <file> --repo getwyrd/bashwalker`.

The package runs wherever its two dependencies have wheels: tree-sitter 0.26.0 (a native
extension) and tree-sitter-bash 0.25.1 (the compiled grammar). It runs inside the caller's
process and starts nothing. CI tests it on Linux.

## 7.2 Test matrix

| Job | Platform | What it runs |
|---|---|---|
| `gate` | ubuntu-latest, Python 3.14 | The test suite |
| `python-3-11` | ubuntu-latest, Python 3.11 | The test suite on the oldest supported Python |
| `differential (bash 5.1/5.2/5.3)` | ubuntu-latest, Python 3.14 | The differential test against each bash release, built from source by `scripts/build_bash.py` |

All of these are required on `main`, along with `dco`, `docs-check`, `docs-immutability`
and `require-linked-issue` (`.github/required-checks.txt`). CodeQL, Dependabot, secret
scanning and OpenSSF Scorecard run as well (SECURITY.md).

## 7.3 Development environment

A Linux machine with Python 3.11+ and `pip install -e '.[dev]'`. The differential test also
needs bash 5.1–5.3 (built by `scripts/build_bash.py`), shfmt 3.12.0 and bubblewrap, and runs
with `BASHWALKER_DIFFERENTIAL=1`. CONTRIBUTING.md has the steps.
