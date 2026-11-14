---
created: 14.11.2026 22:00
type: adr
status: Proposed
tags:
  - adr
  - security
---
# 0010. Options that change how bash reads the line make the tree untrusted

## Context

Some shell options change how bash reads or runs the commands that come after the one
setting them:
- history expansion (`set -H`, with `set -o history`) rewrites `!` on later lines before bash
  parses them;
- POSIX mode (`set -o posix`, `POSIXLY_CORRECT`) parses some forms differently: `time -p cmd`
  runs an external `time`;
- `keyword` (`set -k`) makes `a=b` anywhere in a later command an assignment, not a word;
- without `interactive_comments` an interactive shell runs the text after `#`.

The facts assume these options at their defaults (architecture §3.2). A line that sets one
of them itself made v0.1.1 report trusted facts that bash does not agree with (GHSA-hc72-48v8-pvg7).
The same change can come from code the walker does not see: `eval 'set -k'`, a sourced
file, a trap, or a command word the walker cannot read (`$c -k` with `c=set`).

## Decision

The tree is untrusted when the line:
- runs `set` or `shopt` (also through `command` or `builtin`) with an option outside a list
  of options known not to change reading, checked by direction (`set +H` is trusted,
  `set -H` is not), or with an option word the walker can't read;
- writes `POSIXLY_CORRECT`, `BASH_COMPAT`, `SHELLOPTS`, `BASHOPTS` or `histchars` in any
  way (assignment, loop variable, `${VAR:=…}`, or naming it to a builtin), with the same
  checks as for the variables bash runs as code, which now also cover `${PS4:=…}`;
- runs code the walker does not see (`eval`, `source`, `.`, `fc`, `trap`, `alias`, a code
  option such as `mapfile -C` or `enable -f`, or an unreadable command word) when another command may run
  after it: one written after it, or the same command run again by a loop or function.

We trust options from a list, not reject them from a list. An option nobody has looked at
stays untrusted.

## Consequences

- Common lines stay trusted: `set -euo pipefail`, `set -x`, `shopt -s nullglob globstar`,
  `source venv/bin/activate` as the last command, `eval "$(ssh-agent)"`.
- `shopt -s extglob`, `set -o posix` and the `compat*` options come back untrusted, as do lines
  such as `source env.sh && make` or `$cmd; ls`, where unseen code runs before another
  command. Callers confirm or block them.
- Each danger is checked in bash 5.1, 5.2 and 5.3 by the differential job
  (`MODE_PROBES` in `tests/test_differential.py`).
- Options changed outside the line (the caller's shell, a trap installed earlier) remain
  the caller's precondition (§3.2, threat model §14.9).
