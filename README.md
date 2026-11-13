# bashwalker

A bash command line in, proven facts per simple command out: a fail-closed tree-sitter-bash walker (extracted from nl-shell)

```python
import bashwalker

walked = bashwalker.walk("cd /tmp && git push origin HEAD:main 2>/dev/null")
for invocation in walked.invocations:
    print([w.text for w in invocation.words], [w.literal for w in invocation.words])
# ['cd', '/tmp'] [True, True]
# ['git', 'push', 'origin', 'HEAD:main'] [True, True, True, True]
```

`walk()` parses a line with the pinned tree-sitter-bash grammar and returns one
`Invocation` per simple command, including those inside substitutions, functions and
here-doc command lines: its words (each marked literal or not), assignments, redirects and
where its stdin comes from. `walked.untrusted` names any feature tree-sitter-bash reads
differently from bash. A fact that cannot be proven comes back as the worst case
(non-literal, `unknown` stdin, an untrusted tree), and a walk that cannot be completed
raises `ParseRefused`. bashwalker makes no policy decision: what a command may do is the
caller's to judge.

It began as the shell layer of [nl-shell](https://github.com/getwyrd/nl-shell)'s policy
gate, whose history it keeps. tree-sitter and tree-sitter-bash are pinned exactly, because
every fact depends on how that grammar reads bash; pin bashwalker exactly for the same
reason.

## Status

Early: 0.1.1, not yet on PyPI.

## Documentation

[`docs/`](docs/README.md) is the map. Design documents are in [`docs/design/`](docs/design/README.md):
architecture, decision records (ADRs), proposals and specifications. Governance and the Code
of Conduct are in [`docs/governance/`](docs/governance/GOVERNANCE.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and, for coding agents, [AGENTS.md](AGENTS.md).

## License

Copyright © 2026 Eduard R..

bashwalker is licensed under the **Apache License, Version 2.0** ([LICENSE](LICENSE)).

Contributions are accepted under the same license and gated on the
[Developer Certificate of Origin](DCO). Sign off commits with `git commit -s`.
