"""bashwalker's walker: a bash command line in, proven facts per simple command out.

It parses a command with the pinned tree-sitter-bash and walks the tree with one handler
per named node kind of the pinned grammar (``HANDLERS``). Each simple command becomes an
``Invocation``: its words, assignments, redirects and where its stdin comes from. What a
command is *allowed* to do is the caller's policy; this module only says what it *is*.

One principle runs through this module: **nothing is proven until it is proven**. Every
fact it records (the tree is right, a node was walked, a word is literal, stdin comes from
X) starts as not proven, and becomes proven only through the short lists of forms below.
Anything else is reported as the worst case.

The rules are numbered as in nl-shell's ``policy-gate/v1`` spec, where this walker comes
from. Rule 4 there (which redirects are safe) is policy and stays with the caller; this
module records the redirect facts that rule needs.

- Rule 1 (``untrusted_features``): the tree is trusted only with no ``ERROR`` or
  ``MISSING`` node and none of the features tree-sitter-bash reads differently from bash.
- Rule 2 (``walk``): every named node is visited exactly once, and every ``command``,
  ``declaration_command`` and ``unset_command`` gives exactly one invocation. Both are
  checked against the tree on every walk; a miss is a ``ParseRefused``.
- Rule 3 (``Stdin``, ``lex_word``): stdin sources and the literal flag are proven only
  through the forms listed there; anything else is ``unknown`` / not literal.
- Rule 5 (``Limits``): input over ``max_input_bytes`` is refused before it is parsed, and
  the walk has a total-work budget (``max_work`` nodes, ``max_depth`` levels).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace

import tree_sitter
import tree_sitter_bash

# Rule 5 defaults. tree-sitter-bash's parse time grows with the square of the input, which
# is why the size cap is checked before parsing.
MAX_INPUT_BYTES = 8 * 1024
MAX_WORK = 4096
MAX_DEPTH = 100


@dataclass(frozen=True)
class Limits:
    """Rule 5: the bounds one ``walk`` runs under."""

    max_input_bytes: int = MAX_INPUT_BYTES
    max_work: int = MAX_WORK
    max_depth: int = MAX_DEPTH


DEFAULT_LIMITS = Limits()

LANGUAGE = tree_sitter.Language(tree_sitter_bash.language())

ERROR_KIND = "ERROR"
SIMPLE_KINDS = ("command", "declaration_command", "unset_command")
REDIRECT_KINDS = ("file_redirect", "heredoc_redirect", "herestring_redirect")
# Anonymous tokens that are redirect operators.
REDIRECT_OPERATORS = frozenset(
    (">", ">>", ">|", "&>", "&>>", "<>", ">&", "<&", ">&-", "<&-", "<", "<<", "<<-", "<<<")
)
INPUT_OPERATORS = ("<", "<&", "<&-")  # default descriptor 0
# Operators that take no descriptor: bash passes a number written right before them to the
# command (`printf %s 0&>out` writes `0`).
NO_DESCRIPTOR_OPERATORS = ("&>", "&>>")
_PLAIN_DELIMITER = re.compile(r"[A-Za-z0-9_]+")
_QUOTED_DELIMITER = re.compile(r"'[^']*'|\"[^\"\\$`]*\"")
LOW_FD = ("0", "1", "2")


class ParseRefused(Exception):
    """The walker could not prove its facts about the command (Rule 2 or Rule 5). The
    message is fixed text: it never quotes the input. Callers treat the command as the
    worst case."""


def named_kinds() -> tuple[str, ...]:
    """Every named node kind of the pinned grammar, plus ``ERROR``."""
    kinds = {
        LANGUAGE.node_kind_for_id(i)
        for i in range(LANGUAGE.node_kind_count)
        if LANGUAGE.node_kind_is_named(i) and LANGUAGE.node_kind_is_visible(i)
    }
    kinds.add(ERROR_KIND)
    return tuple(sorted(kinds))


def parse_source(source: bytes) -> tree_sitter.Tree:
    """Parse ``source`` with the pinned grammar (the one entry point to the parser)."""
    return tree_sitter.Parser(LANGUAGE).parse(source)


# --- facts ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Stdin:
    """Where a simple command's standard input comes from (Rule 3).

    ``kind`` is one of:

    - ``terminal``: a command outside any function body and outside ``>(…)``, with no
      redirect touching fd 0, first in its pipeline or standing alone;
    - ``pipe``: a later stage of a pipeline, or the command inside ``>(…)``;
    - ``file``: ``<`` (or ``0<``) from a literal path; ``value`` is the path and ``via``
      the redirect that names it, so a caller that rejects that redirect can treat this
      stdin as ``unknown``;
    - ``literal``: the simple command's own here-string whose word is literal (``value``
      is the word with the newline bash appends), or its own here-doc whose delimiter is
      quoted (or unquoted with no ``$``, `` ` `` or ``\\`` in its body; ``value`` is the
      body). A literal feed on a compound command gives the commands inside ``unknown``:
      they share it, and one may consume part of it before another reads;
    - ``unknown``: everything else (function bodies, ``0>&N``, ``0>&-``, a stdin
      redirect the walker cannot place, any command in untrusted text).

    Consumers MUST treat ``unknown`` as the worst case for each of their rules: as a pipe
    where a pipe is the danger, and as the terminal where the terminal is.
    """

    kind: str
    value: str | None = None
    via: Redirect | None = field(default=None, compare=False, repr=False)


TERMINAL = Stdin("terminal")
PIPE = Stdin("pipe")
UNKNOWN = Stdin("unknown")


@dataclass(frozen=True)
class Word:
    """One shell word: ``text`` after quote removal, ``literal`` when bash would expand
    nothing in it (Rule 3), ``source`` as written."""

    text: str
    literal: bool
    source: str


@dataclass(frozen=True)
class Assignment:
    """One ``variable_assignment`` node. ``role`` is ``prefix`` (``VAR=x cmd``),
    ``declaration`` (inside ``export``/``declare``/…) or ``standalone``."""

    name: str
    value: Word | None
    role: str


@dataclass(frozen=True)
class Redirect:
    """One redirect, as written. Whether it is allowed is the caller's policy.

    ``kind`` is ``file_redirect``, ``heredoc_redirect``, ``herestring_redirect``, or
    ``loose``: a redirect operator the tree did not attach (inside an ``ERROR`` node, or
    ``<``/``>`` inside ``[ ]``, which bash performs as a redirection; ``in_test`` marks
    the latter). A loose redirect has no proven descriptor or target.
    """

    kind: str
    descriptor: str | None
    operator: str
    target: Word | None
    readable: bool  # False when the parser could not read the target (MISSING, several)
    output: bool  # writes a descriptor other than stdin (file redirects only)
    feed: Stdin | None  # the stdin a here-doc/here-string gives
    display: str  # operator and target as written (to be escaped before display)
    heredoc_operator: bool  # its operator bytes are an unquoted `<<` in the text
    start: int
    relative: bool = False  # a file target placed by the cwd or `~` (not a dup of 0-2)
    in_test: bool = False  # a loose `<`/`>` inside `[ ]`


@dataclass(frozen=True)
class Invocation:
    """One simple command handed to the command layer."""

    kind: str  # command | declaration | unset
    words: tuple[Word, ...]
    assignments: tuple[Assignment, ...]
    redirects: tuple[Redirect, ...]
    stdin: Stdin
    in_function: bool

    @property
    def command_word(self) -> Word | None:
        return self.words[0] if self.words else None


@dataclass
class Walk:
    """Everything the walk proved about one command line."""

    untrusted: tuple[str, ...]
    invocations: list[Invocation] = field(default_factory=list)
    assignments: list[Assignment] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    redirects: list[Redirect] = field(default_factory=list)
    process_substitutions: int = 0
    words: list[Word] = field(default_factory=list)


# --- Rule 3: the literal flag --------------------------------------------------------


def lex_word(source: str) -> tuple[str, frozenset[str]]:
    """Quote-remove ``source`` as bash would and say what bash would expand in it.

    Returns the text and the set of causes that make it non-literal (empty means
    literal). ``tilde`` alone, at the very start and followed by ``/`` or nothing, is
    reported as ``leading-tilde``, so a caller may allow it in a redirect target.
    """
    out: list[str] = []
    causes: set[str] = set()
    i, n = 0, len(source)
    while i < n:
        c = source[i]
        if c == "\\":
            if i + 1 < n:
                if source[i + 1] == "\n":
                    causes.add("line continuation")
                else:
                    out.append(source[i + 1])
                i += 2
            else:
                out.append(c)
                i += 1
            continue
        if c == "'":
            end = source.find("'", i + 1)
            if end < 0:
                causes.add("unclosed quote")
                out.append(source[i + 1 :])
                break
            out.append(source[i + 1 : end])
            i = end + 1
            continue
        if c == '"':
            i += 1
            closed = False
            while i < n:
                d = source[i]
                if d == '"':
                    closed = True
                    i += 1
                    break
                if d == "\\" and i + 1 < n and source[i + 1] in '$`"\\\n':
                    if source[i + 1] == "\n":
                        causes.add("line continuation")
                    else:
                        out.append(source[i + 1])
                    i += 2
                    continue
                if d in "$`":
                    causes.add("expansion")
                out.append(d)
                i += 1
            if not closed:
                causes.add("unclosed quote")
            continue
        if c in "$`":
            causes.add("expansion")
        elif c in "*?[":
            causes.add("glob")
        elif c in "{}":
            causes.add("brace")
        elif c in "()":
            causes.add("pattern or substitution")
        elif c in " \t\n;&|<>":
            causes.add("metacharacter")
        elif c == "~":
            if i == 0:
                follows = source[1:2]
                causes.add("leading-tilde" if follows in ("", "/") else "tilde")
            elif source[i - 1] in "=:":
                causes.add("tilde")
        out.append(c)
        i += 1
    return "".join(out), frozenset(causes)


def make_word(source: str) -> Word:
    text, causes = lex_word(source)
    return Word(text=text, literal=not causes, source=source)


def _is_relative_target(operator: str, target: Word | None) -> bool:
    """A file target that the cwd or ``~`` places (not a dup or close of 0-2)."""
    if target is None:
        return False
    if operator in (">&", "<&") and re.fullmatch(r"[012]-?|-", target.text):
        return False
    return target.source.startswith("~") or not target.text.startswith("/")


def _is_output(descriptor: str | None, operator: str, kind: str) -> bool:
    if kind != "file_redirect":
        return False
    if operator in INPUT_OPERATORS and descriptor in (None, "0"):
        return False
    return True


# --- Rule 1: trusting the tree -------------------------------------------------------


def _iter_nodes(root: tree_sitter.Node) -> Iterator[tree_sitter.Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def _masks(root: tree_sitter.Node, size: int) -> tuple[bytearray, bytearray]:
    """Two byte masks over the source: ``single`` (inside single or ANSI-C quotes) and
    ``quoted`` (also inside double-quoted text, here-doc text and comments)."""
    single = bytearray(size)
    quoted = bytearray(size)
    bodies, spans = [], []
    for node in _iter_nodes(root):
        if node.type == "heredoc_body":
            bodies.append(node)
        elif node.type in ("raw_string", "ansi_c_string"):
            spans.append((node, True))
        elif node.type in ("string_content", "heredoc_content", "comment"):
            spans.append((node, False))
    for body in bodies:
        width = body.end_byte - body.start_byte
        quoted[body.start_byte : body.end_byte] = b"\x01" * width
        for child in body.named_children:
            if child.type != "heredoc_content":
                width = child.end_byte - child.start_byte
                quoted[child.start_byte : child.end_byte] = bytes(width)
    for node, is_single in spans:
        width = node.end_byte - node.start_byte
        quoted[node.start_byte : node.end_byte] = b"\x01" * width
        if is_single:
            single[node.start_byte : node.end_byte] = b"\x01" * width
    return single, quoted


def _escaped(source: bytes, i: int) -> bool:
    count = 0
    while i - count - 1 >= 0 and source[i - count - 1] == 0x5C:
        count += 1
    return count % 2 == 1


def _heredoc_runs(source: bytes) -> list[tuple[int, int]]:
    """Every run of exactly two ``<`` in the text: what bash reads as a here-doc
    operator wherever ``<<`` is an operator at all."""
    runs, i, n = [], 0, len(source)
    while i < n:
        if source[i] == 0x3C:
            j = i
            while j < n and source[j] == 0x3C:
                j += 1
            if j - i == 2:
                runs.append((i, j))
            i = j
        else:
            i += 1
    return runs


def _bracket_redirects(node: tree_sitter.Node) -> list[tree_sitter.Node]:
    """The redirect-operator tokens inside a single-bracket test (``[ x > y ]``).
    tree-sitter-bash reads them as test operators; bash runs ``[`` as a command, so for
    bash they are redirections. ``[[ … ]]`` compares strings and is not affected."""
    if node.type != "test_command" or not node.children or node.children[0].type != "[":
        return []
    return [n for n in _iter_nodes(node) if not n.is_named and n.type in REDIRECT_OPERATORS]


def _quoted_heredoc(body: tree_sitter.Node) -> bool:
    """Whether a here-doc body's delimiter is quoted, so bash expands nothing in it."""
    redirect = body.parent
    if redirect is None:
        return False
    for child in redirect.children:
        if child.type == "heredoc_start":
            return child.text[:1] in (b"'", b'"')
    return False


def untrusted_features(tree: tree_sitter.Tree, source: bytes) -> tuple[str, ...]:
    """Rule 1. The features that make the tree untrusted (empty means trusted)."""
    root = tree.root_node
    found: list[str] = []

    def note(feature: str) -> None:
        if feature not in found:
            found.append(feature)

    heredocs = []
    for node in _iter_nodes(root):
        if node.is_error or node.type == ERROR_KIND:
            note("syntax error")
        if node.is_missing:
            note("missing token")
        if node.type == "heredoc_start":
            text = node.text.decode("utf-8", "surrogatepass")
            if not (_PLAIN_DELIMITER.fullmatch(text) or _QUOTED_DELIMITER.fullmatch(text)):
                note("here-doc delimiter is not a plain or fully quoted word")
        if node.type == "heredoc_redirect":
            heredocs.append(node)
        # tree-sitter-bash parses neither of these backtick forms; bash runs both
        # (nl-shell#213).
        if node.type == "command_substitution" and node.text.startswith(b"`"):
            if b"\\`" in node.text:
                note("backtick substitution nested in a backtick substitution")
        if node.type == "heredoc_body" and b"`" in node.text and not _quoted_heredoc(node):
            note("backtick in an unquoted here-doc body")
        if not node.is_named and node.type == "<<-":
            note("here-doc with <<-")
        if _bracket_redirects(node):
            note("'<' or '>' inside [ ], which bash reads as a redirection")
    single, quoted = _masks(root, len(source))
    lines: dict[int, int] = {}
    for start, _ in _heredoc_runs(source):
        if quoted[start] or _escaped(source, start):
            continue
        if source[start + 2 : start + 3] == b"-":
            note("here-doc with <<-")
        line = source.count(b"\n", 0, start)
        lines[line] = lines.get(line, 0) + 1
    if any(count > 1 for count in lines.values()):
        note("more than one here-doc on one line")
    if sum(lines.values()) != len(heredocs):
        note("here-doc the parser did not place")
    for i in range(len(source) - 1):
        pair = source[i : i + 2]
        if pair == b"\\\n" and not single[i]:
            note("backslash-newline")
        elif pair[1:] == b"(" and pair[:1] in (b"?", b"*", b"+", b"@", b"!"):
            if not quoted[i] and not _escaped(source, i):
                note("extglob pattern")
        elif pair == b"${" and not single[i]:
            if source[i + 2 : i + 3] in (b" ", b"\t", b"\n", b"|"):
                note("bash 5.3 ${ } substitution")
    return tuple(found)


# --- Rule 2: the walk ----------------------------------------------------------------


@dataclass(frozen=True)
class Ctx:
    stdin: Stdin
    in_function: bool = False
    role: str | None = None  # how a variable_assignment child is used


Handler = Callable[["Walker", tree_sitter.Node, Ctx, int, tuple], object]


class Walker:
    def __init__(self, source: bytes, layer: Walk, limits: Limits = DEFAULT_LIMITS) -> None:
        self.source = source
        self.layer = layer
        self.limits = limits
        self.visits: dict[tuple[int, int, int], int] = {}
        self.work = 0
        self.heredoc_runs = _heredoc_runs(source)
        # Words written after a file redirect's target (`cat <a b`): tree-sitter-bash puts
        # them under the redirect, bash passes them to the command. Keyed by the
        # redirect's id until the simple command that owns the redirect takes them.
        self.operands: dict[int, list[tuple[int, int]]] = {}

    def note_untrusted(self, feature: str) -> None:
        """Rule 1, for a feature only the walk can see."""
        if feature not in self.layer.untrusted:
            self.layer.untrusted += (feature,)

    def text(self, node: tree_sitter.Node) -> str:
        return self.source[node.start_byte : node.end_byte].decode("utf-8", "surrogatepass")

    def span(self, start: int, end: int) -> str:
        return self.source[start:end].decode("utf-8", "surrogatepass")

    def visit(self, node: tree_sitter.Node, ctx: Ctx, depth: int, bound: tuple = ()):
        self.work += 1
        if self.work > self.limits.max_work:
            raise ParseRefused("work budget exceeded")
        if depth > self.limits.max_depth:
            raise ParseRefused("nesting too deep")
        kind = ERROR_KIND if node.is_error else node.type
        handler = HANDLERS.get(kind)
        if handler is None:
            raise ParseRefused("unhandled node kind")
        key = (node.id, node.start_byte, node.end_byte)
        self.visits[key] = self.visits.get(key, 0) + 1
        return handler(self, node, ctx, depth, bound)

    # Descriptor written right before a redirect operator that the tree did not attach
    # (`cat 0>&-` parses as the argument `0` and the redirect `>&-`).
    def adjacent_token(self, start: int) -> tuple[int, str] | None:
        i = start
        while i > 0 and self.source[i - 1] not in b" \t\n;&|()<>":
            i -= 1
        if i == start:
            return None
        return i, self.span(i, start)

    def in_heredoc_run(self, start: int) -> bool:
        """True when ``start`` is inside a ``<<`` run with no descriptor in
        front of it, or a literal 0-2 (``3<<E`` and ``{x}<<E`` are never exempt)."""
        for a, b in self.heredoc_runs:
            if a <= start < b:
                token = self.adjacent_token(a)
                return token is None or token[1] in LOW_FD
        return False


def _children(walker: Walker, node, ctx: Ctx, depth: int, bound: tuple = ()) -> None:
    if bound:
        ctx = _apply_compound(walker, bound, ctx, depth)
    for child in node.named_children:
        walker.visit(child, ctx, depth + 1)


def _apply_compound(walker: Walker, bound: tuple, ctx: Ctx, depth: int) -> Ctx:
    """Redirects on a compound command: record them, and let them set the stdin the
    commands inside inherit.

    A literal feed is never passed on: the commands inside share it, so one can consume
    part of it before the next reads (``{ read -N 1 s; bash; } <<<'#cmd'`` gives ``bash``
    ``cmd``), and a loop reads on where the last pass stopped. They get ``unknown``."""
    stdin = ctx.stdin
    for node in bound:
        for record in walker.visit(node, ctx, depth + 1):
            stdin = _stdin_after(record, stdin)
    if stdin.kind == "literal":
        stdin = UNKNOWN
    return replace(ctx, stdin=stdin)


def _stdin_after(record: Redirect, stdin: Stdin) -> Stdin:
    if record.kind in ("heredoc_redirect", "herestring_redirect"):
        if record.descriptor in (None, "0"):
            return record.feed or UNKNOWN
        if record.descriptor in LOW_FD:
            return stdin
        return UNKNOWN
    if record.descriptor is not None and not record.descriptor.isdigit():
        return UNKNOWN
    if record.descriptor is None:
        fd = "0" if record.operator in INPUT_OPERATORS or record.operator == "<>" else "1"
    else:
        fd = record.descriptor.lstrip("0") or "0"
    if fd != "0":
        return stdin
    if (
        record.operator == "<"
        and record.descriptor in (None, "0")
        and record.readable
        and record.target is not None
        and record.target.literal
        and not _may_alias_a_descriptor(record.target.text)
    ):
        return Stdin("file", record.target.text, via=record)
    return UNKNOWN


_SYSTEM_TREES = ("/dev", "/proc", "/sys")


def _may_alias_a_descriptor(path: str) -> bool:
    """A path under ``/dev``, ``/proc`` or ``/sys`` (``/dev/stdin``, ``/proc/self/fd/0``,
    ``/dev/tty``) can open a descriptor the shell already has, such as the pipe a command
    reads, so it proves no file. A ``..`` component can lead there too. A relative path
    is resolved against the cwd at run time, which the caller places (``Redirect.relative``
    on ``Stdin.via``)."""
    parts = path.split("/")
    if ".." in parts:
        return True
    if not path.startswith("/"):
        return False
    normal = "/" + "/".join(p for p in parts if p not in ("", "."))
    return any(normal == tree or normal.startswith(tree + "/") for tree in _SYSTEM_TREES)


def _error(walker: Walker, node, ctx: Ctx, depth: int, bound: tuple = ()) -> None:
    for child in node.children:
        loose = (not child.is_named and child.type in REDIRECT_OPERATORS) or (
            child.child_count == 0 and child.is_error
        )
        if loose:
            text = walker.text(child)
            if child.is_named and not any(c in text for c in "<>"):
                continue
            walker.layer.redirects.append(
                Redirect(
                    kind="loose",
                    descriptor=None,
                    operator=child.type,
                    target=None,
                    readable=False,
                    output=False,
                    feed=None,
                    display=text,
                    heredoc_operator=walker.in_heredoc_run(child.start_byte),
                    start=child.start_byte,
                )
            )
    _children(walker, node, ctx, depth, bound)


def _test_command(walker: Walker, node, ctx: Ctx, depth: int, bound: tuple = ()) -> None:
    """``[ … ]``: each ``<``/``>`` inside is a redirection bash would perform, with a
    target the tree does not give, so it is recorded as loose (Rule 1 also marks it)."""
    for token in _bracket_redirects(node):
        after = token.next_sibling
        end = after.end_byte if after is not None else token.end_byte
        walker.layer.redirects.append(
            Redirect(
                kind="loose",
                descriptor=None,
                operator=token.type,
                target=None,
                readable=False,
                output=False,
                feed=None,
                display=walker.span(token.start_byte, end),
                heredoc_operator=False,
                start=token.start_byte,
                in_test=True,
            )
        )
    _children(walker, node, ctx, depth, bound)


def _pipeline(walker: Walker, node, ctx: Ctx, depth: int, bound: tuple = ()) -> None:
    stages, later = [], False
    for child in node.children:
        if not child.is_named:
            if child.type in ("|", "|&"):
                later = True
            continue
        stages.append((child, later))
    # A trailing redirect on a pipeline belongs to its last stage, as in bash.
    last = max((i for i, (c, _) in enumerate(stages) if c.type != "comment"), default=-1)
    for i, (child, is_later) in enumerate(stages):
        stage_ctx = replace(ctx, stdin=PIPE) if is_later else ctx
        walker.visit(child, stage_ctx, depth + 1, bound if i == last else ())
    if bound and last < 0:
        _apply_compound(walker, bound, ctx, depth)


def _negated(walker: Walker, node, ctx: Ctx, depth: int, bound: tuple = ()) -> None:
    inner = node.named_children
    if bound and len(inner) == 1:
        walker.visit(inner[0], ctx, depth + 1, bound)
        return
    _children(walker, node, ctx, depth, bound)


def _redirected(walker: Walker, node, ctx: Ctx, depth: int, bound: tuple = ()) -> None:
    body = node.child_by_field_name("body")
    mine = tuple(c for c in node.named_children if body is None or c.id != body.id)
    redirects = tuple(c for c in mine if c.type in REDIRECT_KINDS)
    others = tuple(c for c in mine if c.type not in REDIRECT_KINDS)
    for other in others:
        walker.visit(other, ctx, depth + 1)
    if body is None:
        _apply_compound(walker, redirects + bound, ctx, depth)
        return
    walker.visit(body, ctx, depth + 1, redirects + bound)


def _simple(walker: Walker, node, ctx: Ctx, depth: int, bound: tuple = ()) -> None:
    kind = {"command": "command", "declaration_command": "declaration"}.get(
        node.type, "unset"
    )
    word_nodes: list = []  # name and argument children, named or not
    prefix: list = []
    redirect_nodes: list = list(bound)
    others: list = []
    unread: list = []  # walked, but not words (a zero-width MISSING command name)
    keyword = None
    seen_name = False
    has_name = False
    for i, child in enumerate(node.children):
        fname = node.field_name_for_child(i)
        if not child.is_named:
            if fname == "argument":
                word_nodes.append(child)
            elif keyword is None and kind != "command" and not seen_name:
                keyword = child
                seen_name = True
            continue
        if child.type in REDIRECT_KINDS:
            redirect_nodes.append(child)
        elif fname == "name" and child.end_byte == child.start_byte:
            # `PATH=x >/dev/null` parses with a MISSING command name: bash runs no
            # command there, so this is no name.
            unread.append(child)
            seen_name = True
        elif fname == "name":
            word_nodes.append(child)
            seen_name = True
            has_name = True
        elif child.type == "variable_assignment" and kind == "command" and not seen_name:
            prefix.append(child)
        elif fname == "argument" or kind != "command":
            word_nodes.append(child)
        else:
            others.append(child)
    redirect_nodes.sort(key=lambda n: n.start_byte)

    # Descriptors the tree left as a separate word (`cat 0>&-`). Only a token that is a
    # descriptor by the same test `_descriptor` uses is taken out of the words; any other
    # word written against a redirect (`rm -rf />/dev/null`) stays an argument.
    fd_tokens = set()
    for r in redirect_nodes:
        if r.child_by_field_name("descriptor") is not None:
            continue
        if _operator(r) not in NO_DESCRIPTOR_OPERATORS:
            token = walker.adjacent_token(r.start_byte)
            if token is not None and _is_descriptor_token(token[1]):
                fd_tokens.add((token[0], r.start_byte))
    fd_words = [w for w in word_nodes if (w.start_byte, w.end_byte) in fd_tokens]
    word_nodes = [w for w in word_nodes if (w.start_byte, w.end_byte) not in fd_tokens]

    # With no command word (`PATH=x >/dev/null`) the assignment is not a one-command
    # prefix: bash keeps it in the shell, so it is standalone.
    prefix_role = "prefix" if has_name or kind != "command" else "standalone"
    assignments = []
    for child in prefix:
        assignments.append(walker.visit(child, replace(ctx, role=prefix_role), depth + 1))
    role = "declaration" if kind == "declaration" else None
    for child in word_nodes:
        if child.is_named:
            result = walker.visit(child, replace(ctx, role=role), depth + 1)
            if isinstance(result, Assignment):
                assignments.append(result)
    if kind == "declaration":
        # An operand that is not one `variable_assignment` node is still read by bash
        # as `name=value` after quote removal (`export 'SUDO_PROMPT=x'`). Pieces with no
        # space between them are one bash word (`export S'UDO_PROMPT'=x`).
        operands: list[list] = []
        for child in sorted(word_nodes, key=lambda n: n.start_byte):
            if operands and operands[-1][-1].end_byte == child.start_byte:
                operands[-1].append(child)
            else:
                operands.append([child])
        for pieces in operands:
            if len(pieces) == 1 and pieces[0].type == "variable_assignment":
                continue
            operand, unsafe = _declared(walker.span(pieces[0].start_byte, pieces[-1].end_byte))
            if unsafe:
                walker.note_untrusted("declaration operand with a subscript bash evaluates")
            if operand is not None:
                assignments.append(operand)
                walker.layer.assignments.append(operand)
    for child in others + unread + [w for w in fd_words if w.is_named]:
        walker.visit(child, ctx, depth + 1)
    records: list[Redirect] = []
    for child in redirect_nodes:
        records.extend(walker.visit(child, ctx, depth + 1))

    # Words: tree-sitter splits some bash words in two (`$"x"`); join pieces with no
    # space between them, as bash does.
    words: list[Word] = []
    if keyword is not None:
        words.append(make_word(walker.text(keyword)))
    groups: list[list[int]] = []
    for child in sorted(word_nodes + others, key=lambda n: n.start_byte):
        if groups and groups[-1][1] == child.start_byte:
            groups[-1][1] = child.end_byte
        else:
            groups.append([child.start_byte, child.end_byte])
    for record in records:
        groups.extend([start, end] for start, end in walker.operands.pop(id(record), ()))
    groups.sort()
    for start, end in groups:
        words.append(make_word(walker.span(start, end)))
    if kind == "command" and not has_name:
        words.insert(0, Word(text="", literal=False, source=""))
    walker.layer.words.extend(words)

    stdin = ctx.stdin
    for record in records:
        stdin = _stdin_after(record, stdin)
    walker.layer.invocations.append(
        Invocation(
            kind=kind,
            words=tuple(words),
            assignments=tuple(a for a in assignments if a is not None),
            redirects=tuple(records),
            stdin=stdin,
            in_function=ctx.in_function,
        )
    )


_DECLARED = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)(\[[^\]]*\])?\+?=(.*)", re.S)
_NUMBER_SUBSCRIPT = re.compile(r"\[[0-9]+\]")


