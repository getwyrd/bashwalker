# Why "bashwalker"

The name says what the library does: it **walks** the syntax tree of a **bash** command
line. `walk()` visits every named node of the tree tree-sitter-bash builds and reports what it
finds, one simple command at a time. A tree walker is the ordinary name for that kind of
code. Like the library, the name says nothing about policy: bashwalker describes a command
line and does not judge it.

The library began as the shell layer of nl-shell's policy gate and was split out so that
nl-shell and pdca-harness could share it. "aibasher" was also considered before the name
was settled.
