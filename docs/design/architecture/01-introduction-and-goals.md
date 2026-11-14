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
simple command in it, without running anything. `walk(line)` parses the line and returns a
`Walk`: one `Invocation` per simple command, including those inside substitutions,
functions and here-doc command lines. Each invocation reports:

- its words, each marked literal or not;
- its assignments and redirects;
- where its stdin comes from.

The walk also lists the features that make the parse untrusted. The caller decides what the
command may do; bashwalker makes no policy decision (ADR-0007).

## 1.2 Why it is needed

More and more bash command lines are written by programs: a language model proposing a
command, an agent calling a shell tool, a script assembling a line. Whatever runs them has
to decide before running whether the line is acceptable. For example, an interactive shell
may ask before anything that changes the system, and an agent's guard may block a push to a
protected branch. That decision needs to know what the line will do.

Reading that from the text is harder than it looks. A string match or a regular expression is
fooled by quoting (`'g'it push`), expansions (`$cmd push`), command substitutions hidden in a
word, redirects written in odd places, and text bash evaluates as code (arithmetic,
`PS4`). Bash itself offers no way to get the structure without running the line: `bash -n`
says only whether the syntax is valid.

bashwalker answers the question a caller can build a decision on: what does bash see in this
line? It does this only where the answer can be proven, and it reports everything else as
the worst case.

## 1.3 What tree-sitter-bash does and doesn't do

bashwalker parses with tree-sitter-bash, pinned exactly (ADR-0006).

**What tree-sitter-bash gives:**
- a concrete syntax tree of the line, in-process and fast;
- a tree for any input, even invalid input: what it can't parse it marks with `ERROR` and
  `MISSING` nodes;
- node kinds for bash's constructs: commands, pipelines, lists, redirects, substitutions,
  here-docs, arithmetic, tests.

**What it doesn't do,** and so bashwalker has to:
- **It isn't bash's parser.** It was written for editors and reads some forms differently
  from bash. bashwalker lists those forms and makes the tree untrusted when it meets one
  (Rule 1, §8.1).
- **It doesn't say whether the line is valid bash.** Error tolerance means a broken line
  still yields a tree. bashwalker treats `ERROR` and `MISSING` nodes as untrusted.
- **It doesn't expand anything.** No quote removal, parameter expansion, globbing or
  arithmetic. bashwalker removes quotes as bash does and marks each word literal or not
  (Rule 3, §8.3).
- **It doesn't give simple commands as bash runs them.** bashwalker builds one invocation per
  simple command, with its words, redirects and stdin, and checks that no node was skipped
  (Rule 2, §8.2).
- **It doesn't know bash versions.** One grammar covers every release (§1.4).
- **It knows nothing at run time:** variables, functions, aliases, the cwd. Neither does
  bashwalker (§1.7).

## 1.4 Bash versions

A line can mean different things in different bash releases. In bash 5.3, `${ cmd; }` runs
`cmd`; in 5.1 and 5.2 it is a syntax error. From 5.2, `&` in `${var/pat/rep}` stands for the
matched text; before, it was literal. Bash 3.2, which macOS still ships, has no associative
arrays or namerefs. Today the facts describe bash 5.1–5.3, which the differential test
covers. A form that differs between them is handled as its worst case.

**[OPEN]** Draft proposal 0001 (#27) designs support for several versions, older and newer:
a caller states the versions a line may run on, and each fact must hold for all of them.

## 1.5 The headline promise

**A fact reported as proven holds for bash.** If `walk()` says a word is literal, that a
line has these simple commands, or that stdin comes from a here-string, bash agrees. When a
fact can't be proven, it comes back as the worst case: a non-literal word, `unknown` stdin
or an untrusted tree. A walk that can't be completed raises `ParseRefused` (ADR-0008). The
threat model (§14) treats a wrong fact that looks proven as the main threat, because a
caller's policy would let through a command it would have blocked.

## 1.6 Quality goals

| # | Goal | Meaning |
|---|------|---------|
| 1 | **Sound** | No wrong fact reported as proven; whatever is unproven is reported as the worst case |
| 2 | **Bounded** | Time and memory stay bounded on hostile input; a refusal never quotes the input |
| 3 | **Useful** | Ordinary command lines come back trusted, with facts precise enough for a policy |
| 4 | **Policy-free** | Facts only; what is allowed is the caller's decision |
| 5 | **Easy to embed** | Pure Python on Python 3.11+, installed from PyPI, two exactly pinned dependencies, no subprocesses |

When goals conflict, the lower number wins. For example, arithmetic is trusted only when it
is literal numbers (ADR-0009): goal 1 wins, and goal 3 loses lines such as
`$((RANDOM % 6))`, which now come back untrusted.

## 1.7 Stakeholders and scope

**Stakeholders:**
- **Callers:** programs that decide whether to run a bash command line written by a model,
  an agent or a person. Examples are an interactive shell's policy gate and an agent
  harness's guard against pushes to protected branches.
- **Their maintainers,** who write the policy on top of the facts and must know which facts
  are proven and which are the worst case (§8).
- **Contributors,** who add forms to the proven lists or find forms the grammar misreads.

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
