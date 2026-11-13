---
created: 13.11.2026 02:25
type: architecture
status: living
tags:
  - architecture
  - security
  - threat-model
---
# 14. Threat model

> Living document. What is worth attacking, where the trust boundaries are, who the
> adversaries are, and which attacks bashwalker must withstand, each mapped to what
> mitigates it and the test that checks it. Open questions are marked **[OPEN]** inline.

## 14.1 Assets

- **The integrity of the facts.** A caller allows or blocks a command on what `walk()`
  reports: which simple commands there are, their words, whether each word is literal,
  their assignments, redirects and stdin. A wrong fact that looks proven (a hidden
  command, a word marked literal that bash expands, a stdin reported as a literal feed
  that the command does not read in full) lets the caller's policy pass a command it would have blocked.
  For nl-shell that is a command run without confirmation; for pdca-harness's STOP guard
  a push to a protected branch.
- **The caller's availability.** `walk()` runs inside the caller's process on every
  command line, so its time and memory on hostile input must stay bounded.
- **The caller's logs.** A refusal's message must never carry the input, which may hold
  secrets or terminal control characters.

## 14.2 Trust boundaries

- **The command line passed to `walk()`.** Every byte of it is attacker-controlled: the
  line comes from a language model's proposal (nl-shell), an agent's tool call
  (pdca-harness's STOP guard) or a person typing. bashwalker parses it with the pinned
  tree-sitter-bash, a third-party grammar compiled to native code, and hands the resulting
  `Walk` to the caller as facts. The caller makes a security decision on those facts (run,
  confirm, block), so the boundary is between the untrusted line and the facts: a fact
  the walker reports as proven must hold for bash. Whatever the walker cannot prove it
  reports as the worst case (an untrusted tree, a non-literal word, `unknown` stdin) or
  refuses (`ParseRefused`), and a caller MUST treat each of those as the worst case for
  its own rules. bashwalker makes no policy decision itself.
- **Pull requests from forks, in GitHub Actions.** A PR's code, title, body and branch name
  are attacker-controlled: anyone can open one. The checks run on `pull_request`, where the
  token is read-only and `actions/checkout` keeps no credentials, so PR-supplied code runs
  without write access. One workflow, `welcome-first-time-contributor.yml`, runs on
  `pull_request_target` instead, because a fork PR's `pull_request` token cannot comment;
  it holds `pull-requests: write` (its only permission) while handling a PR from anyone.
  That boundary holds only while the workflow neither checks the PR out nor interpolates
  the event payload into its script. It reads the author's login and the PR number through
  `context.payload` at run time and posts a fixed comment. The template checks both rules
  before the workflow ships (`test_pull_request_target_never_touches_pr_content` in its
  `template-test`): no `actions/checkout` step and no `${{ github.event` expression in a
  `pull_request_target` workflow. That test is not copied into this project, so a change
  to the workflow is reviewed by hand against the same two rules.

## 14.3 Adversaries

- **A model or agent that writes the command line**, whether confused or steered by a
  prompt injection. It can write any bytes, retry freely, and learn which forms a policy
  lets through, so it will find a form tree-sitter-bash reads differently from bash if
  one exists.
- **A person typing a command** who wants a form past the caller's policy (for nl-shell,
  past the confirmation). Same capabilities, fewer attempts.
- **A compromised or buggy grammar release.** tree-sitter and tree-sitter-bash are pinned
  exactly, so a new release reaches bashwalker only through a reviewed pin change.

## 14.4 STRIDE, per boundary

For the command-line boundary:

- **Tampering / elevation of privilege:** a line that tree-sitter-bash parses differently
  from bash, so a fact reported as proven is wrong and the caller's policy allows what it
  should block. The main threat; §14.5 lists the forms.