def _declared(source: str) -> tuple[Assignment | None, bool]:
    """A declaration operand that is not a ``variable_assignment`` node, as bash reads it
    after quote removal: ``export 'SUDO_PROMPT=x'`` assigns ``SUDO_PROMPT``. An operand
    whose name the walker cannot read (``export "$x"``) gives the name ``""``; a literal
    option or plain name (``-x``, ``A``) gives ``None``.

    The flag is True when the operand has a subscript other than a plain number. bash
    evaluates an indexed array's subscript after quote removal, so a quoted operand runs
    what the tree never parsed (``declare -a 'x[$(id)]=1'`` runs ``id``)."""
    word = make_word(source)
    match = _DECLARED.match(word.text)
    if match is not None:
        value = Word(text=match.group(3), literal=word.literal, source=source)
        subscript = match.group(2)
        unsafe = subscript is not None and not _NUMBER_SUBSCRIPT.fullmatch(subscript)
        return Assignment(name=match.group(1), value=value, role="declaration"), unsafe
    if word.literal:
        return None, False
    return Assignment(name="", value=None, role="declaration"), False


def _assignment(walker: Walker, node, ctx: Ctx, depth: int, bound: tuple = ()):
    name_node = node.child_by_field_name("name")
    value_node = node.child_by_field_name("value")
    if name_node is not None and name_node.type == "subscript":
        inner = name_node.child_by_field_name("name")
        name_node = inner if inner is not None else name_node
    name = walker.text(name_node) if name_node is not None else walker.text(node)
    value = make_word(walker.text(value_node)) if value_node is not None else None
    record = Assignment(name=name, value=value, role=ctx.role or "standalone")
    walker.layer.assignments.append(record)
    if value is not None:
        walker.layer.words.append(value)
    _children(walker, node, replace(ctx, role=None), depth, bound)
    return record


