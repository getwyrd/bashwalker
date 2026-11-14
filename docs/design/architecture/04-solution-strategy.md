---
created: 13.11.2026 02:25
type: architecture
status: living
tags:
  - architecture
---
# 4. Solution strategy

> Living document. The shape of the solution and why. Open questions are marked **[OPEN]** inline.

## 4.1 The shape in one paragraph

`walk()` checks the line's size, then parses it with the pinned tree-sitter-bash grammar.
Rule 1 lists every feature where the grammar may read the line differently from bash; any
of them makes the tree untrusted (§8.1). A walker with a handler for every named node kind
visits every named node exactly once and turns each simple command into an `Invocation`
(Rule 2, §8.2). Words are literal and stdin is proven only through short lists of forms
(Rule 3, §8.3). Everything else is reported as the worst case, and a walk that misses a node
or runs over its budget is refused (Rule 5, §8.4).

## 4.2 Key strategies

| Problem | Strategy | Decision |
|---|---|---|
| Reading bash's structure without running bash | Parse with tree-sitter-bash, pinned exactly; bash and shfmt only as test oracles | ADR-0006 |
| Different callers need different rules | Report facts only; policy belongs to the caller | ADR-0007 |
| Facts that can't be proven | Report them as the worst case, never a guess | ADR-0008 |
| Run-time values reaching arithmetic | Trust arithmetic only when it is literal numbers | ADR-0009 |
| The grammar disagrees with bash on some forms | Rule 1 marks those forms untrusted; the differential test hunts for new ones | ADR-0006, §8.1, §8.5 |
| A node the walk silently skips | Rule 2: a handler for every node kind, checked against the tree on every walk | ADR-0008, §8.2 |
| Hostile input as denial of service | Rule 5: size cap before parsing, work and depth budgets | §8.4 |
| Lines that mean different things in different bash versions | **[OPEN]** Facts that hold for every bash version the caller names | Draft proposal 0001 |

All four ADRs are Proposed.

## 4.3 Build strategy

The walker was taken from an existing policy gate with its history, rather than written from
scratch:

1. Take the gate's shell layer out as its own package, keeping only facts (ADR-0007).
2. Harden it through review and the differential test.
3. Release v0.1.0, then v0.1.1 with the arithmetic rule (ADR-0009).

Next come PyPI publishing (§7) and bash version support (proposal 0001). §9 has the order.
