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
| Extraction (#3) | nl-shell's shell layer works as a package without nl-shell's policy | |
| Hardening and the differential test (#7) | The walker agrees with bash, shfmt and bash's reprint on generated lines | |
| Python 3.11 support (#8) | pdca-harness instances can use it | v0.1.0 |
| Arithmetic rule (#12) | No command hidden in arithmetic is reported as trusted | v0.1.1 |
| nl-shell integration (nl-shell#245) | The gate runs on bashwalker with no loosened verdicts on nl-shell's corpus | nl-shell release |
| pdca-harness integration (pdca-harness#957) | The STOP guard (pdca-harness#898) decides on bashwalker's facts | pdca-harness 0.59.1 |

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

- `coproc`: its stdin and prefix facts are wrong (nl-shell#212, moving here). Today the
  arithmetic rule treats any `coproc` as untrusted.
- **[OPEN]** Publishing to PyPI, and when to mark the API stable (SECURITY.md).
- **[OPEN]** Moving the grammar pins when tree-sitter-bash releases, with the differential
  test as the gate.
