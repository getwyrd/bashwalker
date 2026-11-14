---
created: 13.11.2026 02:25
type: adr
status: Proposed
tags:
  - adr
  - governance
  - licensing
---
# 0002. Apache License, Version 2.0 and DCO sign-off

## Context

bashwalker is public. Users need a clear license, and the project needs to know it may
use what contributors send, without paperwork that deters small contributions.

Its users are developers who embed it in tools that decide whether a command runs: first
nl-shell and pdca-harness, both Apache-2.0. They need a permissive license they can ship
inside their own product, with an explicit patent grant.

## Decision

bashwalker is licensed under the **Apache License, Version 2.0** (`LICENSE`).

Contribution provenance is tracked with the **Developer Certificate of Origin** (DCO, the
`DCO` file), not a Contributor License Agreement (CLA). Each commit carries a
`Signed-off-by:` line (`git commit -s`) certifying the contributor has the right to submit
it. Contributions are licensed inbound under the same license as outbound.

We choose the DCO because a CLA's friction falls on exactly the occasional contributors a
public project wants, and because the main thing a CLA adds, the right to relicense
contributions later, is a power this project chooses not to hold.

## Consequences

- No signing step for contributors; every commit needs a sign-off, and the `dco` check
  fails a pull request with an unsigned commit.
- Every contributor keeps their copyright, so the project cannot later be relicensed
  without their agreement.
- Third-party material shipped with the project keeps its own license.
