---
created: 14.11.2026 12:00
type: adr
status: Proposed
tags:
  - adr
  - parser
---
# 0006. Parse with tree-sitter-bash, pinned exactly

## Context

bashwalker has to know the structure of a bash command line without running it, inside the
caller's process, on every line the caller checks (architecture §2.1). Bash offers no way to
do that: `bash -n` only reports whether the syntax is valid and gives no tree, and anything
more means running bash. Every parser other than bash's own disagrees with bash on some
forms, so whichever is chosen, the disagreements have to be found and handled.

The options:

- **Run bash.** Bash's parser is the only one that agrees with bash by definition, but bash
  has no interface that returns a tree. Its reprint (`declare -f`) loses detail, and every
  line would cost a process.
- **Write a parser.** It would be under our control, but bash's grammar is large and
  irregular, and a new parser would start with more disagreements than a mature one.
- **shfmt's parser (mvdan/sh).** Mature, but it is a Go program, so each line would cost a
  subprocess, and it is not bash either.
- **tree-sitter-bash.** Mature and widely used, it runs in-process through the tree-sitter
  Python binding. It always returns a tree, marking what it can't parse with `ERROR` and
  `MISSING` nodes. It was written for editors, and it reads some forms differently from bash.

## Decision

We will parse with tree-sitter-bash through the tree-sitter Python binding, and pin both
exactly (`tree-sitter==0.26.0`, `tree-sitter-bash==0.25.1` at the time of writing). Every
form the grammar may read differently from bash makes the tree untrusted (Rule 1), and the
differential test compares the walker with bash and shfmt to find forms that aren't listed
yet. A pin moves only in a reviewed pull request that passes the differential test on every
supported bash version.

We reject running bash or shfmt at run time. Both stay oracles in the tests.

## Consequences

- bashwalker stays a pure-Python library with no subprocess.
- The grammar's disagreements with bash are bashwalker's main risk. Finding and listing them
  is ongoing work (threat model §14.5, §14.9).
- A grammar release can change the facts, so callers must pin bashwalker exactly, and each
  pin move is reviewed like a code change.
- One grammar serves every bash version. Syntax that only some versions accept has to be
  handled by bashwalker, not the grammar (proposal 0001).
