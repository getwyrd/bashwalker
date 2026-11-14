---
created: 13.11.2026 02:25
type: architecture
status: living
tags:
  - architecture
---
# 2. Constraints

> Living document. What the design must work within; the decisions that follow from these are the ADRs. Open questions are marked **[OPEN]** inline.

## 2.1 Technical constraints

- **Python 3.11 or newer,** so that tools on older supported Pythons can embed it. CI runs
  the suite on 3.11 and 3.14 (`python-3-11`, `gate`).
- **tree-sitter 0.26.0 and tree-sitter-bash 0.25.1, pinned exactly** (`pyproject.toml`).
  Every fact depends on how this grammar reads bash, so a new grammar release changes
  bashwalker's behaviour. It reaches users only through a reviewed pin change, and callers
  pin bashwalker exactly for the same reason.
- **bash versions.** The facts describe what bash 5.1 to 5.3 does with the line, and the
  differential test compares against those three releases (§8.5). Other versions behave
  differently (§1.4); supporting them is draft proposal 0001.
- **In-process and synchronous.** `walk()` runs inside the caller on every command line it
  checks, so it must be fast and must not start processes, read files or use the network.

## 2.2 Organizational constraints

- **One maintainer** under GOVERNANCE.md's bootstrap rules.
- **Apache License 2.0 with DCO sign-off** (ADR-0002, Proposed). The `dco` check fails a
  pull request with an unsigned commit.
- **Public repository** in the getwyrd organisation; releases go to PyPI (§7, #25).
- **Callers live in other projects.** A change to the facts or the API reaches a caller only
  when it moves its exact pin. Until the API is marked stable (SECURITY.md), a change may
  break callers, so each release says what changed for them.

## 2.3 Conventions

- Design documents live in `docs/design/`: this architecture (arc42), decision records
  (ADR-0001), and proposals and specifications (ADR-0003, ADR-0004). The `docs-check` and
  `docs-immutability` checks enforce their format and that frozen documents stay frozen.
- **A security-relevant change updates the threat model in the same pull request:** both
  §14 and `.oss-scanner/threat_model.md` (AGENTS.md).
- Every pull request links an issue (`require-linked-issue`). Every check in
  `.github/required-checks.txt` must pass before a merge.
- A form becomes proven only with a test. A form found in bash that the walker gets wrong
  becomes a test before the fix (`tests/test_core.py`).
