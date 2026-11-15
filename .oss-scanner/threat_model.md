# Threat model: bashwalker

Reviewer-facing summary of what an attacker can reach and how bad each outcome is, for
security reviewers and scanners. The full, living threat model is
[architecture §14](../docs/design/architecture/14-threat-model.md). Where this file and §14
differ about what exists in code today, this file describes the code and §14 describes the
design it is growing into. A change that adds an untrusted input or moves a trust boundary
updates both in the same PR.

## What this project does

bashwalker is a Python library with one entry point: `walk(line)` parses a bash command
line with the pinned tree-sitter-bash grammar (`src/bashwalker/core.py`) and returns a
`Walk`, one `Invocation` per simple command with its words (each marked literal or not),
assignments, redirects and stdin, plus the features that make the tree untrusted. Callers
make security decisions on these facts: nl-shell's policy gate decides whether a
model-proposed command runs, and pdca-harness's STOP guard whether an agent's `git` or
`gh` call is allowed. bashwalker itself runs nothing and decides nothing.

## Where untrusted input enters

Treat all of the following as attacker-controlled:

1. **The command line passed to `walk()`**, every byte of it. It is written by a language
   model, an agent or a person, any of whom may be trying to get a command past the
   caller's policy. It is parsed by tree-sitter-bash (third-party, native code) and then
   walked by `core.py`.

2. **An issue's title and body**, in `.github/workflows/triage-priority.yml`. Anyone can
   open an issue. The `classify` job passes the text to a language model as data with a
   read-only token; the `apply` job holds `issues: write`, runs no model, checks every label
   in the model's plan against `labels.json` and writes only labels, an assignee and one
   comment. Issue text never reaches a shell. A way to make it write anything else, or
   reach a shell or a token, is in scope.

Trusted: the pinned grammar release (changed only by a reviewed pin), the `Limits` the
caller passes, and the caller's own handling of the facts.

Already in place from the template: `.github/workflows/welcome-first-time-contributor.yml`
runs on `pull_request_target`, so it holds a token with `pull-requests: write` (its only
permission) while handling a pull request from any fork. The PR's code, title, body and
branch name are attacker-controlled. The workflow never checks the PR out and never
interpolates the event payload into its script; it reads only the author's login and the
PR number from the payload and posts a fixed comment. A change that adds an
`actions/checkout` step or a `${{ github.event` expression to that workflow is in scope.

## What must hold

- **No wrong fact looks proven.** Every simple command bash would run in the line appears
  as an `Invocation` (also inside substitutions, functions and here-doc command lines); a
  word marked `literal` is one bash does not expand; a stdin other than `unknown` is where
  bash really reads from. When the walker cannot prove a fact it reports the worst case
  (`Walk.untrusted`, a non-literal word, `unknown` stdin) or raises `ParseRefused`.
- **Grammar disagreements are flagged.** A line that tree-sitter-bash reads differently
  from bash gives a non-empty `Walk.untrusted`, never a clean tree.
- **Options that change reading are flagged.** A line that sets history expansion, POSIX
  mode, `keyword` or turns off `interactive_comments` (by `set`, `shopt` or a mode variable
  such as `POSIXLY_CORRECT`), or runs unseen code (`eval`, `source`, a trap) before another
  command, gives a non-empty `Walk.untrusted` (ADR-0010).
- **Bounded work.** Input over the size cap is refused before it is parsed; the walk has a
  node budget and a depth limit.

"bash" here means the supported releases, today bash 5.1, 5.2 and 5.3 (the ones the
differential test runs on).
- **Refusals never quote the input.**

A finding that breaks one of these is in scope even if no current caller is affected:
the facts are the contract.

## Components that matter most

In order: `untrusted_features` (Rule 1), the walk and its handlers including
`_check_walk` (Rule 2), `lex_word` and the stdin logic (`_stdin_after`,
`may_rewire_stdin`, Rule 3), descriptor and redirect handling, then `Limits` (Rule 5). All
are in `src/bashwalker/core.py`.

Lower priority: `scripts/build_bash.py` (test tooling), the GitHub workflows.

