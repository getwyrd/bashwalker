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
of them makes the tree untrusted (§8.1). A walker with one handler per named node kind
visits every node exactly once and turns each simple command into an `Invocation` (Rule 2,
§8.2). Words are literal and stdin is proven only through short lists of forms (Rule 3,
§8.3). Everything else is reported as the worst case, and a walk that misses a node or runs
over its budget is refused (Rule 5, §8.4).

## 4.2 Key strategies

| Problem | Strategy | Where it is decided |
|---|---|---|
| Reading bash without writing a bash parser | Reuse tree-sitter-bash, pinned exactly | Extraction from nl-shell (#3); ADR candidate |
| The grammar disagrees with bash on some forms | Rule 1 marks those forms untrusted; the differential test hunts for new ones | §8.1, §8.5, §14.5 |
| A node the walk silently skips | Rule 2: exhaustive handlers, checked against the tree on every walk | §8.2 |
| A word that looks literal but bash expands | Rule 3: `lex_word` proves literalness only for forms it knows | §8.3 |
| Run-time values reaching arithmetic | Trust arithmetic only when it is literal numbers | #12; ADR candidate |
| Hostile input as denial of service | Rule 5: size cap before parsing, work and depth budgets | §8.4 |
| Different callers need different rules | Facts only; policy is the caller's | §1.5; ADR candidate |

## 4.3 Build strategy

bashwalker was extracted from a working policy gate rather than built from scratch:

1. Move nl-shell's shell layer into its own package with its history (#3).
2. Remove nl-shell's policy decisions so that only facts remain.
3. Harden it through review and the differential test (#7).
4. Release v0.1.0 (#8), then v0.1.1 with the arithmetic rule (#12).

Next, the callers move to it (§9). There is no implementation-arc proposal; the roadmap is
§9 and the issue tracker.