def _function(walker: Walker, node, ctx: Ctx, depth: int, bound: tuple = ()) -> None:
    name = node.child_by_field_name("name")
    body = node.child_by_field_name("body")
    start = name.start_byte if name is not None else node.start_byte
    end = body.start_byte if body is not None else node.end_byte
    shown = re.sub(r"\s*\(\s*\)\s*$", "", walker.span(start, end).strip())
    walker.layer.functions.append(shown)
    inner = replace(ctx, stdin=UNKNOWN, in_function=True, role=None)
    redirects = [c for c in node.named_children if c.type in REDIRECT_KINDS]
    for child in node.named_children:
        if child.type in REDIRECT_KINDS:
            continue
        walker.visit(child, inner, depth + 1)
    for child in list(bound) + redirects:
        walker.visit(child, ctx, depth + 1)


def _command_substitution(walker: Walker, node, ctx, depth, bound=()) -> None:
    _children(walker, node, replace(ctx, role=None), depth, bound)


def _process_substitution(walker: Walker, node, ctx, depth, bound=()) -> None:
    walker.layer.process_substitutions += 1
    opener = node.children[0].type if node.child_count else ""
    inner = replace(ctx, role=None, stdin=PIPE if opener == ">(" else ctx.stdin)
    _children(walker, node, inner, depth, bound)


