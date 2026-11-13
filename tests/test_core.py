"""The walker's facts, rule by rule (numbered as in nl-shell's ``policy-gate/v1``).

These tests check what the walker proves about a command, never whether the command is
allowed: that is the caller's policy. Each fact that is not proven must come back as the
worst case (``unknown`` stdin, a non-literal word, an untrusted tree, ``ParseRefused``).
"""

from __future__ import annotations

import itertools

import pytest
import tree_sitter
import tree_sitter_bash

import bashwalker
from bashwalker import core

# Rule 1: one input per feature tree-sitter-bash reads differently from bash.
UNTRUSTED = {
    "if true; then": "missing token",
    "case x in": "syntax error",
    "echo a\\\nb": "backslash-newline",
    "cat <<\\E\nx\nE": "here-doc delimiter",
    'cat <<E"F"\nx\nEF': "here-doc delimiter",
    "cat <<$'E'\nx\nE": "here-doc delimiter",
    "cat <<-E\n\tx\nE": "<<-",
    "cat <<A <<B\na\nA\nb\nB": "more than one here-doc",
    "ls ?(a)": "extglob",
    "ls *(a)": "extglob",
    "ls +(a)": "extglob",
    "ls @(a)": "extglob",
    "ls !(a)": "extglob",
    "echo ${ echo x; }": "${ }",
    "echo ${| REPLY=x; }": "${ }",
    "[ x > y ]": "inside [ ]",
}

# Inputs that, together, hold every named node kind of the pinned grammar.
KIND_COVERAGE = [
    "for ((i=0; i<3; i++)); do echo $i; done",
    "echo $(( a ? b : c )) $(( (1+2) )) $(( -x )) $(( x++ ))",
    "[[ $x =~ ^a ]] && [[ -n x ]] && [ -f x ]",
    'echo $"x" ${a[0]} ${x:-y} $? {a,b}',
    "case x in @(a|b)) :;; esac",
    "a=(1 2); b=1 c=2; ! true",
    "echo x 2>&1 # comment",
    "cat <<E\n$x y\nE",
    "cat <<<x",
    "echo 'a' \"b $c\"",
    "unset a; export b=1",
    "echo {1..3}; a=$\"x\"",
    "a | b; c && (d) || { e; }; if f; then g; elif h; then i; else j; fi; "
    "while k; do l; done; for x in 1; do m; done; case x in y) n;; esac; "
    "fn() { o; }; echo $(p) `q`; export R=1; unset S",
    "until a; do b; done; select x in 1; do c; done; coproc d; function g { :; }",
    "echo ${x/a/b} ${x#a} ${#x} ${!x} $'a\\n' a[1]=2 <(ls) >(cat)",
    "cat <<'E'\nx\nE",
    "echo $((1 << 2)) $[1+1]; declare -a x=(); local y; readonly z",
    "x+=1; echo ~ ~/x a*b [ab] \\$x; echo \"${x}\"; time ls",
    "echo \"$(echo \"x\")\"; ((x = 1)); [[ ( a == b ) ]]; [ ! -f x ]",
    "cat 3<x 4>&- {fd}>y &>z &>>w >|v <>u",
]

R4_OPERATORS = ("<", ">", ">>", ">|", "&>", "&>>", "<>", ">&", "<&")
R4_DESCRIPTORS = ("", "0", "1", "2", "3", "{fd}")
R4_TARGETS = ("0", "1", "-", "3", "$x", "out.txt", "~/f", "/dev/null", "../x", '"$f"', "fd/3")


def corpus() -> list[str]:
    redirects = [
        f"echo x {fd}{op}{target}"
        for op, fd, target in itertools.product(R4_OPERATORS, R4_DESCRIPTORS, R4_TARGETS)
    ]
    return list(UNTRUSTED) + KIND_COVERAGE + redirects


def tree_counts(command: str) -> tuple[int, set[str]]:
    tree = core.parse_source(command.encode("utf-8", "surrogatepass"))
    count, kinds, stack = 0, set(), [tree.root_node]
    while stack:
        node = stack.pop()
        if node.is_named:
            kinds.add("ERROR" if node.is_error else node.type)
            if node.type in core.SIMPLE_KINDS:
                count += 1
        stack.extend(node.children)
    return count, kinds


def grammar_kinds() -> set[str]:
    language = tree_sitter.Language(tree_sitter_bash.language())
    return {
        language.node_kind_for_id(i)
        for i in range(language.node_kind_count)
        if language.node_kind_is_named(i) and language.node_kind_is_visible(i)
    }


# --- Rule 1 --------------------------------------------------------------------------


