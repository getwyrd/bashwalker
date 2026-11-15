# Security policy

bashwalker is early software (0.1.x). Its API isn't stable yet, but its one security
promise holds from 0.1.2 on: a fact `walk()` reports as proven holds for bash, in the
supported versions (today 5.1–5.3 at the patch levels CI tests: 5.1.16, 5.2.37 and 5.3.20;
see architecture §1.5). Other patch levels of those releases are expected to agree but are
not tested; a disagreement on one is in scope. The facts also assume, for the whole run, history expansion, POSIX mode, `keyword` and alias expansion off and `interactive_comments` on, every other option ADR-0010 does not list as harmless (such as `extglob`, a `compat` option or a `BASH_COMPAT` level) at bash's default, and no function, alias or trap the lines do not show. The caller gets this only from a shell it starts itself: a non-interactive bash, built without `--enable-strict-posix-default`, started without option flags and not as `sh`, in a clean environment (`env -i` plus the variables the caller sets itself) that holds no variable bash runs as code or reads as options (`PS0`–`PS4`, `PROMPT_COMMAND`, `BASH_ENV`, `ENV`, `MAILPATH`, `FCEDIT`, `BASHOPTS`, `SHELLOPTS`, `POSIXLY_CORRECT`, `BASH_COMPAT`, `histchars`) and no exported function (`BASH_FUNC_…`), that has run only lines `walk()` reported as trusted, none of them ending in code the walker does not see. A shell set up any other way, such as an interactive shell with startup files, cannot be reset reliably from inside, and the facts do not hold for it, and `terminal` stdin means the stdin the caller gave bash
(architecture §3.2). The known exceptions are listed
in [§14.9](docs/design/architecture/14-threat-model.md#149-gaps-and-their-disposition),
each with an open issue (today wrong stdin and prefix facts for `PATH=… $(true)` (#28) and `coproc`
(#26), and no invocation for a `[ … ]` test (#30)). Its callers
decide whether a command runs based on those facts; nl-shell and pdca-harness are the first,
with their integrations in progress. We want to hear about anything that breaks the
promise, including flaws in the design itself.

Versions before 0.1.1 can report a line as trusted while bash runs a command hidden in
arithmetic. Versions before 0.1.2 can report trusted facts for a line that changes how bash
reads its later commands (GHSA-hc72-48v8-pvg7). Use 0.1.2 or later.

The threat model (assets, trust boundaries, adversaries and the attacks the project must
withstand) is maintained with the design documentation: see
[architecture §14](docs/design/architecture/14-threat-model.md).

The project relies on **coordinated disclosure** and free, continuous tooling: Dependabot
security updates, GitHub secret scanning and CodeQL code scanning run on every push, and
[OpenSSF Scorecard](https://scorecard.dev) rates the repository's practices weekly. GitHub
Actions are pinned to commit hashes. The walker is also checked against bash 5.1–5.3 itself:
the differential test compares it with `bash -n`, shfmt and bash's own reprint on
generated command lines in every pull request. Reporters are credited, and
we will work with you on a disclosure timeline.

**Safe harbor.** We will not pursue or support legal action against researchers acting in
good faith under this policy: accessing only their own data, avoiding privacy violations,
service disruption and data destruction, and giving us reasonable time to fix the problem
before public disclosure.

## Reporting a vulnerability

Please report suspected vulnerabilities **privately**, not in a public issue or pull
request. Use **Report a vulnerability** on the repository's
[Security tab](https://github.com/getwyrd/bashwalker/security/advisories/new), or
email **policy@getwyrd.dev**, with:

- a description of the issue and its impact,
- the steps or proof of concept needed to reproduce it, and
- the affected version or commit.

We will acknowledge your report and keep you informed as we investigate.

## Scope

Until a format or interface is marked stable, behavioural changes to it are expected and
are not in themselves security issues.

**In scope:**

- A command line where `walk()` reports a fact as proven that a supported bash version
  (5.1–5.3) doesn't agree with, and the tree isn't untrusted. Examples are a simple command missing from the invocations, a
  word marked literal that bash expands, or a stdin reported as `terminal`, `pipe` or
  `literal` that is something else. Hidden commands, including commands reached through
  arithmetic, are the most serious case.
- A crash, a hang, or time or memory far beyond `Limits` on some input. A memory-safety bug
  in tree-sitter or the pinned grammar that `walk()` reaches is in scope too: report it
  upstream and to us, so we can move the pin and publish an advisory.
- A `ParseRefused` message, or other error or diagnostic output, that carries the input.
  The facts themselves (word text, assignment values, redirect targets) carry the input on
  purpose.
- A workflow or CI weakness that lets a fork's pull request write to the repository or
  read secrets, or that lets an issue's text (which anyone can write) steer the triage
  workflow beyond its labels, assignee and one comment.

**Out of scope:** the documented residuals in
[§14.8](docs/design/architecture/14-threat-model.md#148-residual-and-accepted-risks):
- a disagreement with a bash version outside the supported ones (5.0 until #29 adds it, or a
  newer release not yet added): open a normal issue. Releases older than 5.0 are not
  supported;
- what `eval`, `source`, a script or a non-literal command word runs later;
- run-time shell state that exists before the line runs (§14.8). State the line itself
  changes (aliases, assignments, `hash -p`, arithmetic that writes a variable) is in scope.

A safe line reported as untrusted is a precision bug, not a vulnerability: please open a
normal issue.