_NUMBER_DESCRIPTOR = re.compile(r"[0-9]+")
# bash's `{varname}` redirect: an identifier, optionally with one non-empty subscript.
_NAMED_DESCRIPTOR = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]+\])?\}")


def _is_descriptor_token(text: str) -> bool:
    """Whether a token written right before a redirect operator is its descriptor, as
    bash reads it: ASCII digits (``0>&-``) or ``{name}`` / ``{name[subscript]}``
    (``{fd}>x``, ``{a[0]}>&-``). Anything else is an ordinary word, as in bash:
    ``echo secret>out`` keeps ``secret``, ``rm ١>x`` keeps ``١`` (not an ASCII digit) and
    ``rm {a,b}>x`` keeps ``{a,b}`` (brace expansion), all as arguments."""
    return bool(_NUMBER_DESCRIPTOR.fullmatch(text) or _NAMED_DESCRIPTOR.fullmatch(text))


def _descriptor(walker: Walker, node) -> str | None:
    child = node.child_by_field_name("descriptor")
    if child is not None:
        return walker.text(child)
    if _operator(node) in NO_DESCRIPTOR_OPERATORS:
        return None
    token = walker.adjacent_token(node.start_byte)
    if token is None or not _is_descriptor_token(token[1]):
        return None
    return token[1]