@pytest.mark.parametrize("command", list(UNTRUSTED))
def test_rule1_names_each_feature(command):
    found = bashwalker.walk(command).untrusted
    assert any(UNTRUSTED[command] in f for f in found), (command, found)


def test_rule1_quoted_text_is_trusted():
    for command in ("echo '?(a)' \"*(b)\" \\@\\(c\\)", "echo 'a\\\nb'", "cat <<'E'\nx\nE"):
        assert bashwalker.walk(command).untrusted == (), command


def test_rule1_untrusted_tree_proves_no_stdin():
    walked = bashwalker.walk("cat <x; ls @(a)")
    assert {i.stdin.kind for i in walked.invocations} == {"unknown"}


# --- Rule 2 --------------------------------------------------------------------------


def test_rule2_one_invocation_per_simple_command():
    for command in corpus():
        expected, _ = tree_counts(command)
        assert len(bashwalker.walk(command).invocations) == expected, command
    walked = bashwalker.walk("echo $((10#$(rm x)))")
    assert [i.words[0].text for i in walked.invocations] == ["rm", "echo"]


def test_rule2_every_kind_has_a_handler():
    kinds = grammar_kinds()
    assert len(kinds) > 50
    assert sorted(k for k in kinds | {"ERROR"} if k not in core.HANDLERS) == []


def test_rule2_removed_handler_is_refused(monkeypatch):
    seen: dict[str, str] = {}
    for command in corpus():
        for kind in tree_counts(command)[1]:
            seen.setdefault(kind, command)
    assert sorted(grammar_kinds() - set(seen)) == []
    for kind, command in sorted(seen.items()):
        with monkeypatch.context() as m:
            m.delitem(core.HANDLERS, kind)
            with pytest.raises(bashwalker.ParseRefused):
                bashwalker.walk(command)


@pytest.mark.parametrize(
    "kind,command",
    [
        ("pipeline", "ls | wc"),
        ("command_substitution", "echo $(id)"),
        ("redirected_statement", "ls >x"),
        ("compound_statement", "{ ls; }"),
        ("heredoc_redirect", "cat <<E | sh\nx\nE"),
        ("program", "ls"),
    ],
)
def test_rule2_skipped_children_are_refused(monkeypatch, kind, command):
    bashwalker.walk(command)
    monkeypatch.setitem(core.HANDLERS, kind, lambda walker, node, ctx, depth, bound=(): [])
    with pytest.raises(bashwalker.ParseRefused):
        bashwalker.walk(command)


def test_walk_reaches_every_simple_command():
    walked = bashwalker.walk(KIND_COVERAGE[12])
    seen = {(i.kind, i.words[0].text) for i in walked.invocations}
    assert set("abcdefghijklmnopq") <= {w for _, w in seen}
    assert ("declaration", "export") in seen
    assert ("unset", "unset") in seen


# --- Rule 3 --------------------------------------------------------------------------


def stdin_of(command: str) -> dict[str, tuple[str, str | None]]:
    out = {}
    for invocation in bashwalker.walk(command).invocations:
        out[invocation.words[0].text] = (invocation.stdin.kind, invocation.stdin.value)
    return out


def test_rule3_stdin_sources():
    assert stdin_of("cat <<E | sudo tee /x\nx\nE")["sudo"][0] == "pipe"
    assert stdin_of("cat <x | y")["y"][0] == "pipe"
    assert stdin_of("cat <<<x | y")["y"][0] == "pipe"
    assert stdin_of("a | b <f") == {"a": ("terminal", None), "b": ("file", "f")}
    assert stdin_of("curl x > >(sh)")["sh"][0] == "pipe"
    assert stdin_of("cat <<E > >(sudo tee /x)\nx\nE")["sudo"][0] == "pipe"
    assert stdin_of("f() { sudo tee /x; }; cat <<E | f\nx\nE")["sudo"][0] == "unknown"
    assert stdin_of("f() { sh; }; curl x | f")["sh"][0] == "unknown"
    assert stdin_of("cat 0>&1")["cat"][0] == "unknown"
    assert stdin_of("cat 0>&-")["cat"][0] == "unknown"
    assert stdin_of("bash <<<'rm -rf ~'")["bash"] == ("literal", "rm -rf ~")
    assert stdin_of("cat <<'E'\n$x\nE")["cat"] == ("literal", "$x\n")
    assert stdin_of("cat <<E\nplain\nE")["cat"] == ("literal", "plain\n")
    assert stdin_of("cat <<E\n$x\nE")["cat"][0] == "unknown"
    assert stdin_of("cat <<-E\n\t$(rm x)\nE")["cat"][0] != "literal"
    assert stdin_of("cat")["cat"] == ("terminal", None)
    assert stdin_of("cat <$f")["cat"][0] == "unknown"
    assert stdin_of("cat <&3")["cat"][0] == "unknown"
    assert stdin_of("cat <>f")["cat"][0] == "unknown"
    assert stdin_of("{ cat; } <f")["cat"] == ("file", "f")
    assert stdin_of("{ sudo tee /etc/y; } </tmp/x")["sudo"] == ("file", "/tmp/x")
    assert stdin_of("exec </tmp/x; sudo tee /etc/y")["sudo"][0] == "unknown"
    assert stdin_of("while :; do cat; exec <x; done")["cat"][0] == "unknown"
    assert stdin_of("command exec <x; cat")["cat"][0] == "unknown"
    assert stdin_of("eval x; cat")["cat"][0] == "unknown"
    assert stdin_of("$x <f; cat")["cat"][0] == "unknown"
    assert stdin_of("trap 'exec <<<payload' DEBUG; cat")["cat"][0] == "unknown"
    assert stdin_of("exec; cat")["cat"] == ("terminal", None)
    assert stdin_of("PATH=x >/dev/null")[""][0] == "unknown"  # untrusted (MISSING)


