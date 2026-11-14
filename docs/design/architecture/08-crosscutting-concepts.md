---
created: 13.11.2026 02:25
type: architecture
status: living
tags:
  - architecture
---
# 8. Cross-cutting concepts

> Living document. The core ideas the rest of the design is built on. Terms are also in the glossary (section 12). Open questions are marked **[OPEN]** inline.

One principle runs through all of them: **nothing is proven until it is proven.** Each fact
starts as the worst case and becomes proven only through a short list of forms that tests
cover. A form that isn't on a list stays the worst case. That keeps the walker sound
(goal 1) at the cost of some precision (goal 3) (ADR-0008). The rules keep the numbers of
the policy specification the walker was first written for. Rule 4 there decides which
redirects are safe; that is policy, so it belongs to callers (ADR-0007), and bashwalker only
records the redirect facts it needs.

## 8.1 Rule 1: trusting the tree

tree-sitter-bash is a grammar for editors, not a reimplementation of bash, and it reads some
forms differently. Each such form found adds a reason to `Walk.untrusted`, and one reason
is enough to make the whole tree untrusted. The reasons come from two places:

- `untrusted_features()` checks the parse itself: `ERROR` and `MISSING` nodes, extglob,
  backslash-newline, unusual here-docs, backtick forms the grammar merges, words read across
  whitespace, and the other parser-level forms in §14.5.
- `walk()` adds the reasons that need the whole walk: arithmetic (below), a variable bash
  runs as code (`PS4`, `PROMPT_COMMAND`, …), assigned text holding a substitution, words
  after a redirect with no command to take them, and the forms the walker meets while
  visiting (a declaration or `unset` operand with a subscript).

So `untrusted_features()` alone is not a full trust verdict (§3.2).

Arithmetic is part of Rule 1. Bash evaluates a variable's run-time value as an arithmetic
expression in many places, and a subscript in that value runs its command substitutions, so
`$((X))` with `X='a[$(id)]'` runs `id`. Since #12, arithmetic is trusted only when it is
literal numbers. Any of these makes the tree untrusted:
- a name, `$` or backtick in an arithmetic context or an array index;
- a `-i` declaration or a write to one of bash's integer variables;
- a value bash may reparse as a compound assignment;
- an indirect `${!name}`, or a `coproc`.

## 8.2 Rule 2: no node skipped

The `Walker` has a handler for every named node kind in the pinned grammar (`HANDLERS`):
a specific one where the kind matters, otherwise one that walks the node's children.
After each walk, `_check_walk()` confirms two things:
- every named node was visited exactly once;
- every `command`, `declaration_command` and `unset_command` produced exactly one
  `Invocation`.

A miss raises `ParseRefused`. Tests remove each handler in turn and check that the walk
refuses. A node kind that a grammar update adds is walked through its children at run time.
The test suite fails until its corpus has a line with that kind
(`test_rule2_removed_handler_is_refused`), so a pin move can't add one unreviewed.

## 8.3 Rule 3: literal words and proven stdin

`lex_word()` removes quotes as bash does. It marks a word literal only when bash would expand
nothing in it: no `$`, backtick, glob, brace, tilde, `$'…'` or `$"…"`. The decoded text is
what bash would see.

Stdin is one of four kinds:
- `terminal`;
- `pipe`;
- `literal`, for the command's own here-doc or here-string, when nothing may read it first;
- `unknown`.

There is no file kind: a path can name any descriptor at run time, so `<path` gives
`unknown`, and its redirect stays in `redirects` for the caller.

## 8.4 Rule 5: bounded work

`Limits` sets three bounds: `max_input_bytes` (8 KiB), `max_work` (4096 nodes) and
`max_depth` (100 levels). tree-sitter-bash's parse time grows with the square of the input,
so the size cap is checked before encoding and again before parsing. Callers can pass their
own limits.

## 8.5 The differential test

Rule 1's list is checked by sampling, not proven complete. `tests/test_differential.py`
generates command lines and compares the walker with three oracles:
- `bash -n`;
- shfmt's syntax tree;
- bash's own reprint of the line as a function body, run in bubblewrap with markers that
  catch a line that escapes the wrapper.

For each line bash accepts and the walker trusts, every simple command an oracle sees must
be among the walker's invocations, and every word the walker calls literal must match. One
exception is built into the comparison: a `[ … ]` test is a `test_command` node that gives
no invocation, so oracle commands headed by `[` are not compared. Other accepted differences
are listed with a reason in `tests/differential/known.toml`. CI runs
it on bash 5.1, 5.2 and 5.3.

## 8.6 Policy stays with the caller

bashwalker reports facts and the worst case; it never says "allowed" or "blocked". Callers
differ: an interactive shell may confirm anything that changes the system, and an agent's
guard may block only pushes to protected branches. The same facts serve both (ADR-0007). The helpers `command_head()` and
`may_rewire_stdin()` are facts too: what runs, and whether it can change the shell's own
stdin.

## 8.7 Errors never quote the input

`ParseRefused` carries fixed text only. The input may hold secrets or terminal control
characters, and a caller logs or prints the refusal.

## 8.8 Security

The threat model is [§14](14-threat-model.md), with a scanner-facing copy in
[`.oss-scanner/threat_model.md`](../../../.oss-scanner/threat_model.md). Update both in the
same pull request when a change touches any of these:
- a rule or a proven form;
- the facts or their meaning;
- the limits;
- the pins;
- a workflow's permissions.

A form found that the grammar misreads becomes a test and an entry in §14.5.