def _operator(node) -> str:
    for child in node.children:
        if not child.is_named and child.type in REDIRECT_OPERATORS:
            return child.type
    return ""


def _file_redirect(walker: Walker, node, ctx, depth, bound=()) -> list[Redirect]:
    _children(walker, node, replace(ctx, role=None), depth)
    descriptor = _descriptor(walker, node)
    operator = _operator(node)
    targets = node.children_by_field_name("destination")
    missing = any(t.is_missing or t.has_error for t in targets)
    # Destinations with no space between them are one bash word; the first such word is
    # the target and every later one is a word of the command (`cat <a b` reads `a` and
    # passes `b`). A close (`>&-`) has none.
    spans: list[list[int]] = []
    for t in targets:
        if spans and spans[-1][1] == t.start_byte:
            spans[-1][1] = t.end_byte
        else:
            spans.append([t.start_byte, t.end_byte])
    target = make_word(walker.span(*spans[0])) if spans else None
    readable = not missing
    op_node = next((c for c in node.children if c.type == operator), None)
    op_start = op_node.start_byte if op_node is not None else node.start_byte
    display_end = spans[0][1] if spans else node.end_byte
    record = Redirect(
        kind="file_redirect",
        descriptor=descriptor,
        operator=operator,
        target=target,
        readable=readable,
        output=_is_output(descriptor, operator, "file_redirect"),
        feed=None,
        display=(descriptor or "") + walker.span(op_start, display_end),
        heredoc_operator=walker.in_heredoc_run(op_start),
        start=node.start_byte,
        relative=readable and _is_relative_target(operator, target),
    )
    if len(spans) > 1:
        walker.operands[id(record)] = [(a, b) for a, b in spans[1:]]
    walker.layer.redirects.append(record)
    return [record]


