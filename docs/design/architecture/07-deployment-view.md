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

bashwalker is deployed as a package on PyPI, which callers install and pin exactly:

```
pip install bashwalker==X.Y.Z
```

Each release tag builds an sdist and a pure-Python wheel and publishes them with PyPI's
trusted publishing (OIDC, no stored token). Until the first PyPI release (#25), callers
install from the git tag (`bashwalker @ git+https://github.com/getwyrd/bashwalker@v0.1.1`).

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
