---
created: 13.11.2026 02:25
type: architecture
status: living
tags:
  - architecture
---
# 9. Build order and roadmap

> Living document. bashwalker has no implementation-arc proposal; this section and the issue tracker hold the plan. Open questions are marked **[OPEN]** inline.

## The order

| Step | What it proves | Release |
|---|---|---|
| Extraction and hardening | The walker works as a package that reports facts only (ADR-0007) and agrees with bash, shfmt and bash's reprint on generated lines (§8.5) | |
| Python 3.11 support | Tools on older supported Pythons can embed it | v0.1.0 |
| Arithmetic rule (ADR-0009) | No command hidden in arithmetic is reported as trusted | v0.1.1 |
| PyPI publishing (#25) | Callers install it with `pip` and pin it exactly (§7) | first PyPI release |
| `coproc` facts (#26) | `coproc` lines give correct facts or come back untrusted | |
| Bash versions (proposal 0001, #27) | Facts hold for every bash version a caller names, older and newer | **[OPEN]** |
| Stable API | Callers can rely on the facts' meaning across minor releases (SECURITY.md) | **[OPEN]** 1.0 |

## Where to start contributing

- **Find a misread.** A bash command line where `walk()` reports a fact that bash doesn't
  agree with is the most useful finding. Report it privately if it hides a command
  (SECURITY.md). The differential test's generator (`tests/test_differential.py`) is a good
  place to add forms.
- **Precision.** A safe line that comes back untrusted costs callers a confirmation or a
  block. A form can be made proven only with a test that runs it in bash.
- **Follow-ups:** #16 (`wait -p` on an integer variable is flagged even though bash unsets
  it first) and #17 (`${#:X}` and `${!:X}` are caught only as syntax errors).

## Later

- **[OPEN]** Running `ARITHMETIC_SINKS` in bash in CI (§13).
- **[OPEN]** Moving the grammar pins when tree-sitter-bash releases, with the differential
  test on every supported bash version as the gate (ADR-0006).
