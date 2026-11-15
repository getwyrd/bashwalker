---
created: 14.11.2026 12:00
type: proposal
status: draft
author: Eduard Ralph
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

Bash 5.0 lacks `SRANDOM` and `wait -p`. Older releases differ more: bash 4.x added associative
arrays, namerefs, `|&` and `;&`, and 3.2, which macOS still ships, has none of them. Newer
releases will keep adding forms, as 5.3 did.

Today bashwalker targets bash 5.1–5.3 implicitly. The differential test runs on those three,
and a form whose meaning differs between them is made untrusted or handled as its worst
case. Nothing records which version a fact holds for, there is no way to add another
release, and a caller whose bash is known can't get the more precise facts that
version allows.

## Design

**A fact holds for a set of versions.** `walk()` gets one parameter describing the bash the
line may run on: its versions and, optionally, the `shopt` and `set` options the caller knows
are on or off (question 4):

```python
walk(line, bash=Bash("5.2"))                                   # the caller knows its version
walk(line, bash=Bash("5.1", "5.2"))                            # ... or that it is one of these
walk(line, bash=Bash("5.2", on={"extglob"}, off={"nocaseglob"}))  # ... and some options
walk(line)                                                      # default: every supported version
```

A version names a release at the patch level CI tests (`"5.2"` means 5.2.37, the level
`scripts/build_bash.py` builds); the profile records it, and it moves only with a full test
run. A version means every patch level of that release: other patch levels are expected to
agree, and a disagreement found on one is a bug like any other. The fix records that patch
level in the profile, and the release's facts become the worst case over its patch levels, so
`Bash("5.2")` stays correct for any 5.2 a caller runs.

An option the caller doesn't mention may be on or off, whatever its default: a session can
have changed it. Only a caller that says the line runs in a fresh shell with the version's
default options (`Bash("5.2", fresh=True)`) gets the profile's defaults for the options it
doesn't mention. "Fresh" means one shell mode only: a non-interactive `bash -c` started
without option flags, in an environment without `BASH_ENV`, `BASHOPTS`, `SHELLOPTS`,
`POSIXLY_CORRECT` or `BASH_COMPAT`, which a new shell would inherit. An interactive shell (history expansion, among others,
changes the line before it is parsed) or one started with flags must not claim it. What the caller declares, and a fresh shell's defaults, describe the shell
only when the line starts. If anything in the line may change an option, every option is
unknown for the **whole** line, not only after that point: a function or loop can run code
written before the change after it. What may change an option includes `shopt`, `set`,
`enable`, `eval`, `source`, a function call or definition, a non-literal command word, and a
write by any means (an assignment, `read`, `printf -v`, `declare`) to a variable that changes
options or the shell's mode, such as `BASH_COMPAT`, `POSIXLY_CORRECT`, `SHELLOPTS` or
`BASHOPTS`. The implementation fixes the exact list, each entry with a test.

bashwalker sees only the line. A declaration (or `fresh=True`) is the caller vouching that
nothing outside the line changes an option while it runs: a shell with a `DEBUG`, `ERR` or
`RETURN` trap, or anything else that runs code between the line's commands, must not
declare options.

The options that change how bash reads a line in ways the profile does not model (history
expansion, POSIX mode, `keyword`, `interactive_comments`) stay outside the profile: they remain caller preconditions
(architecture §3.2), so "every setting left open" never includes them and the default keeps
today's results.

A fact is proven only when it holds for
**every** version in the set, with every setting of the options left open. The default is the
full supported set, so the default stays fail-closed and gives the same results as today.
A caller that knows its bash, for example from `$BASH_VERSINFO` in the session that will run
the line, passes that version and gets facts that need not cover the others.

**Version profiles are data.** A module `bashwalker.versions` lists, for each supported
release, what the walker needs to know:
- syntax added or removed (`${ cmd; }` from 5.3);
- integer variables (`SRANDOM` from 5.1);
- default `shopt` settings that change expansion (`patsub_replacement` from 5.2), used only
  for a caller that declares a fresh shell;
- builtin options the walker reads (`wait -p` from 5.1).

The rules consult the profile instead of hard-coding one bash. A difference that the
profiles don't describe is handled as today: as the worst case.

**One grammar for all versions.** tree-sitter-bash parses a superset of bash (ADR-0006).
Syntax that only some targeted versions accept, or that means different things in them,
makes the tree untrusted unless the profiles say it means the same thing in every targeted
version.

**Adding versions over time.** A new bash release is added in this order:

1. `scripts/build_bash.py` builds it.
2. The differential test and the unit tests for every fact class (words, stdin, redirects,
   assignments) run against it in CI; the differential test alone covers only command
   splitting and literal words (§8.5).
3. Each difference it finds becomes a profile entry with a test.
4. The release joins the supported set in a bashwalker release whose notes announce it
   (question 3).

Bash 5.0 is added the same way (#29). No release older than 5.0 is added (question 1).
A grammar pin move (ADR-0006) must pass the differential test on every supported version.

## Alternatives considered

- **Support only the newest bash.** This is the simplest option, but it gives wrong facts for
  every machine running an older bash, such as the 5.1 and 5.2 of current Linux LTS releases.
- **Support back to 3.2 (macOS's `/bin/bash`) or 4.4.** Every older release adds profile
  entries and turns more of today's proven facts into the worst case for callers using the
  default. Rejected: the oldest release is 5.1, with 5.0 to follow (question 1).
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
caller's statement of which bash will run the line, and with which options. A caller that
names the wrong version or option
can get facts that don't hold for the bash that actually runs, and so can a caller that
declares options for a shell with traps that may change them. The default (all versions)
is fail-closed, and the documentation tells callers to name a version only when they know
it. The pull request that implements this adds the new input and its mitigation to both
threat-model copies (§14 and `.oss-scanner/threat_model.md`); today §14.9 records only that
versions outside 5.1–5.3 are not covered.

## Backward compatibility

The parameter is optional, and its default keeps today's behaviour, so existing callers are
unaffected. Adding a version to the default set, such as 5.0 (#29), can turn facts that are
proven today into the worst case. Such a change is announced in the release notes.

## Open questions

1. **Decided:** the oldest supported bash is 5.1. Support for 5.0 is tracked in #29. Releases
   older than 5.0 will not be supported.
2. **Decided:** the default stays "all supported versions". A caller that names no version
   gets only facts that hold for every one of them, so nothing is reported as proven that
   isn't proven for the bash the caller may have (ADR-0008).
3. **Decided:** a new bash release joins the supported set, and so the default, only in a
   bashwalker release whose notes announce it, after the steps under "Adding versions over
   time". The facts a caller gets never change without a bashwalker release. Until a bash
   release is added, a caller running it gets no guarantee (threat model §14.9).
4. **Decided:** `shopt` and `set` options a caller knows (for example `extglob`) belong in
   the same parameter as the version. They are tied together: the version decides which
   options exist and their defaults in a fresh shell (`patsub_replacement` is on from 5.2).
