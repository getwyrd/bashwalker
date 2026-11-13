"""The differential parser test (#7): the walker against `bash -n`, shfmt and bash's own
reprint, on generated command lines.

For each line bash accepts and the walker reports as a trusted tree, every simple command
an oracle sees must be among the walker's invocations, and every word the walker calls
literal must have the oracle's literal text. Anything else is a failure: a command the
walker does not report, or a word it calls literal that bash expands. A line whose
reprint loses its markers escaped the wrapper and fails too. Differences that are not
security-relevant are listed with a reason in ``differential/known.toml``.

The test runs only with ``BASHWALKER_DIFFERENTIAL=1`` (CI's ``differential`` job), and then
a missing tool or a sandbox that cannot be set up is a failure, never a skip.
``BASHWALKER_DIFFERENTIAL_LINES`` and ``BASHWALKER_DIFFERENTIAL_SEED`` change how many
lines are generated and from which seed.
"""

from __future__ import annotations

import os
import random
import tomllib
from collections import Counter
from pathlib import Path

import pytest

import bashwalker
import oracle

ENABLED = os.environ.get("BASHWALKER_DIFFERENTIAL") == "1"
LINES = int(os.environ.get("BASHWALKER_DIFFERENTIAL_LINES", "1500"))
SEED = int(os.environ.get("BASHWALKER_DIFFERENTIAL_SEED", "7"))
KNOWN = tomllib.loads((Path(__file__).parent / "differential" / "known.toml").read_text())

pytestmark = pytest.mark.skipif(not ENABLED, reason="set BASHWALKER_DIFFERENTIAL=1")


# --- generator -----------------------------------------------------------------------

NAMES = ["echo", "cat", "ls", "rm", "git", "printf", "sudo", "x", "a-b", "./run", "/bin/ls"]
PLAIN = ["a", "b", "file.txt", "-rf", "--x", "/tmp/y", "a=b", "x:y", "1", "a~b", "@", "%"]


def word(rng: random.Random, depth: int) -> str:
    pick = rng.randrange(18)
    if pick < 5:
        return rng.choice(PLAIN)
    return [
        lambda: f"'{rng.choice(PLAIN)} {rng.choice(PLAIN)}'",
        lambda: f'"{rng.choice(PLAIN)} $v"',
        lambda: f'"{rng.choice(PLAIN)}"',
        lambda: "$v",
        lambda: "${v:-d}",
        lambda: f"$({line(rng, depth + 1)})" if depth < 2 else "$(id)",
        lambda: f"`{rng.choice(NAMES)} {rng.choice(PLAIN)}`",
        lambda: "*.c",
        lambda: "~/x",
        lambda: "\\$x",
        lambda: "$'a\\tb'",
        lambda: rng.choice(PLAIN) + rng.choice(["'q'", '"q"', "\\ q"]),
        lambda: "{a,b}",
    ][pick - 5]()


def redirect(rng: random.Random) -> str:
    return rng.choice([">f", "2>&1", "<f", ">>/tmp/o", "2>/dev/null", "<<<w", "&>log", ">|f"])


def simple(rng: random.Random, depth: int) -> str:
    parts = []
    if rng.random() < 0.15:
        parts.append(f"V={word(rng, depth)}")
    parts.append(rng.choice(NAMES))
    for _ in range(rng.randrange(4)):
        parts.append(word(rng, depth))
    if rng.random() < 0.3:
        parts.insert(rng.randrange(1, len(parts) + 1), redirect(rng))
    return " ".join(parts)


def line(rng: random.Random, depth: int = 0) -> str:
    kind = rng.randrange(10)
    if kind < 4 or depth >= 2:
        return simple(rng, depth)
    inner = line(rng, depth + 1)
    return [
        lambda: f"{inner} {rng.choice(['&&', '||', ';', '|', '|&'])} {simple(rng, depth)}",
        lambda: f"{{ {inner}; }}",
        lambda: f"( {inner} )",
        lambda: f"if {simple(rng, depth)}; then {inner}; fi",
        lambda: f"for i in a b; do {inner}; done",
        lambda: f"{simple(rng, depth)} <<E\n{word(rng, depth)} $(id)\nE",
    ][kind - 4]()


