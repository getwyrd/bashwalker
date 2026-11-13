"""The walker's facts, rule by rule (numbered as in nl-shell's ``policy-gate/v1``).

These tests check what the walker proves about a command, never whether the command is
allowed: that is the caller's policy. Each fact that is not proven must come back as the
worst case (``unknown`` stdin, a non-literal word, an untrusted tree, ``ParseRefused``).
"""

from __future__ import annotations

import itertools
import time

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
    # Forms bash runs that the grammar does not parse (checked against bash 5.3).
    "echo `echo \\`sudo id >&3\\``": "backtick substitution nested",
    "cat <<E\n`sudo id >&3`\nE": "backtick in an unquoted here-doc body",
    "declare -a 'x[$(touch m)]=1'": "subscript bash evaluates",
    "export \"x[$i]=1\"": "subscript bash evaluates",
    "declare -a >/dev/null 'x[$(touch m)]=1'": "subscript bash evaluates",
    "unset 'a[$(touch m)0]'": "unset operand with a subscript",
    "unset >/dev/null 'm[$(touch m)]'": "unset operand with a subscript",
    "unset -v a[$i]": "unset operand with a subscript",
    # Quoted text bash later reads as a variable reference evaluates its subscript
    # (checked against bash 5.3; each runs `touch`).
    "printf -v 'a[$(touch m)0]' x": "subscript with a substitution",
    "read 'a[$(touch m)0]' <<<x": "subscript with a substitution",
    "test -v 'a[$(touch m)0]'": "subscript with a substitution",
    "[[ -v 'a[$(touch m)0]' ]]": "subscript with a substitution",
    "let \"a[\\$(touch m)0]\"": "subscript with a substitution",
    "declare -n r='a[$(touch m)0]'; r=1": "subscript with a substitution",
    "i='a[$(touch m)]'; echo $((i))": "subscript with a substitution",
    "printf -v 'a[b[0]+$(touch m)0]' x": "subscript with a substitution",
    "declare -a 'x[b[0]+$(touch m)0]=1'": "subscript with a substitution",
    "a['$(touch m)0']=1": "subscript with a substitution",
    "v='x'; printf '%s' \"${v@P}\"": "@P",
    ": \"${a[@]@P}\" ${!p@P}": "@P",
    "command unset 'a[$(touch m)0]'": "unset operand with a subscript",
    ": $(( '$(touch m)0' ))": "arithmetic context",
    "\"unset\" 'a[$(touch m)0]'": "unset operand with a subscript",
    "printf -v $'a[\\444(touch m)0]' x": "subscript with a substitution",
    "PS4='$(touch m)'; set -x; :": "bash runs as code",
    "printf -v PS4 '%s' x; set -x; :": "bash runs as code",
    "printf -vPS4 x": "bash runs as code",
    "read PS4 <<<x": "bash runs as code",
    "declare PROMPT_COMMAND=x": "bash runs as code",
    "BASH_ENV=./e bash -c :": "bash runs as code",
    "command declare -n r=PS4; r=x; set -x; :": "nameref",
    "f() { local -n r=PS4; r=x; }": "nameref",
    "declare -gn r=PS4": "nameref",
    "printf -v $'a[$\\0ignored''(touch m)0]' x": "subscript with a substitution",
    "printf -v $'a[$\\c@x''(touch m)0]' x": "subscript with a substitution",
    "MAILPATH='/tmp/m?$(touch m)'": "bash runs as code",
    "FCEDIT=x fc": "bash runs as code",
    "printf -v $'PS\\064' x; set -x; :": "bash runs as code",
    "read $'P\\x534' <<<x": "bash runs as code",
    "for PS4 in x; do set -x; :; done": "bash runs as code",
    "select PS1 in a; do :; done": "bash runs as code",
    "read -aPS4 <<<x; set -x; :": "bash runs as code",
    "x='a['; x+='$(touch m)]'; : $((x))": "assigned text holding a substitution",
    "x=$'\\x24(touch m)'": "assigned text holding a substitution",
    "x='a[$'; x+='(touch m)0]'; : $((x))": "assigned text holding a substitution",
    'x="a[$"; x+="(touch m)0]"; : $((x))': "assigned text holding a substitution",
    'x="a[\\$"; x+="(touch m)0]"; : $((x))': "assigned text holding a substitution",
    'x=a\\$; y=$x"(touch m)0]"; : $((y))': "assigned text holding a substitution",
    "o=p; command \"-$o\" exec </tmp/payload; bash": "prefix with an option",
    "shopt -s expand_aliases\nalias x='exec <<<payload'\nx\nbash": "alias definition",
    "command alias x=y": "alias definition",
    "BASH_ALIASES[bash]='exec <<<x; bash'": "bash runs as code",
    "BASH_CMDS[ls]=/tmp/evil; ls": "bash runs as code",
    "hash -p /tmp/evil ls; ls": "hash -p",
    "printf -v $\"PS4\" x; set -x; :": "bash runs as code",
    "declare a['$(touch m)0']=1": "subscript with a substitution",
    "a[$'\\x24(touch m)0']=1": "subscript with a substitution",
    "printf -v $'a[\\x24(touch m)0]' x": "subscript with a substitution",
    "printf -v a$'\\x5b\\044(touch m)0]' x": "subscript with a substitution",
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
    for command in (
        "echo '?(a)' \"*(b)\" \\@\\(c\\)",
        "echo 'a\\\nb'",
        "cat <<'E'\nx\nE",
        "cat <<'E'\n`id`\nE",  # a quoted delimiter: bash runs nothing in the body
        "echo `id` $(id)",
        "declare -a 'x[1]=1' x[2]=2",
        "echo ${a[0]} ${a[$i]} \"${a[$i]}\"",
        "grep 'a[bc]' f; awk '{c[$1]++}'; sed -n 's/[$]//p' f",
        "[[ $x =~ ^a[0-9]+$ ]]",
        "a['key']=1; a[1]=2; m[\"$k\"]=3; printf '%s\\n' $'a[\\t]'",
        "echo $(( 1 + 2 )) $(( x * ${#y} ))",
        "echo \"$PS1\" ${PS4:-x}; MYPS4=1",
        "x=$(date); y=\"$(id -u)\"; z=`pwd`; w=${HOME}",
        "x=$HOME; y=\"$x/b\"; z=\"${a[0]}$1$@$?\"",
    ):
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
    assert stdin_of("a | b <f") == {"a": ("terminal", None), "b": ("unknown", None)}
    assert stdin_of("curl x > >(sh)")["sh"][0] == "pipe"
    assert stdin_of("cat <<E > >(sudo tee /x)\nx\nE")["sudo"][0] == "pipe"
    assert stdin_of("f() { sudo tee /x; }; cat <<E | f\nx\nE")["sudo"][0] == "unknown"
    assert stdin_of("f() { sh; }; curl x | f")["sh"][0] == "unknown"
    assert stdin_of("cat 0>&1")["cat"][0] == "unknown"
    assert stdin_of("cat 0>&-")["cat"][0] == "unknown"
    assert stdin_of("bash <<<'rm -rf ~'")["bash"] == ("literal", "rm -rf ~\n")
    # bash appends a newline to every here-string, also an empty one or one that ends in
    # a newline.
    assert stdin_of("cat <<<''")["cat"] == ("literal", "\n")
    assert stdin_of("cat <<<$'x\\n'")["cat"][0] == "unknown"  # $'…' is not literal
    assert stdin_of("cat <<<'x\n'")["cat"] == ("literal", "x\n\n")
    assert stdin_of("cat <<'E'\n$x\nE")["cat"] == ("literal", "$x\n")
    assert stdin_of("cat <<E\nplain\nE")["cat"] == ("literal", "plain\n")
    # A compound command's commands share its feed, so none of them is proven to read
    # all of it (bash 5.3: `{ read -r -N 1 s; bash; } <<<'#printf X'` runs `printf`).
    # The grammar reads a here-doc on a compound command; a here-string there is a syntax
    # error to it (an untrusted tree), so both forms end up unknown.
    for feed in ("<<'E'\n#printf X\nE", "<<E\n#printf X\nE", "<<<'#printf X'"):
        for body in (
            "{ read -r -N 1 skipped; bash; }",
            "{ bash; }",
            "(bash)",
            "for i in 1 2; do bash; done",
            "while read -r l; do bash; done",
            "if true; then bash; fi",
        ):
            command = f"{body} {feed}"
            assert stdin_of(command)["bash"][0] == "unknown", command
    assert not bashwalker.walk("{ bash; } <<'E'\nx\nE").untrusted  # the here-doc parses
    assert stdin_of("{ cat; } <f")["cat"] == ("unknown", None)
    assert stdin_of("cat <<E\n$x\nE")["cat"][0] == "unknown"
    assert stdin_of("cat <<-E\n\t$(rm x)\nE")["cat"][0] != "literal"
    assert stdin_of("cat")["cat"] == ("terminal", None)
    assert stdin_of("cat <$f")["cat"][0] == "unknown"
    assert stdin_of("cat <&3")["cat"][0] == "unknown"
    assert stdin_of("cat <>f")["cat"][0] == "unknown"
    # `<path` proves no stdin: what a path names is a run-time fact (bash 5.3 with
    # /tmp/x -> /dev/stdin: `echo piped | cat </tmp/x` prints `piped`).
    for path in ("f", "/tmp/x", "/dev/stdin", "/proc/self/fd/0", "../x", "self/fd/4"):
        assert stdin_of(f"echo x | cat <{path}")["cat"] == ("unknown", None), path
    assert stdin_of("{ sudo tee /etc/y; } </tmp/x")["sudo"] == ("unknown", None)
    assert stdin_of("exec </tmp/x; sudo tee /etc/y")["sudo"][0] == "unknown"
    assert stdin_of("while :; do cat; exec <x; done")["cat"][0] == "unknown"
    assert stdin_of("command exec <x; cat")["cat"][0] == "unknown"
    assert stdin_of("eval x; cat")["cat"][0] == "unknown"
    assert stdin_of("$x <f; cat")["cat"][0] == "unknown"
    assert stdin_of("trap 'exec <<<payload' DEBUG; cat")["cat"][0] == "unknown"
    assert stdin_of("exec; cat")["cat"] == ("terminal", None)
    # A background job reads /dev/null without job control (bash 5.3 `-c`), and is
    # stopped on a terminal read with it.
    assert stdin_of("cat & wait") == {"cat": ("unknown", None), "wait": ("terminal", None)}
    assert stdin_of("a | b & c")["a"][0] == "unknown"
    assert stdin_of("{ cat; } &")["cat"][0] == "unknown"
    assert stdin_of("cat <<<x &")["cat"] == ("literal", "x\n")  # its own redirect counts
    # A builtin that runs shell code from an option may rewire stdin like `eval`.
    for command in ("mapfile -C 'trap x DEBUG' -c 1 a; cat", "readarray -tC f a; cat", "bind -x '\"\\C-x\":f'; cat", "mapfile $o a; cat"):
        assert stdin_of(command)["cat"][0] == "unknown", command
    assert stdin_of("mapfile -t a; cat")["cat"] == ("terminal", None)
    # `fc` re-runs history lines in the current shell (interactive bash 5.3).
    assert stdin_of("fc -s; cat")["cat"][0] == "unknown"
    assert stdin_of("alias x=y; cat")["cat"][0] == "unknown"
    assert not bashwalker.walk("alias").untrusted  # listing defines nothing
    # A rewiring command is not exempt: an earlier one rewires it too (bash 5.3:
    # `exec </x; exec bash >/dev/null` runs /x).
    walked = bashwalker.walk("exec </tmp/payload; exec bash >/dev/null")
    assert [i.stdin.kind for i in walked.invocations] == ["unknown", "unknown"]
    assert stdin_of("PATH=x >/dev/null")[""][0] == "unknown"  # untrusted (MISSING)


