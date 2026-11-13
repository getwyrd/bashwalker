"""Oracles for the differential test (#7): what bash, shfmt and bash's own reprint say a
command line contains, as lists of simple commands.

A simple command is a tuple of words; a word is its text after quote removal when it is
literal, or ``None`` when bash expands it. Each oracle returns ``None`` when it does not
accept the line. The tools are found on ``PATH`` (``bash``, ``shfmt``, ``bwrap``); a
missing one raises ``OracleUnavailable``, which the test turns into a failure, never a
skip, once it is enabled.
"""

from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess

TIMEOUT = 10


class OracleUnavailable(Exception):
    pass


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise OracleUnavailable(f"{name} not found on PATH")
    return path


def _run(argv: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        input=stdin,
        capture_output=True,
        text=True,
        errors="surrogateescape",
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        timeout=TIMEOUT,
    )


def bash_accepts(line: str) -> bool:
    """`bash -n`: whether bash parses the line."""
    return _run([_tool("bash"), "--norc", "--noprofile", "-n", "-c", line]).returncode == 0


# --- shfmt ---------------------------------------------------------------------------

_DOUBLE_QUOTED_ESCAPE = re.compile(r'\\([$`"\\\n])')
_UNQUOTED_ESCAPE = re.compile(r"\\(.)", re.S)


def _lit_literal(value: str, first: bool) -> bool:
    """Whether an unquoted shfmt literal is text bash leaves alone: no glob, brace or
    tilde expansion (a leading `~`, or one after `=` or `:`)."""
    unescaped = re.sub(r"\\.", "", value)
    if any(c in unescaped for c in "*?{}") or re.search(r"\[.*\]", unescaped):
        return False  # a `[` is a glob only with a `]` after it
    if first and unescaped.startswith("~"):
        return False
    return not re.search(r"[=:]~", unescaped)


def _word(word: dict) -> str | None:
    """A shfmt word as the comparison sees it: its text, or None when bash expands it."""
    out = []
    for i, part in enumerate(word.get("Parts", [])):
        kind = part.get("Type")
        if kind == "Lit":
            value = part.get("Value", "")
            if not _lit_literal(value, i == 0):
                return None
            out.append(_UNQUOTED_ESCAPE.sub(r"\1", value).replace("\\\n", ""))
        elif kind == "SglQuoted":
            if part.get("Dollar"):
                return None
            out.append(part.get("Value", ""))
        elif kind == "DblQuoted":
            if part.get("Dollar"):
                return None
            for inner in part.get("Parts", []):
                if inner.get("Type") != "Lit":
                    return None
                out.append(_DOUBLE_QUOTED_ESCAPE.sub(r"\1", inner.get("Value", "")))
        else:
            return None
    return "".join(out)


def _commands(tree: dict) -> list[tuple]:
    """Every simple command in a shfmt tree, in any position (also inside substitutions,
    here-docs and backticks)."""
    found: list[tuple[int, tuple]] = []

    def visit(node) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if not isinstance(node, dict):
            return
        kind = node.get("Type")
        offset = node.get("Pos", {}).get("Offset", 0)
        if kind == "CallExpr" and node.get("Args"):
            found.append((offset, tuple(_word(w) for w in node["Args"])))
        elif kind == "DeclClause":
            found.append((offset, (node.get("Variant", {}).get("Value"),)))
        elif kind == "LetClause":
            found.append((offset, ("let",)))
        for value in node.values():
            visit(value)

    visit(tree)
    return [command for _, command in sorted(found, key=lambda item: item[0])]


def shfmt_commands(line: str) -> list[tuple] | None:
    """shfmt's simple commands for the line, or None when shfmt does not parse it."""
    result = _run([_tool("shfmt"), "--to-json", "-ln", "bash"], stdin=line + "\n")
    if result.returncode != 0:
        return None
    return _commands(json.loads(result.stdout))


# --- bash's own reprint --------------------------------------------------------------


class Escaped(Exception):
    """The line closed the wrapper function: its markers did not survive the reprint."""


def bash_reprint(line: str) -> str | None:
    """bash's reprint of the line as the body of a function, made inside a sandbox
    (bubblewrap: the root read-only, a fresh tmpfs, no network, killed with the test).
    Raises ``Escaped`` when the reprint is not exactly the wrapped body."""
    nonce = "n" + secrets.token_hex(8)
    script = f"f() {{ : {nonce}_start;\n{line}\n: {nonce}_end;\n}}\ndeclare -F\ndeclare -f f\n"
    argv = [
        _tool("bwrap"), "--ro-bind", "/", "/", "--tmpfs", "/tmp", "--dev", "/dev",
        "--proc", "/proc", "--unshare-all", "--die-with-parent", "--chdir", "/tmp",
        _tool("bash"), "--norc", "--noprofile", "-c", script,
    ]
    try:
        result = _run(argv)
    except subprocess.TimeoutExpired:
        raise Escaped("timed out while sourcing") from None
    if "bwrap:" in result.stderr:
        raise OracleUnavailable(f"sandbox failed: {result.stderr.strip()[:200]}")
    if result.returncode != 0:
        return None
    out = result.stdout
    functions, _, body = out.partition("f () \n")
    if functions.strip() != "declare -f f":
        raise Escaped(f"functions defined: {functions.strip()!r}")
    lines = body.strip().splitlines()
    if len(lines) < 2 or f": {nonce}_start" not in lines[1] or f": {nonce}_end" not in body.rstrip()[-80:]:
        raise Escaped("markers missing from the reprint")
    return body


def reprint_commands(line: str) -> list[tuple] | None:
    """shfmt's simple commands in bash's reprint, without the two marker commands."""
    body = bash_reprint(line)
    if body is None:
        return None
    commands = shfmt_commands("f () \n" + body)
    if commands is None:
        return None
    return [c for c in commands if not (len(c) == 2 and c[0] == ":" and c[1] and c[1].startswith("n") and c[1].endswith(("_start", "_end")))]