def _heredoc_redirect(walker: Walker, node, ctx, depth, bound=()) -> list[Redirect]:
    descriptor = _descriptor(walker, node)
    operator = _operator(node)
    delimiter = body = None
    nested: list[Redirect] = []
    piped = False
    for i, child in enumerate(node.children):
        fname = node.field_name_for_child(i)
        if not child.is_named:
            if child.type in ("|", "|&"):
                piped = True
            continue
        if child.type == "heredoc_start":
            delimiter = child
            walker.visit(child, ctx, depth + 1)
        elif child.type == "heredoc_body":
            body = child
            walker.visit(child, replace(ctx, role=None), depth + 1)
        elif child.type in REDIRECT_KINDS or fname == "redirect":
            result = walker.visit(child, ctx, depth + 1)
            nested.extend(result if isinstance(result, list) else [])
        elif child.type in ("heredoc_end", "file_descriptor"):
            walker.visit(child, ctx, depth + 1)
        else:
            # The rest of the command line, which tree-sitter hangs under the here-doc.
            if piped or child.type == "pipeline":
                rest = PIPE
            elif ctx.stdin.kind == "pipe":
                rest = UNKNOWN
            else:
                rest = ctx.stdin
            walker.visit(child, replace(ctx, stdin=rest, role=None), depth + 1)
    feed = UNKNOWN
    if delimiter is not None and body is not None and operator == "<<":
        delim = walker.text(delimiter)
        text = walker.text(body)
        if delim[:1] in ("'", '"') and _QUOTED_DELIMITER.fullmatch(delim):
            feed = Stdin("literal", text)
        elif _PLAIN_DELIMITER.fullmatch(delim) and not any(c in text for c in "$`\\"):
            feed = Stdin("literal", text)
    record = Redirect(
        kind="heredoc_redirect",
        descriptor=descriptor,
        operator=operator,
        target=None,
        readable=True,
        output=False,
        feed=feed,
        display=(descriptor or "")
        + operator
        + (walker.text(delimiter) if delimiter else ""),
        heredoc_operator=True,
        start=node.start_byte,
    )
    walker.layer.redirects.append(record)
    return [record, *nested]


