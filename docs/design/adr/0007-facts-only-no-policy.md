---
created: 14.11.2026 12:00
type: adr
status: Proposed
tags:
  - adr
  - api
---
# 0007. Report facts only; policy belongs to the caller

## Context

Tools that check a bash command line before it runs want different things from it. For
example, an interactive shell may ask for confirmation before anything that changes the
system, and an agent's guard may block only a push to a protected branch. Both need the
same knowledge about the line: its simple commands, their words, redirects, assignments and
stdin. A library that decided "allowed" or "blocked" would have to carry every caller's rules,
or force one set on all of them.

## Decision

bashwalker will report facts about a command line and never a verdict. It has no allow, deny
or risk API. A helper such as `command_head()` or `may_rewire_stdin()` is allowed only if it
states a fact about bash, not a judgement. Which commands, redirects or targets are
acceptable is decided by the caller.

## Consequences

- Each caller writes its own policy and must handle the worst case (ADR-0008) correctly.
  The architecture documents (§6, §8) show how.
- The facts are the API. Adding a fact is a feature; changing what a fact means is a breaking
  change for every caller.
- Rules that are policy (such as which redirects are safe) stay out of bashwalker, even when
  every caller needs them.
