#!/usr/bin/env python3
"""Resumable steps of the release workflow (.github/workflows/release.yml). Stdlib only.

    python3 -I .github/release/release_steps.py pypi-pending DIST VERSION
    python3 -I .github/release/release_steps.py github-release DIST VERSION

Both are safe to re-run after a failure part-way through:

- `pypi-pending` compares DIST with the files PyPI already has for VERSION. A file PyPI has
  with the same SHA-256 was uploaded by an earlier attempt of this run and is moved out of
  DIST, so the upload sends only the rest. A file PyPI has with a different hash stops the
  release.
- `github-release` (needs gh) creates or resumes the draft release vVERSION targeting
  GITHUB_SHA, uploads the files it lacks and checks every asset's digest, then publishes
  it, which creates the tag. It refuses when a tag vVERSION already points at another
  commit, and after publishing it checks the tag points at GITHUB_SHA. A release that is
  already published with the same files and tag is left as it is.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

PROJECT = "bashwalker"
SHA = re.compile(r"[0-9a-f]{40}")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


class Refused(Exception):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dist_files(dist: Path) -> dict[str, Path]:
    files = {p.name: p for p in sorted(dist.iterdir()) if p.is_file()}
    if not files:
        raise Refused(f"{dist} holds no files")
    return files


# --- PyPI ---------------------------------------------------------------------------------

def pypi_files(version: str, opener=urllib.request.urlopen) -> dict[str, str]:
    """{filename: sha256} of the files PyPI has for VERSION; {} when it has none."""
    url = f"https://pypi.org/pypi/{PROJECT}/{version}/json"
    request = urllib.request.Request(url, headers={"User-Agent": f"{PROJECT}-release"})
    try:
        with opener(request, timeout=30) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise Refused(f"PyPI answered {e.code} for {PROJECT} {version}") from e
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        raise Refused(f"can't read PyPI's files for {PROJECT} {version} ({e})") from e
    try:
        return {f["filename"]: f["digests"]["sha256"] for f in data["urls"]}
    except (KeyError, TypeError) as e:
        raise Refused(f"PyPI's answer for {PROJECT} {version} is malformed ({e})") from e


def pypi_pending(dist: Path, version: str, opener=urllib.request.urlopen) -> list[str]:
    """Move files PyPI already has (same hash) out of DIST; return the names left to upload."""
    have = pypi_files(version, opener)
    local = dist_files(dist)
    stray = sorted(set(have) - set(local))
    if stray:
        raise Refused(f"PyPI has files this run did not build: {', '.join(stray)}")
    done = dist.parent / f"{dist.name}-on-pypi"
    pending = []
    for name, path in local.items():
        if name not in have:
            pending.append(name)
        elif have[name] != sha256(path):
            raise Refused(f"PyPI's {name} differs from the one built in this run")
        else:
            done.mkdir(exist_ok=True)
            path.rename(done / name)
            print(f"{name}: already on PyPI with the same hash, not uploaded again")
    return pending


# --- GitHub release -----------------------------------------------------------------------

def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise Refused(f"gh {' '.join(args[:3])} failed: {result.stderr.strip() or 'no output'}")
    return result.stdout


def gh_json(*args: str):
    out = gh(*args)
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise Refused(f"gh {' '.join(args[:3])}: unreadable answer ({e})") from e


def tag_commit(repo: str, tag: str) -> str | None:
    """The commit the tag points at, None when there is no such tag."""
    refs = gh_json("api", f"repos/{repo}/git/matching-refs/tags/{tag}")
    if not isinstance(refs, list):
        raise Refused("tag lookup: not a list")
    ref = next((r for r in refs if isinstance(r, dict) and r.get("ref") == f"refs/tags/{tag}"),
               None)
    if ref is None:
        return None
    obj = ref.get("object") or {}
    # An annotated tag points at a tag object; follow it to the commit.
    for _ in range(5):
        if obj.get("type") == "commit":
            return obj.get("sha")
        if obj.get("type") != "tag":
            break
        obj = (gh_json("api", f"repos/{repo}/git/tags/{obj.get('sha')}").get("object") or {})
    raise Refused(f"tag {tag} does not resolve to a commit")


def find_release(repo: str, tag: str) -> dict | None:
    """The release (draft or published) for TAG. Drafts have no tag yet, so list them."""
    pages = gh_json("api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100")
    matches = [r for page in pages for r in page
               if isinstance(r, dict) and r.get("tag_name") == tag]
    if len(matches) > 1:
        raise Refused(f"{len(matches)} releases name {tag}; delete the extra drafts by hand")
    return matches[0] if matches else None


def asset_digests(release: dict) -> dict[str, str | None]:
    return {a["name"]: (a.get("digest") or "").removeprefix("sha256:") or None
            for a in release.get("assets") or []}


def check_assets(release: dict, local: dict[str, Path]) -> None:
    have = asset_digests(release)
    if set(have) != set(local):
        raise Refused(f"release assets {sorted(have)} differ from the built files {sorted(local)}")
    for name, path in local.items():
        if have[name] != sha256(path):
            raise Refused(f"release asset {name} differs from the one built in this run")


def github_release(dist: Path, version: str, repo: str, sha: str) -> None:
    tag = f"v{version}"
    local = dist_files(dist)
    pointed = tag_commit(repo, tag)
    if pointed is not None and pointed != sha:
        raise Refused(f"tag {tag} points at {pointed}, not the built commit {sha}")
    release = find_release(repo, tag)

    if release and not release.get("draft"):
        if pointed != sha:
            raise Refused(f"release {tag} is published but its tag does not point at {sha}")
        check_assets(release, local)
        print(f"{tag} is already released from {sha} with the same files")
        return

    if release is None:
        gh("release", "create", tag, "--repo", repo, "--draft", "--target", sha,
           "--title", tag, "--generate-notes")
        release = find_release(repo, tag)
        if release is None:
            raise Refused(f"the draft release {tag} was created but can't be found")
    elif release.get("target_commitish") != sha:
        raise Refused(f"the draft release {tag} targets {release.get('target_commitish')}, "
                      f"not {sha}; delete it by hand")

    have = asset_digests(release)
    stray = sorted(set(have) - set(local))
    if stray:
        raise Refused(f"the draft release {tag} has assets this run did not build: {stray}")
    # --clobber replaces a partly uploaded or mismatching asset on the draft.
    upload = [str(p) for name, p in local.items() if have.get(name) != sha256(p)]
    if upload:
        gh("release", "upload", tag, "--repo", repo, "--clobber", *upload)
    release = find_release(repo, tag)
    check_assets(release or {}, local)

    # Publishing creates the tag at the target; check again just before.
    pointed = tag_commit(repo, tag)
    if pointed is not None and pointed != sha:
        raise Refused(f"tag {tag} appeared and points at {pointed}, not {sha}")
    gh("release", "edit", tag, "--repo", repo, "--draft=false")
    if tag_commit(repo, tag) != sha:
        raise Refused(f"release {tag} is published, but its tag does not point at {sha}")
    print(f"Released {tag} from {sha}")


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] not in ("pypi-pending", "github-release"):
        print(__doc__, file=sys.stderr)
        return 2
    step, dist, version = argv[0], Path(argv[1]), argv[2]
    try:
        if not VERSION.fullmatch(version):
            raise Refused(f"version {version!r} is not X.Y.Z")
        if step == "pypi-pending":
            pending = pypi_pending(dist, version)
            print(f"To upload: {', '.join(pending) or 'nothing'}")
            output = os.environ.get("GITHUB_OUTPUT")
            if output:
                with open(output, "a", encoding="utf-8") as fh:
                    fh.write(f"upload={'true' if pending else 'false'}\n")
        else:
            repo, sha = os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_SHA", "")
            if not repo or not SHA.fullmatch(sha):
                raise Refused("GITHUB_REPOSITORY or GITHUB_SHA is missing")
            github_release(dist, version, repo, sha)
    except Refused as e:
        print(f"::error::{e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
