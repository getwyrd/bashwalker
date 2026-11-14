---
created: 13.11.2026 02:25
type: architecture
status: living
tags:
  - architecture
---
# 10–13. Quality, risks, glossary, and testing strategy

> Living document. Combines arc42 sections 10 (quality scenarios), 11 (risks and technical debt) and 12 (glossary), plus the testing strategy (section 13). Open questions are marked **[OPEN]** inline.

## 10. Quality scenarios

| Scenario | Measurable outcome | Goal |
|---|---|---|
| A line hides a command in a form the grammar misreads | `walked.untrusted` is not empty, or the command is among the invocations | 1 Sound |
| A run-time value reaches arithmetic (`echo $((X))`) | The tree is untrusted for every `ARITHMETIC_SINKS` entry | 1 Sound |
| A grammar update adds a node kind | The test suite fails until the corpus covers the kind, so the pin can't move unreviewed | 1 Sound |
| An 8 KiB line of nested substitutions | Refused or walked within the work budget; nothing over the cap is parsed | 2 Bounded |
| A refused line holds a secret or escape codes | The `ParseRefused` message has none of the input | 2 Bounded |
| `cd /tmp && git push origin HEAD:main 2>/dev/null` | Trusted; two invocations; every word literal | 3 Useful |
| A caller's recorded command lines (for example an interactive shell's 21,539-line corpus) through its policy | No verdict looser than before a change; no internal errors | 1, 3 |

## 11. Risks and technical debt

| Risk | Nature | Mitigation |
|---|---|---|
| A misread the generator doesn't produce | Rule 1 is complete only as far as it has been sampled | The differential test, review of each grammar pin change, abuse-case tests; §14.9 |
| The grammar changes under a pin move | Facts change silently | Exact pins; Rule 2's exhaustive handlers; the differential test before any pin moves |
| Too strict for ordinary lines | Callers ask for confirmation more often, and users learn to click through | Corpus comparison against a caller's policy; precision issues like #16 |
| `coproc` facts are wrong | Known misread (#26) | Arithmetic fails closed on any `coproc`; fixing it is on the roadmap (§9) |
| The differential test compares only command splits and literal words | Stdin, redirect and assignment facts are checked by unit tests only | §14.9 |
| `ARITHMETIC_SINKS` are run in bash by hand, not in CI | An entry that no longer runs its payload would not prove its rule | **[OPEN]** in §13 |
| `core.py` is one large module | Harder to review | Sections follow the rules; split it when a section grows its own tests |

## 12. Glossary

| Term | Meaning |
|---|---|
| **Walk** | The result of `walk()`: invocations, assignments, redirects, words and the untrusted reasons |
| **Invocation** | One simple command: words, assignments, redirects, stdin |
| **Simple command** | A command name and its words, as in bash; `command`, `declaration_command` and `unset_command` nodes |
| **Literal word** | A word bash would expand nothing in; its text is what bash sees |
| **Proven** | Shown to hold for bash through a listed form with a test; anything else is the worst case |
| **Worst case** | An untrusted tree, a non-literal word, or `unknown` stdin: what a caller must assume |
| **Untrusted tree** | A walk with at least one reason in `Walk.untrusted`; no fact in it may allow a command |
| **ParseRefused** | The walk could not prove its facts or exceeded a limit |
| **Command head** | The word that runs after `command`, `builtin` and the reserved `time` |
| **Rule 1–3, 5** | The walker's rules, numbered as in the policy specification it was first written for: trusting the tree, no node skipped, literal words and stdin, bounded work (§8) |
| **Differential test** | Generated lines compared with bash, shfmt and bash's reprint (§8.5) |
| **Oracle** | A tool whose reading of a line the walker is compared against |
| **Arithmetic sink** | A place where bash evaluates a value as arithmetic |

## 13. Testing strategy

**The principle:** a form is proven only by a test, and a security fix starts with a test
that fails without it.

| Tier | What | When |
|---|---|---|
| Unit and abuse-case | `tests/test_core.py`: every rule, every proven form, every flagged form, refusals and limits (§14.6) | Every pull request, Python 3.11 and 3.14 |
| Bash-run sinks | Each `ARITHMETIC_SINKS` entry should be a line that really runs a payload in bash; the unit test checks only that it is flagged | By hand when an arithmetic rule changes. **[OPEN]** Run them in bash in CI, as the differential job does for its lines |
| Differential | `tests/test_differential.py` against bash 5.1–5.3, shfmt and bash's reprint | Every pull request |
| Caller corpus | A caller's policy over its recorded command lines, compared with the last release | Before a release that changes facts |
