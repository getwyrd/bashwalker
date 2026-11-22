#!/usr/bin/env python3
"""Pre-flight checks for a release (.github/workflows/release.yml). Stdlib only; needs gh.

    python3 -I .github/release/preflight.py

Reads GITHUB_REPOSITORY, GITHUB_REF and GITHUB_SHA (set by Actions) and exits 0 only when:
- the run is on refs/heads/main;
- pyproject.toml's version is X.Y.Z;
- no tag vX.Y.Z exists on GitHub;
- PyPI has no bashwalker X.Y.Z;
- the ci workflow's push run on this commit passed;
- the `pypi` environment exists, deploys only from chosen branches and has a required
  reviewer. A run that names a missing environment creates it unprotected, so without
  this check the first release could publish without the maintainer's approval.

On success it writes `version=X.Y.Z` to GITHUB_OUTPUT. Every check fails closed: an answer
it cannot read stops the release.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "bashwalker"
CI_WORKFLOW = "ci.yml"
ENVIRONMENT = "pypi"
MAIN = "refs/heads/main"
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SHA = re.compile(r"[0-9a-f]{40}")


class Refused(Exception):
    """A check failed or could not be read; the message says which."""


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise Refused(f"gh {' '.join(args[:2])} failed: {result.stderr.strip() or 'no output'}")
    return result.stdout


def read_json(text: str, what: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise Refused(f"{what}: unreadable answer ({e})") from e


def project_version(root: Path = ROOT) -> str:
    try:
        version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as e:
        raise Refused(f"can't read the version from pyproject.toml ({e})") from e
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise Refused(f"pyproject.toml's version {version!r} is not X.Y.Z")
    return version


def tag_exists(repo: str, tag: str) -> bool:
    # matching-refs is a prefix match (v0.1.1 also matches v0.1.10), so compare exactly.
    refs = read_json(gh("api", f"repos/{repo}/git/matching-refs/tags/{tag}"), "tag lookup")
    if not isinstance(refs, list):
        raise Refused("tag lookup: not a list")
    return any(isinstance(r, dict) and r.get("ref") == f"refs/tags/{tag}" for r in refs)


def on_pypi(version: str, opener=urllib.request.urlopen) -> bool:
    url = f"https://pypi.org/pypi/{PROJECT}/{version}/json"
    request = urllib.request.Request(url, headers={"User-Agent": f"{PROJECT}-release-check"})
    try:
        with opener(request, timeout=30) as response:
            if response.status == 200:
                return True
            raise Refused(f"PyPI answered {response.status} for {PROJECT} {version}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise Refused(f"PyPI answered {e.code} for {PROJECT} {version}") from e
    except (urllib.error.URLError, OSError) as e:
        raise Refused(f"can't reach PyPI ({e})") from e


def ci_passed(repo: str, sha: str) -> bool:
    runs = read_json(gh("run", "list", "-R", repo, "--workflow", CI_WORKFLOW, "--commit", sha,
                        "--event", "push", "--limit", "50",
                        "--json", "databaseId,headSha,status,conclusion"), "ci run lookup")
    if not isinstance(runs, list):
        raise Refused("ci run lookup: not a list")
    runs = [r for r in runs if isinstance(r, dict) and r.get("headSha") == sha
            and isinstance(r.get("databaseId"), int)]
    if not runs:
        raise Refused(f"no {CI_WORKFLOW} push run on {sha}; wait for it, then run this again")
    # The newest run counts; a re-run keeps its ID and reports its latest attempt.
    latest = max(runs, key=lambda r: r["databaseId"])
    return latest.get("status") == "completed" and latest.get("conclusion") == "success"


def environment_protected(repo: str) -> bool:
    env = read_json(gh("api", f"repos/{repo}/environments/{ENVIRONMENT}"), "environment lookup")
    if not isinstance(env, dict):
        raise Refused("environment lookup: not an object")
    reviewers = sum(len(r.get("reviewers") or []) for r in env.get("protection_rules") or []
                    if isinstance(r, dict) and r.get("type") == "required_reviewers")
    policy = env.get("deployment_branch_policy") or {}
    return reviewers > 0 and policy.get("custom_branch_policies") is True


def preflight(env: dict[str, str]) -> str:
    repo, ref, sha = env.get("GITHUB_REPOSITORY", ""), env.get("GITHUB_REF", ""), env.get("GITHUB_SHA", "")
    if ref != MAIN:
        raise Refused(f"releases run only from main, not {ref or 'an unknown ref'}")
    if not repo or not SHA.fullmatch(sha):
        raise Refused("GITHUB_REPOSITORY or GITHUB_SHA is missing")
    version = project_version()
    tag = f"v{version}"
    if tag_exists(repo, tag):
        raise Refused(f"tag {tag} already exists; bump the version in a release PR first")
    if on_pypi(version):
        raise Refused(f"PyPI already has {PROJECT} {version}")
    if not ci_passed(repo, sha):
        raise Refused(f"{CI_WORKFLOW} has not passed on {sha}")
    if not environment_protected(repo):
        raise Refused(f"the {ENVIRONMENT} environment has no required reviewer or no branch "
                      "rule; run `python3 -I scripts/repo-settings.py apply` first")
    return version


def main() -> int:
    try:
        version = preflight(dict(os.environ))
    except Refused as e:
        print(f"::error::{e}")
        return 1
    print(f"Releasing {PROJECT} {version} from {os.environ['GITHUB_SHA']}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"version={version}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
