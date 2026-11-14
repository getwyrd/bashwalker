# Security policy

bashwalker is early software (0.1.x). Its API isn't stable yet, but its one security
promise holds from the start: a fact `walk()` reports as proven holds for bash, in the
supported versions (today 5.1–5.3; see architecture §1.5). Its callers
decide whether a command runs based on those facts; nl-shell and pdca-harness are the first,
with their integrations in progress. We want to hear about anything that breaks the
promise, including flaws in the design itself.

Versions before 0.1.1 can report a line as trusted while bash runs a command hidden in
arithmetic. Use 0.1.1 or later.

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
- A crash, a hang, or time or memory far beyond `Limits` on some input.
- A `ParseRefused` message, or other error or diagnostic output, that carries the input.
  The facts themselves (word text, assignment values, redirect targets) carry the input on
  purpose.
- A workflow or CI weakness that lets a fork's pull request write to the repository or
  read secrets.

**Out of scope:** the documented residuals in
[§14.8](docs/design/architecture/14-threat-model.md#148-residual-and-accepted-risks):
- a disagreement with a bash version outside the supported ones (for example 3.2 or a newer
  release not yet added): open a normal issue;
- what `eval`, `source`, a script or a non-literal command word runs later;
- run-time shell state;
- memory-safety bugs inside tree-sitter itself (report those upstream).

A safe line reported as untrusted is a precision bug, not a vulnerability: please open a
normal issue.
