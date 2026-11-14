---
created: 14.11.2026 12:00
type: adr
status: Proposed
tags:
  - adr
  - security
---
# 0008. A fact not proven is reported as the worst case

## Context

Callers decide whether a command runs based on bashwalker's facts (ADR-0007). A fact that
looks proven but is wrong lets a caller allow what it would have blocked. Bash has many
expansions, many forms the grammar misreads (ADR-0006) and much run-time state, so
bashwalker can't prove everything about every line. When it can't, it has to choose between
guessing the likely meaning and reporting what is unknown.

## Decision

Every fact starts as not proven. It becomes proven only through a short list of forms, each
with a test showing that it holds for bash. Anything else is reported as the worst case:

- a word is not literal;
- stdin is `unknown`;
- the tree is untrusted, with a reason in `Walk.untrusted`;
- or the walk raises `ParseRefused` when it can't be completed or exceeds a limit.

bashwalker will not guess. A caller MUST treat each worst-case fact as the worst case for
its own rules.

## Consequences

- Soundness wins over precision (architecture §1.6). Safe lines sometimes come back untrusted,
  which costs a caller a confirmation or a block. That is a precision bug, not a security bug
  (SECURITY.md).
- Making a form proven is a deliberate change with a test. It can't happen as a side effect.
- A wrong fact that looks proven is the most serious bug class (threat model §14.4), and the
  issue priority scheme rates it highest (ADR-0005).