def _herestring_redirect(walker: Walker, node, ctx, depth, bound=()) -> list[Redirect]:
    _children(walker, node, replace(ctx, role=None), depth)
    descriptor = _descriptor(walker, node)
    pieces = [c for c in node.named_children if c.type != "file_descriptor"]
    word = None
    if pieces:
        word = make_word(walker.span(pieces[0].start_byte, pieces[-1].end_byte))
    # bash appends a newline to a here-string's word.
    feed = Stdin("literal", word.text + "\n") if word is not None and word.literal else UNKNOWN
    if word is not None:
        walker.layer.words.append(word)
    record = Redirect(
        kind="herestring_redirect",
        descriptor=descriptor,
        operator="<<<",
        target=word,
        readable=word is not None,
        output=False,
        feed=feed,
        display=walker.text(node),
        heredoc_operator=False,
        start=node.start_byte,
    )
    walker.layer.redirects.append(record)
    return [record]


HANDLERS: dict[str, Handler] = {kind: _children for kind in named_kinds()}
HANDLERS.update(
    {
        ERROR_KIND: _error,
        "pipeline": _pipeline,
        "negated_command": _negated,
        "test_command": _test_command,
        "redirected_statement": _redirected,
        "command": _simple,
        "declaration_command": _simple,
        "unset_command": _simple,
        "variable_assignment": _assignment,
        "function_definition": _function,
        "command_substitution": _command_substitution,
        "process_substitution": _process_substitution,
        "file_redirect": _file_redirect,
        "heredoc_redirect": _heredoc_redirect,
        "herestring_redirect": _herestring_redirect,
    }
)