def test_rule3_path_stdin_keeps_its_redirect():
    # The stdin is unknown, but the redirect stays for a caller that resolves the path
    # when the command runs. Only fd 0 is stdin.
    assert stdin_of("cat 1<f")["cat"] == ("terminal", None)
    (invocation,) = bashwalker.walk("cat <self/fd/4").invocations
    assert invocation.stdin.kind == "unknown"
    assert [(r.operator, r.target.text) for r in invocation.redirects] == [("<", "self/fd/4")]


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
    # `&>` and `&>>` take no descriptor: a number or `{name}` right before them is an
    # argument (bash 5.3: `printf "<%s>" 0&>out` writes `<0>`).
    for token in ("0", "2", "{fd}"):
        for op in ("&>", "&>>"):
            assert words(f"rm {token}{op}f") == (["rm", token], [(None, op)]), (token, op)
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
    # `$'…'` text is decoded as bash decodes it; the word stays non-literal.
    assert bashwalker.lex_word("$'PS\\064'") == ("PS4", frozenset({"expansion"}))
    assert bashwalker.lex_word("a$'\\x2f'b") == ("a/b", frozenset({"expansion"}))
    assert bashwalker.lex_word("$'it\\'s'")[0] == "it's"
    assert bashwalker.lex_word('$"PS4"') == ("PS4", frozenset({"locale translation"}))