def generated() -> list[str]:
    rng = random.Random(SEED)
    lines = [line(rng) for _ in range(LINES)]
    return list(dict.fromkeys(lines))


# --- comparison ----------------------------------------------------------------------


def walker_commands(walked: bashwalker.Walk) -> list[tuple]:
    out = []
    for invocation in walked.invocations:
        words = invocation.words
        if not words or not words[0].source:
            continue  # no command word: an assignment or redirect alone
        if invocation.kind == "declaration" or (words[0].literal and words[0].text == "let"):
            out.append((words[0].text,))
            continue
        texts = tuple(w.text if w.literal else None for w in words)
        # `time` is a reserved word to bash and a command word to the grammar.
        while texts[:1] == ("time",) and len(texts) > 1:
            texts = texts[1:]
            if texts[:1] == ("-p",):
                texts = texts[1:]
        out.append(texts)
    return out


def compatible(walker: tuple, other: tuple) -> bool:
    """The walker's command can be the oracle's: same length, and every word the walker
    calls literal is literal with the same text in the oracle."""
    if len(walker) != len(other):
        return False
    return all(w is None or w == o for w, o in zip(walker, other))


def differences(walker: list[tuple], other: list[tuple]) -> list[str]:
    other = [c for c in other if not (c and c[0] == "[")]  # `[ ]` is a test_command
    if len(walker) < len(other):
        return [f"walker reports {len(walker)} commands, oracle {len(other)}: {other}"]
    # A one-to-one matching (augmenting paths): first-fit would give a walker command to
    # the wrong oracle command when two are compatible.
    owner: dict[int, int] = {}  # walker index -> oracle index

    def assign(i: int, seen: set[int]) -> bool:
        for j, mine in enumerate(walker):
            if j in seen or not compatible(mine, other[i]):
                continue
            seen.add(j)
            if j not in owner or assign(owner[j], seen):
                owner[j] = i
                return True
        return False

    unmatched = [other[i] for i in range(len(other)) if not assign(i, set())]
    return [f"oracle command {c} not among the walker's {walker}" for c in unmatched]


def check(text: str) -> list[str]:
    if text in KNOWN.get("lines", {}):
        return []
    try:
        walked = bashwalker.walk(text)
    except bashwalker.ParseRefused:
        return []  # refused is the worst case already
    if walked.untrusted or not oracle.bash_accepts(text):
        return []
    mine = walker_commands(walked)
    problems = []
    shfmt = oracle.shfmt_commands(text)
    if shfmt is not None:
        problems += [f"shfmt: {p}" for p in differences(mine, shfmt)]
    try:
        reprint = oracle.reprint_commands(text)
    except oracle.Escaped as escaped:
        return problems + [f"reprint: escaped the wrapper ({escaped})"]
    if reprint is not None:
        problems += [f"bash reprint: {p}" for p in differences(mine, reprint)]
    return problems


def test_tools_are_available():
    for name in ("bash", "shfmt", "bwrap"):
        oracle._tool(name)
    assert oracle.bash_reprint("echo hi") is not None, "the sandbox could not be set up"


def test_escape_is_detected():
    with pytest.raises(oracle.Escaped):
        oracle.bash_reprint(":; }; g() { :")
    with pytest.raises(oracle.Escaped):
        oracle.bash_reprint(":; }; f() { :;")


def test_generated_lines_agree_with_the_oracles():
    failures = {}
    for text in generated():
        problems = check(text)
        if problems:
            failures[text] = problems
    summary = Counter(p.split(":")[0] for ps in failures.values() for p in ps)
    shown = "\n".join(f"{t!r}\n    " + "\n    ".join(ps) for t, ps in list(failures.items())[:15])
    assert not failures, f"{len(failures)} lines disagree {dict(summary)}:\n{shown}"
