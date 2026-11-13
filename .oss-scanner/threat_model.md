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
- **Bounded work.** Input over the size cap is refused before it is parsed; the walk has a
  node budget and a depth limit.
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
bashwalker's use of it turns it into a wrong fact that looks proven); policy built on the
facts by a caller.

## Known gaps: do not report these on their own

- Rule 1 lists the grammar disagreements found so far; the differential oracle test that
  would find the rest is not here yet (nl-shell#191, moving here). A new disagreement that
  gives a wrong fact without being flagged is still in scope.
- Arithmetic evaluation of a variable whose value comes from run time (the environment,
  `read`, a command's output) runs commands the walk never reports: #6. A value written as
  text in the line, also in pieces (`x='a[$'; x+='(id)0]'`), is flagged; a hidden command reached another way is in scope.
- Wrong stdin and prefix facts for `PATH=… $(true)` and `coproc` (nl-shell#212). Known;
  variants beyond them are in scope.
- What a command runs later (`eval`'s argument, `source`d files, `python -c`, aliases,
  functions defined elsewhere) is not in the line. The walker reports the command, not
  what it runs.

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