Out of scope: tree-sitter and tree-sitter-bash themselves (report a grammar bug only if
bashwalker's use of it turns it into a wrong fact that looks proven, and a memory-safety bug
only if `walk()` reaches it); policy built on the
facts by a caller; a disagreement that shows only with a bash release outside the supported
ones (5.0 until #29 adds it, or a newer release not yet added), which is a version-support
request (draft proposal 0001). Releases older than 5.0 are not supported.

## Known gaps: do not report these on their own

- The facts assume, for the whole run, history expansion, POSIX mode and `keyword` off and `interactive_comments` on in the shell that runs the line. How bash was started does not prove this; the caller makes sure by running `\builtin set +H +k +o posix; \builtin shopt -s interactive_comments` in that shell before the first line (the backslash skips an alias and `builtin` a function named `set` or `shopt`), in a shell with no function named `builtin` and where nothing outside the lines runs code between commands (no `DEBUG`, `ERR` or `RETURN` trap, no `PROMPT_COMMAND`), so nothing turns them back on. Every other option ADR-0010 does not list as harmless (such as `extglob`, a `compat` option or a `BASH_COMPAT` level) stays at bash's default, and `terminal` stdin means the stdin the caller gave that bash (architecture §3.2). A report
  that needs one of these settings changed, or that only says `terminal` may be a pipe, is a
  precondition the caller guarantees, not a broken fact. A line that changes one of these
  settings itself makes the tree untrusted from 0.1.2 (ADR-0010, GHSA-hc72-48v8-pvg7); a way
  past that rule is in scope, except through code the walker does not see that ends the line
  (any command ADR-0010 counts as unseen code: `eval`, `source`, `.`, `fc`, `trap`, `alias`, a code option such as `mapfile -C`, `complete -C`/`-F`, `bind -x`, `enable -f` or `jobs -x`, or an unreadable command word), which is the caller's when it runs several
  lines in one shell.
- Rule 1 lists the grammar disagreements found so far; the differential test checks it
  against bash, `bash -n` and shfmt by sampling generated lines, not exhaustively. A new
  disagreement that gives a wrong fact without being flagged is in scope.
- Arithmetic is trusted only when it is literal numbers (#6, #12): any name, `$` or
  backtick in an arithmetic context or array index (compound-assignment keys and `{a[i]}>`
  descriptors included), any `-i` declaration, any declared value bash may reparse as a
  compound assignment, any unquoted expansion in a `test`, any write to one
  of bash's integer variables, any declaration or destination name the walker cannot
  read, any indirect `${!name}` and any `coproc` are flagged. Arithmetic run by `eval`, `source` or a
  callback is the caller's (the walker reports those commands, not what they run); a
  hidden command reached through arithmetic in one line otherwise is in scope.
- Wrong stdin and prefix facts for `PATH=… $(true)` (#28) and `coproc` (#26), first reported as nl-shell#212. Known;
  variants beyond them are in scope.
- A `[ … ]` test gives no `Invocation`, so a `[` redefined as a function or replaced on
  `PATH` runs unseen (#30). Known; other simple commands missing from `invocations` are in
  scope.
- What a command runs later (`eval`'s argument, `source`d files, `python -c`, aliases,
  functions defined elsewhere) is not in the line. The walker reports the command, not
  what it runs.
- The pre-commit secret guard (`.pre-commit-config.yaml`: machine-local Claude Code settings,
  credential files, gitleaks) runs only in clones where it was activated (the hook reads copies of the config
  and the gitleaks policy taken from the default branch) and is skipped by `git commit --no-verify`. A way to get a secret committed past an *active*
  guard is in scope.

## How to exercise it

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/python -c 'import bashwalker; print(bashwalker.walk("cat <<E | sh\nid\nE"))'
```

## How we rate severity

- **Critical:** a command bash runs is missing from `invocations`, or a word bash expands
  is marked literal, in a tree reported as trusted.
- **High:** another wrong fact that looks proven in a trusted tree (a stdin, a redirect's
  descriptor or target, an assignment's role), or an unflagged grammar disagreement.
- **Medium:** unbounded time or memory within the limits; a refusal that quotes the input.
- **Low:** a fact reported as worst case that could have been proven.

A clean reproducer matters more than a severity label. The best form is a failing test in
the style of the existing ones.
