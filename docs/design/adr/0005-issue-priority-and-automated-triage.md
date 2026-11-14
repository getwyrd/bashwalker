---
created: 13.11.2026 02:25
type: adr
status: Proposed
tags:
  - adr
  - process
  - triage
---
# 0005. Issue priority: severity and reach set P0–P3, applied by hand or by a bot

## Context

Issues reach the repository from users, contributors, automated loops and deferred review
findings. Without a written scheme, ordering the backlog means rereading issues one by one,
and two people (or one person on different days) put the same issue at different
priorities. The scheme has to work the same for a human triager and for a bot, so either
can check the other.

## Decision

We qualify every issue with three labels, derive a priority from two of them with a fixed
table, and then apply a short list of overrides. Sections 1–3 apply to whoever triages;
section 4 adds what an automated triager may and may not do.

### 1. Labels describing the issue

**Severity: how bad it is when it happens**

| Label | Meaning |
|---|---|
| `sev:critical` | Data loss or corruption, a security or safety property broken, or a secret leaks |
| `sev:major` | A safety check bypassed or silently off, a crash, or a core feature broken with no workaround |
| `sev:minor` | Wrong behaviour with a workaround, or a visible degradation |
| `sev:trivial` | Cosmetic, wording, docs, or a test-only gap |

**Reach: how likely someone hits it**

| Label | Meaning |
|---|---|
| `reach:common` | Normal use triggers it |
| `reach:edge` | Needs an unusual setup, input or timing |
| `reach:adversarial` | Only triggers when someone sets it up on purpose |

For bashwalker, *a security or safety property broken* means a fact that `walk()` reports
as proven while bash disagrees, on a tree it reports as trusted. Examples are a hidden
command, a word marked literal that bash expands, or a wrong stdin. Callers allow commands
on those facts (threat model §14.1), so this is `sev:critical`. *A core feature broken*
means `walk()` crashes, hangs or refuses ordinary command lines. A safe line wrongly
reported as untrusted is `sev:minor`: callers fail closed, at the cost of a confirmation or
a block.

**Area: where the issue lives** (for routing and assignment): the `area:*` labels in
`.github/triage/labels.json`:

| Label | Covers |
|---|---|
| `area:walker` | `src/bashwalker/`: the walk, the trust rules, the facts and their API |
| `area:ci` | Workflows, build and release tooling, `scripts/` |
| `area:docs` | ADRs, specs, the threat model and other docs |
| `area:tests` | The test suite only, including the differential test, when the walker is right |

### 2. Priority from severity and reach

| | common | edge | adversarial |
|---|---|---|---|
| **critical** | P0 | P1 | P1 |
| **major** | P1 | P2 | P2 |
| **minor** | P2 | P3 | P3 |
| **trivial** | P3 | P3 | P3 |

- **P0:** drop other work, fix now, block the release.
- **P1:** goes on the current milestone.
- **P2:** next milestone, or whenever it fits.
- **P3:** backlog; may be closed if it sits for a long time.

The labels are `priority:P0` to `priority:P3`. Severity and reach set a priority only for a
`bug`; other types are prioritized by the maintainer.

### 3. Overrides

- **Security or safety bugs get at least P1, even when `reach:adversarial`.** bashwalker's
  main threat is an adversary who writes the command line (threat model §14.3), so an
  attacker-only misread is the case that matters most, as in nl-shell.
- **`release-gating` means at least P1**, whatever the table says.
- **`accessibility` barriers get at least P2.**
- **Deferred review findings** keep the review's priority, unless the triager can show the
  PR changed the impact.
- **When unsure, leave the priority off.** If the triager can't place severity or reach,
  they set `needs-triage` and say what is missing. Never guess a lower priority.

### 4. Automated triage

`.github/workflows/triage-priority.yml` runs `.github/triage/triage_priority.py` on each new
issue without a priority. It:

1. sets type (`bug`, `enhancement`, `documentation` or `research`), severity, reach, area
   and a `priority:*` label;
2. posts one comment with a sentence of reasoning per label, so the maintainer can check the
   call quickly;
3. assigns by area from the owner table in `labels.json`;
4. leaves the milestone empty. Setting it stays the maintainer's decision, so the `new`
   label stays until then (`triage-new-issue.yml`).

Issue text is untrusted, and GitHub's `issues: write` permission also allows editing,
closing and re-milestoning issues. So the model MUST NOT hold a token that can write:

- The model runs in its own job with a read-only token and no secret except its own
  short-lived Claude credential (OIDC workload identity federation; no API key is
  stored). Token permissions are per job, so the split MUST be between jobs.
- A second job runs no model, alone holds `issues: write`, and applies the verdict as data.
  It accepts only labels from `labels.json` (one of each kind, plus `needs-triage`), only an
  assignee from the owner table, and posts the comment as text. A verdict that fails these
  checks is dropped and the issue gets `needs-triage`.
- Reasons never quote the issue; an issue that appears to contain a secret or an undisclosed
  vulnerability gets its labels but no posted reasons.

The workflow does nothing until the repository has the `ANTHROPIC_*` variables and a
matching federation rule in the Claude Console.

## Consequences

Every issue carries a priority that says why it has it, and the backlog can be sorted by
label. Manual and automated triage use the same rules. Each automated run costs model
tokens; one request per issue, capped input and the workspace spending limit bound it.
Leaving the milestone to the maintainer keeps work from starting on the bot's judgement
alone, at the cost of one manual step per issue.