def test_rule3_file_stdin_names_its_redirect():
    # Only fd 0 written as `<` or `0<`; the caller judges the redirect it came from.
    assert stdin_of("cat 00<f")["cat"][0] == "unknown"
    assert stdin_of("cat 1<f")["cat"] == ("terminal", None)
    (invocation,) = bashwalker.walk("cat <self/fd/4").invocations
    assert (invocation.stdin.kind, invocation.stdin.value) == ("file", "self/fd/4")
    assert invocation.stdin.via is invocation.redirects[0]
    assert invocation.stdin.via.target.text == "self/fd/4"
    walked = bashwalker.walk("{ cat; } <f")
    (inner,) = walked.invocations
    assert inner.stdin.via is walked.redirects[0]  # a compound's redirect, inherited
    assert bashwalker.Stdin("file", "f") == inner.stdin  # `via` is not part of equality


def test_words_next_to_redirects_are_kept():
    def words(command):
        (invocation,) = bashwalker.walk(command).invocations
        return [w.text for w in invocation.words], [
            (r.descriptor, r.operator) for r in invocation.redirects
        ]

    assert words("rm -rf />/dev/null") == (["rm", "-rf", "/"], [(None, ">")])
    assert words("sudo rm -rf /etc>x") == (["sudo", "rm", "-rf", "/etc"], [(None, ">")])
    assert words("rm -rf ~>/dev/null") == (["rm", "-rf", "~"], [(None, ">")])
    assert words("cat a3>f") == (["cat", "a3"], [(None, ">")])
    assert words('echo "3">f') == (["echo", "3"], [(None, ">")])
    assert words("echo x}>f") == (["echo", "x}"], [(None, ">")])
    assert words("cat 0>&-") == (["cat"], [("0", ">&-")])
    assert words("echo {x}>f") == (["echo"], [("{x}", ">")])
    # Only what bash itself takes as a descriptor (checked against bash 5.3): ASCII
    # digits, `{name}` and `{name[subscript]}`. Every other token stays an argument.
    for token in ("{fd}", "{_a1}", "{A9}", "{a[1]}", "{a[$i]}", "12"):
        assert words(f"printf x {token}>f") == (["printf", "x"], [(token, ">")]), token
    for token in ("١", "٣", "{a,b}", "{x-y}", "{1x}", "{}", "{a[]}", "{a[x]]}", "{a[1][2]}", "{é}"):
        assert words(f"rm {token}>f") == (["rm", token], [(None, ">")]), token
    (invocation,) = bashwalker.walk("PATH=/tmp/evil >/dev/null").invocations
    assert [(a.name, a.role) for a in invocation.assignments] == [("PATH", "standalone")]
    assert [w.text for w in invocation.words] == [""]


def test_rule3_literal_flag():
    def second_word(command):
        return bashwalker.walk(command).invocations[-1].words[1]

    assert not second_word("cat ~/x").literal
    assert second_word("cat '~'/x").literal
    assert second_word("cat \\~/x").literal
    assert second_word("cat '~'/x").text == "~/x"
    for command in (
        "cat $x",
        "cat `x`",
        "cat *.c",
        "cat a?",
        "cat [ab]",
        "cat {a,b}",
        'cat "$x"',
        "cat $'x'",
        "cat x=~/y",
        "cat a:~/y",
    ):
        assert not second_word(command).literal, command
    for command in ("cat plain", "cat 'a b'", 'cat "a b"', "cat a\\*b", "cat a=b"):
        assert second_word(command).literal, command
    assert not bashwalker.walk("A=x:~/b").assignments[0].value.literal
    assert bashwalker.lex_word("~/x")[1] == frozenset({"leading-tilde"})


