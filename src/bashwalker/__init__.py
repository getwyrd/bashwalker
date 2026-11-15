"""bashwalker: a bash command line in, proven facts per simple command out.

``walk(line)`` parses ``line`` with the pinned tree-sitter-bash grammar and returns a
``Walk``: one ``Invocation`` per simple command (its words, assignments, redirects and
stdin), every word marked literal or not, and the features that make the tree
untrusted. It raises ``ParseRefused`` when it cannot prove its facts. It makes no policy
decision: what a command may do is the caller's to judge, and every unproven fact is
reported as the worst case so the caller can fail closed.

The facts are for one line run on its own in a new, non-interactive shell with no startup
files and a clean environment (SECURITY.md and architecture section 3.2 give the exact
conditions). In an interactive shell, or one that has already run other lines, they do
not hold.
"""

from __future__ import annotations

from bashwalker.core import (
    DEFAULT_LIMITS,
    LANGUAGE,
    Assignment,
    Invocation,
    Limits,
    ParseRefused,
    Redirect,
    Stdin,
    Walk,
    Word,
    command_head,
    lex_word,
    make_word,
    may_rewire_stdin,
    parse_source,
    untrusted_features,
    walk,
)

__all__ = [
    "DEFAULT_LIMITS",
    "LANGUAGE",
    "Assignment",
    "Invocation",
    "Limits",
    "ParseRefused",
    "Redirect",
    "Stdin",
    "Walk",
    "Word",
    "command_head",
    "lex_word",
    "make_word",
    "may_rewire_stdin",
    "parse_source",
    "untrusted_features",
    "walk",
]
