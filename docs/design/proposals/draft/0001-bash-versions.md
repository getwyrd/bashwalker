---
created: 14.11.2026 12:00
type: proposal
status: draft
author: Eduard R.
tracking-issue: 27
supersedes:
tags:
  - proposal
  - bash-versions
---
# Proposal: Support several bash versions

## Motivation

The facts bashwalker reports describe what bash does with a line, and bash changes from
release to release. A line can mean different things depending on the bash that runs it.
These were checked on bash 5.1, 5.2 and 5.3:

| Form | 5.1 | 5.2 | 5.3 |
|---|---|---|---|
| `${ cmd; }` | bad substitution | bad substitution | runs `cmd` in the current shell |
| `&` in `${var/pat/rep}` | literal `&` | the matched text (`patsub_replacement` on by default) | same as 5.2 |
| `SRANDOM`, `wait -p` | present | present | present |

Older releases differ more. Bash 4.x added associative arrays, namerefs, `|&` and `;&`, and
3.2, which macOS still ships, has none of them. Newer releases will keep adding forms, as
5.3 did.

Today bashwalker targets bash 5.1–5.3 implicitly. The differential test runs on those three,
and a form whose meaning differs between them is made untrusted or handled as its worst
case. Nothing records which version a fact holds for, there is no way to add an older or a
newer release, and a caller whose bash is known can't get the more precise facts that
version allows.

## Design

**A fact holds for a set of versions.** `walk()` gets a parameter naming the bash versions
the line may run on:

```python
walk(line, bash=BashVersions("5.2"))          # the caller knows its bash
walk(line)                                     # default: every supported version
```

A fact is proven only when it holds for **every** version in the set. The default is the
full supported set, so the default stays fail-closed and gives the same results as today.
A caller that knows its bash, for example from `$BASH_VERSINFO` in the session that will run
the line, passes that version and gets facts that need not cover the others.

**Version profiles are data.** A module `bashwalker.versions` lists, for each supported
release, what the walker needs to know:
- syntax added or removed (`${ cmd; }` from 5.3, `|&` from 4.0);
- integer variables (`SRANDOM` from 5.1);
- default `shopt` settings that change expansion (`patsub_replacement` from 5.2);
- builtin options the walker reads (`wait -p` from 5.1).

The rules consult the profile instead of hard-coding one bash. A difference that the
profiles don't describe is handled as today: as the worst case.

**One grammar for all versions.** tree-sitter-bash parses a superset of bash (ADR-0006).
Syntax that only some targeted versions accept, or that means different things in them,
makes the tree untrusted unless the profiles say it means the same thing in every targeted
version.

**Adding versions over time.** A new bash release is added in this order:

1. `scripts/build_bash.py` builds it.
2. The differential test runs against it in CI.
3. Each difference it finds becomes a profile entry with a test.
4. The release joins the supported set.

An older release is added the same way, back to the oldest version chosen (open question 1).
A grammar pin move (ADR-0006) must pass the differential test on every supported version.

## Alternatives considered

- **Support only the newest bash.** This is the simplest option, but it gives wrong facts for
  every machine running an older bash, including macOS's 3.2.
- **One walker per version (separate packages or pinned releases).** It avoids profiles, but
  a caller that doesn't know its bash can't get a fail-closed answer across versions, and
  every fix would have to be repeated in each one.
- **Detect the version by running bash.** bashwalker doesn't start processes (ADR-0006). The
  caller knows which bash will run the line; bashwalker does not.

## Graduation criteria

- `walk(line, bash=…)` exists, and its default (all supported versions) gives the same facts
  as today for bash 5.1–5.3.
- Every profile entry has a test, and the differential test runs on every supported version
  in CI.
- The documentation lists the supported versions and how a caller chooses them (architecture
  §2, §7, §8).

## Security impact

The line is still the untrusted input (threat model §14.2). The new trusted input is the
caller's statement of which bash will run the line. A caller that names the wrong version
can get facts that don't hold for the bash that actually runs. The default (all versions)
is fail-closed, and the documentation tells callers to name a version only when they know
it. §14 gains an entry for this.

## Backward compatibility

The parameter is optional, and its default keeps today's behaviour, so existing callers are
unaffected. Adding an older version to the default set can turn facts that are proven today
into the worst case. Such a change is announced in the release notes.

## Open questions

1. **[OPEN]** Which is the oldest bash to support: 3.2 (macOS), 4.4, or 5.0?
2. **[OPEN]** Should the default stay "all supported versions", or should callers have to
   name a version?
3. **[OPEN]** When a new bash release comes out, does it join the supported set (and so the
   default) automatically, or only in a release that announces it?
4. **[OPEN]** Do `shopt` and `set` options a caller enables (for example `extglob`) belong in
   the same parameter as the version?
