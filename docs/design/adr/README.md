---
created: 13.11.2026 02:25
type: index
tags:
  - adr
---
# Architecture Decision Records

Numbered, immutable records of significant decisions and *why* they were made. An ADR is
never edited after acceptance; a later ADR supersedes it (ADR-0004). This index is the
authoritative record of each ADR's current status. Format: the lightweight Nygard template
(ADR-0001); start from `../templates/adr.md`.

**What deserves an ADR:** a decision that later work depends on and that would be expensive
to reverse: a language or core dependency, a data format, a trust boundary, a process rule.
Not every choice does; if reversing it touches one file, it doesn't need an ADR.
Example: wyrd's [ADR index](https://github.com/getwyrd/wyrd/blob/main/docs/design/adr/README.md).

## How an ADR is made

The rules are in ADR-0001 (lifecycle), ADR-0004 (supersession) and
[GOVERNANCE.md](../../governance/GOVERNANCE.md) (who accepts). In order:

1. **Open an issue** that states the question. Every pull request needs one, and the
   discussion before there is a draft belongs there.
2. **Take the next number.** One more than the highest number in the index and in any open
   pull request that adds an ADR. Numbers are never reused, not even for an ADR that was
   dropped.
3. **Write it from the template.** Copy [`../templates/adr.md`](../templates/adr.md) to
   `NNNN-short-title.md`, keep `status: Proposed` with nothing after it on that line, and
   write Context, Decision and Consequences. Mark anything still undecided **[OPEN]**.
4. **Add it to the index** below, with status `Proposed`, in the same pull request.
5. **Open the pull request** with `Refs #N` for the issue. Discussion happens there; a
   Proposed ADR may be edited freely, before and after it merges.
6. **Accept it.** When the architecture board (GOVERNANCE.md) agrees and no **[OPEN]**
   items are left, change `status:` to `Accepted` and the index row to match, then merge.
   This edit is the act of acceptance; only a maintainer makes it, never an agent. From
   here the file is frozen (`docs-immutability`).
7. **Change it later only by superseding it** (ADR-0004): a new ADR with
   `supersedes: NNNN`, the old file's `status:` changed to `Superseded` (optionally with
   `superseded-by:`) and nothing else, and the old index row changed to
   `Superseded by NNNN`, all in one pull request.

ADR-0001 has no Rejected status: if the board does not agree, close the pull request
without merging it.

`docs-check` keeps this index honest: every ADR is listed once, its status here matches its
frontmatter, and both sides of every supersession agree. Run
`python3 -I .github/docs-check/adr_index.py` before pushing.

## Index

| # | Title | Status |
|---|-------|--------|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted |
| [0002](0002-license-and-dco.md) | Apache License, Version 2.0 and DCO sign-off | Proposed |
| [0003](0003-proposal-and-spec-process.md) | Proposal and specification process, lifecycle, and immutability | Accepted |
| [0004](0004-supersession.md) | How a frozen document is superseded | Accepted |
| [0005](0005-issue-priority-and-automated-triage.md) | Issue priority: severity and reach set P0–P3, applied by hand or by a bot | Proposed |
| [0006](0006-parse-with-pinned-tree-sitter-bash.md) | Parse with tree-sitter-bash, pinned exactly | Proposed |
| [0007](0007-facts-only-no-policy.md) | Report facts only; policy belongs to the caller | Proposed |
| [0008](0008-unproven-means-worst-case.md) | A fact not proven is reported as the worst case | Proposed |
| [0009](0009-arithmetic-trusted-only-as-literal-numbers.md) | Arithmetic is trusted only when it is literal numbers | Proposed |

## ADR candidates

None at the moment: the decisions that were settled elsewhere are now ADR-0006 to ADR-0009.
Support for several bash versions is draft proposal 0001.

| Candidate | Where it is decided now | Why it will need an ADR |
|-----------|-------------------------|-------------------------|

## Why not ...?

- **Why not ask bash itself?** bashwalker runs in the caller's process on every line, with
  no subprocess (architecture §2.1). `bash -n` checks syntax but gives no tree. bash is the
  oracle in the differential test instead (ADR-0006).
- **Why not return allowed or blocked?** Callers need different rules from the same facts
  (ADR-0007).
- **Why not prove a variable numeric from an earlier assignment?** That was v0.1.0's
  approach, and review kept finding ways around it (ADR-0009).
- **Why not a version range for tree-sitter-bash?** A grammar release changes the facts;
  only a reviewed pin change may do that (ADR-0006).
