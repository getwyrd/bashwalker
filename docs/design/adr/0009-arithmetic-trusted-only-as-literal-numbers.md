---
created: 14.11.2026 12:00
type: adr
status: Proposed
tags:
  - adr
  - security
---
# 0009. Arithmetic is trusted only when it is literal numbers

## Context

Bash evaluates text as an arithmetic expression in many places:
- `$(( ))`, `$[ ]`, `(( ))` and `for (( ))`;
- `let`, `[[ ]]` numeric tests and `${…:off:len}`;
- array indexes;
- assignments to integer variables.

When that text names a variable, bash evaluates the variable's value as arithmetic too. A
subscript in the value runs its command substitutions, so `echo $((X))` with `X='a[$(id)]'`
in the environment runs `id`. The command is in no node of the tree.

Version 0.1.0 tried to prove some names numeric from earlier assignments in the same line.
Review found many ways around those proofs, through other writers, prefixes, the integer
attribute and bash's own integer variables (#10, #12). A sound proof would need most of
bash's data flow.

## Decision

The tree is trusted only when every arithmetic context holds literal numbers and operators.
Any of the following makes it untrusted:
- a name, `$` or backtick in an arithmetic context or an array index (compound-assignment
  keys, named descriptors, and element names given to builtins or `-v` tests included);
- a `-i` declaration;
- a write to one of bash's integer variables;
- a declaration, destination or `unset` name the walker can't read;
- a declared value bash may reparse as a compound assignment;
- an indirect `${!name}`, or a `coproc`.

Words bash expands before it reads them as arithmetic (tilde, globs, braces, process
substitution, splitting) count as names. We reject proving names numeric.

## Consequences

- Common lines such as `$((RANDOM % 6))`, `${a[i]}` and `for ((i=0; i<3; i++))` come back
  untrusted, so callers confirm or block them.
- Each covered place is listed in `ARITHMETIC_SINKS` and is checked to run a hidden command
  in bash.
- Arithmetic run by `eval`, `source` or a callback, and state from earlier commands in a
  persistent shell, stay outside the line (threat model §14.8).
- Making a form precise again means a new ADR that supersedes this one, with a proof that
  covers bash's data flow for that form.