def test_declaration_operands_after_a_redirect():
    walked = bashwalker.walk("export >/dev/null 'SUDO_PROMPT=x' B=1")
    # bash 5.3 assigns both; the one after the redirect is recovered from under it.
    assert sorted((a.name, a.role) for a in walked.assignments) == [
        ("B", "declaration"),
        ("SUDO_PROMPT", "declaration"),
    ]


def test_redirect_substitutions_read_the_earlier_redirects():
    # bash 5.3: `: <payload >"$(bash)"` runs payload in bash.
    walked = bashwalker.walk('echo x | : </tmp/payload >"$(bash)"')
    inner = next(i for i in walked.invocations if i.words[0].text == "bash")
    assert inner.stdin.kind == "unknown"  # not the pipe: the earlier redirect replaced it
    walked = bashwalker.walk('echo x | { :; } </tmp/payload >"$(bash)"')
    inner = next(i for i in walked.invocations if i.words[0].text == "bash")
    assert inner.stdin.kind == "unknown"
    # Words are expanded before any redirect: a word the grammar put after a redirect
    # target reads the command's stdin (bash 5.3: `: </x >/dev/null "$(bash)"` runs what
    # is piped in, not /x).
    walked = bashwalker.walk('echo x | : </tmp/payload >/dev/null "$(bash)"')
    inner = next(i for i in walked.invocations if i.words[0].text == "bash")
    assert inner.stdin.kind == "pipe"
    # A literal feed is not passed into a substitution in a later redirect: its commands
    # share it (bash 5.3: `read -N 1` takes `#`, then `bash` runs the rest).
    for command in (
        ": <<<'#printf X' >\"$(read -r -N 1 s; bash; printf /dev/null)\"",
        ": <<'E' >\"$(read -r -N 1 s; bash; printf /dev/null)\"\n#printf X\nE",
    ):
        assert stdin_of(command)["bash"][0] == "unknown", command
        assert stdin_of(command)["read"][0] == "unknown", command
    assert stdin_of('>"$(bash)" cat')["bash"] == ("terminal", None)  # nothing before it


