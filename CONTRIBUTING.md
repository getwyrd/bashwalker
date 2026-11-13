# Contributing to bashwalker

Thanks for contributing. Read the
[shared contributing guide](https://github.com/getwyrd/.github/blob/main/CONTRIBUTING.md)
first. It covers when to open an issue before writing code, what won't be merged, and the
rules for AI-assisted changes. This file adds what is specific to bashwalker.

This project is licensed under the Apache License, Version 2.0 ([LICENSE](LICENSE)); contributions
are accepted under the same license.

## Developer Certificate of Origin (sign-off)

Every commit must carry a [Developer Certificate of Origin](DCO) (DCO 1.1) sign-off. By
signing off you certify the DCO's terms for your contribution. Sign off with:

```bash
git commit -s
```

This appends a `Signed-off-by: Your Name <you@example.com>` trailer (using your
`git config user.name` / `user.email`). Amend a commit that's missing it with
`git commit --amend -s`. The `dco` check fails a PR with an unsigned commit.

## Pull requests

- **Every pull request links an issue**, typo and docs fixes included: `Closes #NNN`, or
  `Refs #NNN` for partial work, in the description. This project is stricter than the
  shared guide here; the required `require-linked-issue` check fails a PR without one.
  For a small fix, a one-line issue is enough. Dependabot's PRs are exempt.
- One logical change per PR; split unrelated changes.
- A change ships with the means to verify it: a test, or a stated reason why a test is
  impractical plus a manual repro.
- A change to the system's structure updates the architecture overview in the same PR. A
  settled design question becomes an ADR. See [`docs/design/README.md`](docs/design/README.md)
  for which document class to use; accepted ADRs and proposals and stable specs are never
  edited, only superseded. To propose a decision, follow
  [How an ADR is made](docs/design/adr/README.md#how-an-adr-is-made).

## Issues

New issues are triaged by the rules in [ADR-0005](docs/design/adr/0005-issue-priority-and-automated-triage.md):
severity and reach set a `priority:P0`–`P3` label. If automated triage is set up, a bot
labels the issue and posts its reasons; a maintainer makes the final call and sets the
milestone. Report security problems privately (see [SECURITY.md](SECURITY.md)).

## Running checks

Every check runs with `python3 -m pytest` from the repo root. First-time setup:
`python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`. Tests import from `src/`
directly, so they always run against the tree they sit in. The required `gate` job in
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs the same command.

The differential parser test (`tests/test_differential.py`) compares the walker with
`bash -n`, shfmt and bash's own reprint. It is skipped unless enabled, and once enabled a
missing tool or sandbox fails it. It needs `shfmt` (3.12.0) and `bwrap` on `PATH`:

```bash
BASHWALKER_DIFFERENTIAL=1 python3 -m pytest tests/test_differential.py
```

`BASHWALKER_DIFFERENTIAL_LINES` and `BASHWALKER_DIFFERENTIAL_SEED` change how many lines it
generates and from which seed. A difference that is not a security problem goes into
`tests/differential/known.toml` with its reason. CI's `differential` jobs run it on bash
5.1, 5.2 and 5.3.

The status checks `main` requires are listed in
[`.github/required-checks.txt`](.github/required-checks.txt). A maintainer can see whether
the repo's settings and branch protection still match it, and the rest of the settings
the project expects, with `python3 -I scripts/repo-settings.py check`; `apply` restores
them.