- **Denial of service:** a line that makes the parse or the walk slow or deep
  (tree-sitter-bash's parse time grows with the square of the input).
- **Information disclosure:** a refusal message that quotes the input into the caller's
  log or terminal.

For the GitHub Actions boundary, see the bullet in §14.2.

## 14.5 Attack catalog

| Attack | Mitigation |
|---|---|
| A form the grammar reads differently from bash: a syntax error or `MISSING` node, extglob, backslash-newline, a here-doc delimiter that is not a plain or fully quoted word, `<<-`, two here-docs on one line, bash 5.3 `${ }`, `<`/`>` inside `[ ]`, an escaped backtick inside a backtick substitution, a backtick in an unquoted here-doc body, a quoted declaration operand with a subscript other than a number (`declare -a 'x[$(id)]=1'`, also after a redirect target), an `unset` operand with such a subscript (`unset 'a[$(id)0]'`), any quoted or escaped text (`$'…'` decoded as bash does, `$"…"` read as in the C locale, low byte of octal escapes and cut at NUL, a subscript's index taken whole) holding a subscript with `$(`, a backtick or `${`, which bash may evaluate later, a `${…@P}` prompt expansion, which runs the value's substitutions, quoted text in `$(( ))`, `(( ))` or `for (( ))` that decodes to a substitution, which bash expands again, or setting a variable bash runs as code (`PS0`–`PS4`, `PROMPT_COMMAND`, `BASH_ENV`, `ENV`, `MAILPATH`, `FCEDIT`, `BASH_ALIASES`, `BASH_CMDS`), by assignment, as a loop variable or by naming it to a builtin (`PS4='$(id)'; set -x; :`, `for PS4 in …`, `read PS4`, `read -aPS4`), or assigning quoted text holding a `$` or a backtick, which bash may evaluate once pieces are joined (`x='a[$'; x+='(id)0]'; : $((x))`; harmless `x='$5'` is flagged too), a `command`/`builtin` prefix with an option the walker cannot read, an alias definition, which changes how bash reads later lines, or `hash -p`, which changes what a command name runs, or creating a nameref, which may alias one (`declare -n r=PS4`) (`printf -v`, `read`, `test -v`, `[[ -v ]]`, `let`, `local`, `declare -n`, `${!v}`, `$((v))`; harmless text such as `echo 'a[$(x)]'` is flagged too) | Rule 1: `untrusted_features` names it, `Walk.untrusted` is non-empty and every stdin is `unknown`; the caller treats the tree as untrusted |
| A node or simple command the walk skips, so a command is never reported | Rule 2: one handler per named node kind of the pinned grammar; every walk checks that each named node was visited exactly once and each simple command gave one invocation, else `ParseRefused` |
| A word that looks literal but bash expands (`$x`, backticks, globs, braces, `~`, `$'…'`, `a=~/b`) | Rule 3: `lex_word` marks a word literal only with none of these, as bash quote-removes it |
| A stdin that looks proven but is a pipe, the terminal or other bytes (`<path` through a symlink or `/dev/fd` to the pipe, function bodies, `exec <x` elsewhere, `eval`, `trap`, a dynamic command word, a literal feed that another command or a substitution may read part of first: a compound command's commands, a substitution in a later redirect, a redirect the grammar hangs under a here-doc; a substitution in a function's redirect, which runs at call time; a substitution in a redirect, which reads what earlier redirects set; a word after a redirect target, which is expanded before any redirect) | Rule 3: stdin is proven only as `terminal`, `pipe`, or `literal` for the simple command's own here-doc or here-string with nothing that may read it first; every `<path` is `unknown` (its redirect stays in `Invocation.redirects` for a caller that resolves the path at run time); a command run with `&` has `unknown` stdin unless its own redirects set one, and so has one whose redirects move fd 0 away (`3<&0-`); `may_rewire_stdin` (also true for `fc`, which re-runs history lines, `alias`, and for `mapfile -C`, `complete -C`/`-F`, `bind -x`, which run code from an option) makes every command's stdin `unknown`, its own included |
| A token taken for a redirect descriptor, so an argument disappears (`rm {a,b}>x`, `rm ١>x`, `rm 0&>x`) | Only ASCII digits and `{name}` / `{name[subscript]}`, as in bash, are descriptors, and `&>` / `&>>` take none |
| A word written after a redirect target, which the grammar files under the redirect, so it disappears from the command (`git push origin >/dev/null HEAD:main`) | The first word after the operator is the target and every later one goes back to the command's words, in source order; with no simple command to take them the tree is untrusted |
| A declaration hidden behind a prefix or quoting, so its assignment is not reported (`command export 'PATH=/x'`, `builtin readonly 'X=y'`, `"export" 'PATH=/x'`) | `command`/`builtin` prefixes and quoting of the command name are looked through (`command -v`/`-V` only looks up, so it gives no head; `declare -p`/`-f`/`-F` only display, so they record no assignment, options ending at `--` or the first operand); `declare`, `typeset`, `local`, `export`, `readonly` and `unset` behind them get the same checks and facts as without |
| A huge or deeply nested line | Rule 5: `Limits` (8 KiB checked before encoding and parsing, a 4096-node work budget, 100 levels), else `ParseRefused` |
| Input echoed through an error | `ParseRefused` messages are fixed text |

## 14.6 Abuse-case tests

In `tests/test_core.py`: every Rule 1 form (`test_rule1_*`); removing any one handler or
skipping a node's children must refuse the walk, for every node kind in the pinned
grammar (`test_rule2_removed_handler_is_refused`, `test_rule2_skipped_children_are_refused`);
inputs at and over the size cap, deep nesting and long chains (`test_rule5_*`); and
inputs that hold control characters in refused lines (`test_refusals_never_quote_the_input`).

## 14.7 Threat → test map

| Threat | Mitigation | Test |
|---|---|---|
| Grammar disagreement hides a form | Rule 1 | `test_rule1_names_each_feature`, `test_rule1_quoted_text_is_trusted`, `test_rule1_untrusted_tree_proves_no_stdin` |
| A command the walk never reports | Rule 2 | `test_rule2_one_invocation_per_simple_command`, `test_rule2_every_kind_has_a_handler`, `test_rule2_removed_handler_is_refused`, `test_rule2_skipped_children_are_refused`, `test_walk_reaches_every_simple_command` |
| A non-literal word reported literal | Rule 3 | `test_rule3_literal_flag`, `test_declaration_operands` |
| A wrong stdin fact | Rule 3 | `test_rule3_stdin_sources`, `test_rule3_file_stdin_names_its_redirect`, `test_unreadable_targets_are_marked`, `test_command_head_and_stdin_rewiring` |
| A word lost to a descriptor | descriptor syntax | `test_words_next_to_redirects_are_kept` |
| A word lost under a redirect | operands after the target | `test_words_after_a_redirect_target_stay_operands` |
| A prefixed declaration | prefix look-through | `test_declarations_behind_command_and_builtin` |
| Wrong redirect facts | redirect facts | `test_redirect_facts` |
| Slow or deep input | Rule 5 | `test_rule5_inputs_at_the_cap_are_walked`, `test_rule5_over_cap_is_never_parsed`, `test_rule5_work_and_depth_budgets`, `test_rule5_limits_are_the_callers` |
| Input in a refusal | fixed messages | `test_refusals_never_quote_the_input` |

## 14.8 Residual and accepted risks

- **What a line runs later is not in the line.** A script file, `python -c '…'`, `eval`'s
  argument, an alias, or a function defined outside the line: the walker reports the
  command (`eval`, `source`, `.` and `trap` are listed in `SHELL_RUNNERS` and
  `CODE_LATER`) but not what it will run. A caller that must know treats these commands
  as opaque.
- **tree-sitter itself.** A memory-safety bug in tree-sitter or the compiled grammar is
  out of this project's reach; the exact pin limits exposure to reviewed releases.
- **Run-time state.** The walker sees text, not the shell it will run in: the cwd,
  `HOME`, the current branch, defined functions and aliases are the caller's to check.
- **Machine-local Claude Code settings can leak secrets.** Claude Code saves each command
  approved with "don't ask again" verbatim, tokens included, to `.claude/settings.local.json`.
  The repository ignores it at any depth, and `.pre-commit-config.yaml` refuses to commit it
  (or a suffixed copy), `CLAUDE.local.md`, `.credentials.json` or `.env` even when
  force-added, and runs gitleaks on staged content. Residual: git hooks are not cloned, so
  the guard runs only in a clone where it was activated (the header of `.pre-commit-config.yaml`: the hook reads copies of the
  config and the gitleaks policy taken from the default branch and refuses a checked-out
  `.gitleaksignore`, so a checked-out branch cannot redefine them), and
  `git commit --no-verify` skips it. GitHub push protection is the backstop for a public
  repository; a private repository on a personal account has none.

## 14.9 Gaps and their disposition

- **Forms Rule 1 does not list yet.** Rule 1 lists the disagreements found so far; there is
  no independent check that it is complete. The differential oracle test (each string
  parsed by tree-sitter-bash, `bash -n`, shfmt and bash's own `declare -f` reprint, in a
  sandbox) closes this; it is specified in nl-shell's `policy-gate/v1` and tracked as
  nl-shell#191, to move here.
- **Arithmetic evaluation of a variable whose value comes from run time runs commands the
  walk never reports** (a value from the environment, `read`, `printf -v` or a command's
  output, evaluated by `$((v))`, `x[v]=1`, `[[ v -eq 0 ]]`, `let`, `(( ))`): #6. A value
  written as text in the line is flagged by Rule 1. Until #6 closes, a caller that must
  not run hidden commands refuses lines with arithmetic contexts that read variables.
- **Known misreads, open in nl-shell and moving here:** wrong stdin and prefix facts for
  `PATH=… $(true)` and `coproc` (nl-shell#212; its `</dev/stdin` form is fixed). The two
  backtick forms of nl-shell#213 are flagged by Rule 1; other forms of the same kind are
  for the differential oracle to find.