def test_literal_stdin_read_by_a_later_redirect_is_unknown():
    # bash 5.3: the substitution reads `#` before bash reads the rest.
    command = "bash <<<'#echo X >&2' >\"$(read -r -N 1 s; printf /dev/null)\""
    assert stdin_of(command)["bash"][0] == "unknown"
    assert stdin_of("bash <<<'#echo X' >/dev/null")["bash"] == ("literal", "#echo X\n")
    # A here-string after another redirect is a syntax error to the grammar; the here-doc
    # forms parse. A substitution before the feed is applied reads the terminal; one in a
    # redirect after it (which the grammar hangs under the here-doc) may read the feed.
    before = "bash >\"$(printf /dev/null)\" <<'E'\nx\nE"
    assert stdin_of(before)["bash"] == ("literal", "x\n")
    after = "bash <<'E' >\"$(read -r -N 1 s; printf /dev/null)\"\n#echo X\nE"
    assert stdin_of(after)["bash"][0] == "unknown"
    assert stdin_of(after)["read"][0] == "unknown"
    assert stdin_of("cat <<E > >(sudo tee /x)\nx\nE")["cat"] == ("literal", "x\n")


def test_text_that_is_not_utf_8_is_walked():
    # A lone surrogate (surrogatepass) can reach the parser as bytes that a node splits.
    walked = bashwalker.walk("ls \udcff 'a[\udcff'")
    assert [w.text for w in walked.invocations[0].words][:1] == ["ls"]


def test_function_redirects_run_at_call_time():
    # bash 5.3: `f() { :; } <"$(cat >m)"; echo piped | f` writes `piped` to m.
    walked = bashwalker.walk('f() { :; } <"$(cat)"; printf x | f')
    cat = next(i for i in walked.invocations if i.words[0].text == "cat")
    assert (cat.stdin.kind, cat.in_function) == ("unknown", True)


def test_quoted_substitutions_in_arithmetic_are_untrusted():
    # bash 5.3 runs `touch` in each; the grammar reads only the first without an error.
    for command in (
        ": $(( '$(touch m)0' ))",
        ": $(( $'\\x24(touch m)0' ))",
        "(( $'\\x24(touch m)0' ))",
        "for (( i='$(touch m)0'; 0; )); do :; done",
    ):
        assert bashwalker.walk(command).untrusted, command