def _check_walk(tree: tree_sitter.Tree, walker: Walker) -> None:
    """Rule 2, on every classification: every named node visited exactly once, and one
    invocation per simple command node."""
    named = 0
    simple = 0
    for node in _iter_nodes(tree.root_node):
        if not node.is_named:
            continue
        named += 1
        if node.type in SIMPLE_KINDS:
            simple += 1
        if walker.visits.get((node.id, node.start_byte, node.end_byte)) != 1:
            raise ParseRefused("a node was not walked exactly once")
    if named != len(walker.visits):
        raise ParseRefused("the walk and the tree disagree")
    if simple != len(walker.layer.invocations):
        raise ParseRefused("a simple command gave no invocation")


def walk(source: str, limits: Limits = DEFAULT_LIMITS) -> Walk:
    """Parse and walk ``source``. Raises ``ParseRefused`` when a fact cannot be proven
    (Rule 2) or a limit is exceeded (Rule 5); the size cap is checked before parsing."""
    data = source.encode("utf-8", "surrogatepass")
    if len(data) > limits.max_input_bytes:
        raise ParseRefused(f"input over {limits.max_input_bytes // 1024} KiB")
    tree = parse_source(data)
    layer = Walk(untrusted=untrusted_features(tree, data))
    walker = Walker(data, layer, limits)
    walker.visit(tree.root_node, Ctx(stdin=TERMINAL), 0)
    _check_walk(tree, walker)
    if walker.operands:
        # Words after a redirect target with no simple command to take them
        # (`{ cat; } <a b`, a syntax error in bash): the tree is not bash's.
        walker.note_untrusted("words after a redirect target with no command to take them")
    if layer.untrusted:
        # No stdin fact from a tree the walker does not trust.
        layer.invocations = [replace(i, stdin=UNKNOWN) for i in layer.invocations]
    elif any(may_rewire_stdin(i) for i in layer.invocations):
        # A command that can change the shell's own stdin (`exec </x; sudo tee /y`) makes
        # every other command's stdin unproven: it may run after it, in source order or on
        # a later loop pass.
        layer.invocations = [
            i if may_rewire_stdin(i) else replace(i, stdin=UNKNOWN)
            for i in layer.invocations
        ]
    return layer


def command_head(invocation: Invocation) -> Word | None:
    """The command word, with ``command`` and ``builtin`` in front looked through; None
    when there is no command word."""
    words = list(invocation.words)
    while words and words[0].literal and words[0].text in BUILTIN_PREFIXES:
        words.pop(0)
        while words and words[0].literal and words[0].text.startswith("-"):
            words.pop(0)
    if not words or not words[0].source:
        return None
    return words[0]


# Builtins that run shell code the walker does not see.
SHELL_RUNNERS = ("eval", "source", ".")
# Builtins that install code to run later, which the walker does not see (`trap '…' DEBUG`
# runs before every later command).
CODE_LATER = ("trap",)
BUILTIN_PREFIXES = ("command", "builtin")


def may_rewire_stdin(invocation: Invocation) -> bool:
    """Whether ``invocation`` can change the stdin of the shell itself: ``exec`` with
    any redirect, ``eval`` / ``source`` / ``.`` / ``trap`` (code the walker does not see),
    or a command word the walker cannot read. ``command`` and ``builtin`` in front are
    looked through."""
    head = command_head(invocation)
    if head is None:
        return False  # no command word: a redirect alone applies to nothing
    if not head.literal:
        return True
    if head.text in SHELL_RUNNERS or head.text in CODE_LATER:
        return True
    return head.text == "exec" and bool(invocation.redirects)
