---
created: 13.11.2026 02:25
type: architecture
status: living
tags:
  - architecture
---
# 1. Introduction and goals

> Living document. What bashwalker is and why. Open questions are marked **[OPEN]** inline.

## 1.1 What this is

bashwalker is a Python library. It takes one bash command line and returns facts about each
simple command in it, without running anything. `walk(line)` parses the line with a pinned
tree-sitter-bash grammar and returns a `Walk`: one `Invocation` per simple command, including
those inside substitutions, functions and here-doc command lines. Each invocation reports:

- its words, each marked literal or not;
- its assignments and redirects;
- where its stdin comes from.

The walk also lists the features that make the parse untrusted. A caller decides what the
command may do; bashwalker makes no policy decision.

It began as the shell layer of [nl-shell](https://github.com/getwyrd/nl-shell)'s policy gate
and keeps that history. nl-shell's gate and pdca-harness's STOP guard are its first callers.

## 1.2 The headline promise

**A fact reported as proven holds for bash.** If `walk()` says a word is literal, that a
line has these simple commands, or that stdin comes from a here-string, bash agrees. When a
fact can't be proven, it comes back as the worst case: a non-literal word, `unknown` stdin
or an untrusted tree. A walk that can't be completed raises `ParseRefused`. The threat model
(§14) treats a wrong fact that looks proven as the main threat, because the caller's policy
would let through a command it would have blocked.

## 1.3 Quality goals

| # | Goal | Meaning |
|---|------|---------|
| 1 | **Sound** | No wrong fact reported as proven; whatever is unproven is reported as the worst case |
| 2 | **Bounded** | Time and memory stay bounded on hostile input; a refusal never quotes the input |
| 3 | **Useful** | Ordinary command lines come back trusted, with facts precise enough for a policy |
| 4 | **Policy-free** | Facts only; what is allowed is the caller's decision |
| 5 | **Easy to embed** | Pure Python on Python 3.11+, two exactly pinned dependencies, no subprocesses |

When goals conflict, the lower number wins. For example, arithmetic is trusted only when it
is literal numbers (#12), so goal 1 costs goal 3 lines such as `$((RANDOM % 6))`.

## 1.4 Stakeholders and target users

- **Callers:** programs that decide whether to run a bash command line written by a model,
  an agent or a person. Today these are nl-shell's policy gate (nl-shell#245) and
  pdca-harness's STOP guard (pdca-harness#898, #957).
- **Their maintainers,** who write the policy on top of the facts and must know which facts
  are proven and which are the worst case (§8).
- **Contributors,** who add forms to the proven lists or find forms the grammar misreads.

## 1.5 Scope boundaries

In scope:
- parsing one command line;
- reporting the facts and the untrusted features;
- bounding the work.

Out of scope:
- **Policy:** which commands, redirects or targets are allowed is the caller's call.
- **Running anything:** bashwalker never starts bash or any other process.
- **Run-time state:** the cwd, the environment, defined functions, aliases and variable
  attributes are invisible to it (§14.8).
- **What a line runs later:** the contents of `eval`, `source`, a script, `python -c`, or a
  non-literal command word. bashwalker reports these commands, not what they will run.
- **Other shells:** sh, dash, zsh and fish.