def test_declarations_behind_command_and_builtin():
    # bash 5.3 performs these assignments; the grammar parses them as plain commands.
    for command, name in (
        ("command export 'PATH=/x'", "PATH"),
        ("builtin readonly 'X=y'", "X"),
        ("command -p declare Y=z", "Y"),
        ("\"export\" 'PATH=/x'", "PATH"),
        ("\\readonly X=y", "X"),
        ("ex''port 'PATH=/x'", "PATH"),
    ):
        walked = bashwalker.walk(command)
        assert [(a.name, a.role) for a in walked.assignments] == [(name, "declaration")], command
    assert bashwalker.walk("command declare -a 'x[$(touch m)]=1'").untrusted
    assert bashwalker.walk("echo export 'PATH=/x'").assignments == []  # not a prefix
    # `command -v`/`-V` only look a command up (bash 5.3 leaves PATH alone).
    for command in ("command -v export PATH=/x", "command -pV export PATH=/x", "command -V unset 'a[$i]'"):
        walked = bashwalker.walk(command)
        assert walked.assignments == [], command
        assert bashwalker.command_head(walked.invocations[0]) is None, command
    assert bashwalker.command_head(bashwalker.walk("command -p ls").invocations[0]).text == "ls"
    assert not bashwalker.walk("export -n X").untrusted  # removes the export: no nameref
    # `-p`, `-f`, `-F` only display (bash 5.3 leaves PATH alone).
    for command in ("declare -p PATH=/x", "\"declare\" -p 'PATH=/x'", "typeset -f f", "local -Fp X=1"):
        assert bashwalker.walk(command).assignments == [], command
    assert [a.name for a in bashwalker.walk("declare -x X=1").assignments] == ["X"]
    # Options end at the first operand or `--` (bash 5.3: `declare PATH=/x -p` assigns).
    assert [a.name for a in bashwalker.walk("\"declare\" PATH=/x -p").assignments] == ["PATH"]
    assert [a.name for a in bashwalker.walk("declare -- -p PATH=/x").assignments] == ["PATH"]
    assert bashwalker.walk("\"declare\" +p 'PATH=/x'").assignments == []  # +p displays too
    # `+f`/`+F` turn an attribute off and still assign (bash 5.3).
    for option in ("+f", "+F"):
        assert [a.name for a in bashwalker.walk(f"declare {option} PATH=/x").assignments] == ["PATH"]
    # An option the walker cannot read may assign: X stays, and `"$o"` is an operand it
    # cannot name.
    assert [a.name for a in bashwalker.walk("declare \"$o\" X=1").assignments] == ["X", ""]


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
    walked = bashwalker.walk("echo x 2>")  # a MISSING target
    assert [r.readable for r in walked.redirects] == [False]
    assert walked.untrusted


def test_words_after_a_redirect_target_stay_operands():
    # tree-sitter-bash puts every word after a file redirect's operator under the
    # redirect; bash takes the first as the target and passes the rest to the command
    # (checked against bash 5.3: `cat <a b` reads `a` and prints `b`).
    def facts(command):
        walked = bashwalker.walk(command)
        (invocation,) = walked.invocations
        return (
            [w.text for w in invocation.words],
            [(r.descriptor, r.operator, r.target.text, r.display) for r in invocation.redirects],
            invocation.stdin.kind,
            walked.untrusted,
        )

    assert facts("cat <a b") == (["cat", "b"], [(None, "<", "a", "<a")], "unknown", ())
    assert facts("printf x >out y") == (["printf", "x", "y"], [(None, ">", "out", ">out")], "terminal", ())
    assert facts('cat <a"b" c d') == (["cat", "c", "d"], [(None, "<", "ab", '<a"b"')], "unknown", ())
    assert facts("echo >a b 2>c d")[0] == ["echo", "b", "d"]
    # The case a guard on `git push` must see: the refspec is not hidden by a redirect.
    assert facts("git push origin >/dev/null HEAD:main")[0] == ["git", "push", "origin", "HEAD:main"]
    assert [w.text for w in bashwalker.walk("sudo rm >/dev/null -rf /").words] == ["sudo", "rm", "-rf", "/"]
    # With no simple command to take the words (a syntax error in bash), the tree is
    # untrusted.
    walked = bashwalker.walk("{ cat; } <a b")
    assert any("no command to take them" in f for f in walked.untrusted)
    assert walked.invocations[0].stdin.kind == "unknown"


# --- Rule 5 --------------------------------------------------------------------------


@pytest.mark.parametrize("unit", ["$[", "a=(", "${"])
def test_rule5_inputs_at_the_cap_are_walked(unit):
    command = (unit * 8192)[:8192]
    assert len(command.encode()) == 8192
    start = time.monotonic()
    try:
        bashwalker.walk(command)
    except bashwalker.ParseRefused as exc:
        assert "input over" not in str(exc)
    # tree-sitter-bash's parse time grows with the square of the input: the cap bounds it.
    assert time.monotonic() - start < 5.0


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