def test_declaration_operands():
    names = [a.name for a in bashwalker.walk("export 'SUDO_PROMPT=x' S'UDO'=y \"$x\"").assignments]
    assert names == ["SUDO_PROMPT", "SUDO", ""]


# --- redirect facts ------------------------------------------------------------------


def only_redirect(command: str) -> bashwalker.Redirect:
    (record,) = bashwalker.walk(command).redirects
    return record


def test_redirect_facts():
    r = only_redirect("echo x 2>out.txt")
    assert (r.kind, r.descriptor, r.operator, r.target.text) == ("file_redirect", "2", ">", "out.txt")
    assert r.readable and r.output and r.relative
    assert not only_redirect("echo x >/tmp/f").relative
    assert only_redirect("echo x >~/f").relative
    assert not only_redirect("echo x 2>&1").relative  # a dup of 0-2 names no file
    assert not only_redirect("cat <f").output
    assert only_redirect("cat 3<f").output  # writes no stdin: not fd 0
    closed = only_redirect("cat 0>&-")
    assert closed.readable and closed.target is None
    heredoc = only_redirect("cat <<E\nx\nE")
    assert (heredoc.kind, heredoc.heredoc_operator, heredoc.feed.kind) == (
        "heredoc_redirect",
        True,
        "literal",
    )
    here = only_redirect("cat <<<$x")
    assert (here.kind, here.target.literal, here.feed.kind) == ("herestring_redirect", False, "unknown")
    bracket = bashwalker.walk("[ a > b ]").redirects
    assert [(r.kind, r.in_test, r.readable) for r in bracket] == [("loose", True, False)]


def test_unreadable_targets_are_marked():
    # A MISSING target, or one the tree splits into several destinations.
    for command in ("echo x 2>", "cat <a b"):
        walked = bashwalker.walk(command)
        assert [r.readable for r in walked.redirects] == [False], command
    # An unreadable stdin redirect proves no stdin.
    assert bashwalker.walk("cat <a b").invocations[0].stdin.kind == "unknown"


# --- Rule 5 --------------------------------------------------------------------------


@pytest.mark.parametrize("unit", ["$[", "a=(", "${"])
def test_rule5_inputs_at_the_cap_are_walked(unit):
    command = (unit * 8192)[:8192]
    assert len(command.encode()) == 8192
    try:
        bashwalker.walk(command)
    except bashwalker.ParseRefused as exc:
        assert "input over" not in str(exc)


def test_rule5_over_cap_is_never_parsed(monkeypatch):
    calls = []
    monkeypatch.setattr(core, "parse_source", lambda data: calls.append(data))
    for command in ("a" * 8193, "é" * 4096 + "a"):
        with pytest.raises(bashwalker.ParseRefused, match="input over 8 KiB"):
            bashwalker.walk(command)
    assert calls == []


def test_rule5_work_and_depth_budgets():
    deep = "echo " + "$(echo " * 150 + ")" * 150
    chain = "echo " + "$(:)" * 1500
    with pytest.raises(bashwalker.ParseRefused, match="nesting too deep"):
        bashwalker.walk(deep)
    with pytest.raises(bashwalker.ParseRefused, match="work budget"):
        bashwalker.walk(chain)


def test_rule5_limits_are_the_callers():
    with pytest.raises(bashwalker.ParseRefused, match="input over 1 KiB"):
        bashwalker.walk("a" * 1025, bashwalker.Limits(max_input_bytes=1024))
    with pytest.raises(bashwalker.ParseRefused, match="work budget"):
        bashwalker.walk("a; b; c", bashwalker.Limits(max_work=3))
    assert len(bashwalker.walk("a; b; c").invocations) == 3


def test_refusals_never_quote_the_input(monkeypatch):
    secret = "s3cr3t\x1b"
    for command in (secret * 2000, "echo " + "$(echo " * 150 + secret + ")" * 150):
        with pytest.raises(bashwalker.ParseRefused) as info:
            bashwalker.walk(command)
        assert "s3cr3t" not in str(info.value)


# --- helpers -------------------------------------------------------------------------


def test_command_head_and_stdin_rewiring():
    def first(command):
        return bashwalker.walk(command).invocations[0]

    assert bashwalker.command_head(first("command -p exec <x")).text == "exec"
    assert bashwalker.command_head(first("PATH=x >/dev/null")) is None
    assert bashwalker.may_rewire_stdin(first("exec <x"))
    assert not bashwalker.may_rewire_stdin(first("exec"))
    assert bashwalker.may_rewire_stdin(first("$x"))
    assert bashwalker.may_rewire_stdin(first("builtin eval x"))
