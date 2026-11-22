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
  GITHUB_SHA and from then on reads, fills and publishes it by its ID: it uploads the files
  it lacks and checks every asset's digest, then publishes it, which creates the tag. It refuses when a tag vVERSION already points at another
  commit, and after publishing it checks the tag points at GITHUB_SHA. A release that is
  already published with the same files and tag is left as it is.

GitHub's reads lag its writes by a moment: a release just created, an asset just uploaded
or a tag just made by publishing may not show yet. Each read that follows a write is tried
READS times, READ_DELAY seconds apart, before the step refuses.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT = "bashwalker"
SHA = re.compile(r"[0-9a-f]{40}")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
READS = 6
READ_DELAY = float(os.environ.get("RELEASE_READ_DELAY", "3"))


class Refused(Exception):
    pass


def settled(read, done, what: str):
    """Call read() until done(result) holds, READS times at most; return the last result.
    For a read right after a write, which GitHub may not show yet. A Refused from read()
    counts as not done until the last try, which raises it. done() raises Refused for a
    state that is wrong rather than late, which stops at once: a later, staler read must
    not hide it."""
    for attempt in range(READS):
        if attempt:
            time.sleep(READ_DELAY)
        try:
            result = read()
        except Refused:
            if attempt == READS - 1:
                raise
            continue
        if done(result):  # may raise Refused
            return result
    print(f"{what}: still not as expected after {READS} reads", file=sys.stderr)
    return result


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


def release_by_id(repo: str, release_id: int) -> dict | None:
    """The release with this ID (drafts too), None when GitHub has none (yet)."""
    try:
        release = gh_json("api", f"repos/{repo}/releases/{release_id}")
    except Refused as e:
        if "HTTP 404" in str(e):
            return None
        raise
    if not isinstance(release, dict):
        raise Refused(f"release {release_id}: not an object")
    return release


def assets_match(release: dict | None, local: dict[str, Path]) -> bool:
    try:
        check_assets(release or {}, local)
    except Refused:
        return False
    return True


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
        # Created through the API so the answer names the new draft's ID; every later read,
        # and the publish, uses that ID, never the tag another draft could carry.
        created = gh_json("api", "-X", "POST", f"repos/{repo}/releases",
                          "-f", f"tag_name={tag}", "-f", f"target_commitish={sha}",
                          "-f", f"name={tag}", "-F", "draft=true",
                          "-F", "generate_release_notes=true")
        release_id = created.get("id") if isinstance(created, dict) else None
    else:
        release_id = release.get("id")
    if not isinstance(release_id, int):
        raise Refused(f"the draft release {tag} has no readable ID")

    def ours(r: dict | None) -> bool:
        """Still our draft: this tag, the built commit, not yet published."""
        return (r is not None and r.get("id") == release_id and r.get("draft") is True
                and r.get("tag_name") == tag and r.get("target_commitish") == sha)

    release = settled(lambda: release_by_id(repo, release_id), lambda r: r is not None,
                      f"draft release {tag}")
    if release is None:
        raise Refused(f"the draft release {tag} ({release_id}) can't be found")
    if not ours(release):
        raise Refused(f"the draft release {tag} ({release_id}) targets "
                      f"{release.get('target_commitish')} or is no longer a draft, not a draft "
                      f"of {sha}; delete it by hand")

    have = asset_digests(release)
    stray = sorted(set(have) - set(local))
    if stray:
        raise Refused(f"the draft release {tag} has assets this run did not build: {stray}")
    # Uploads go to this draft's own upload URL, and a partly uploaded or mismatching asset
    # is deleted by its own ID first: nothing here finds the draft by its tag again.
    upload_url = str(release.get("upload_url") or "").split("{", 1)[0]
    if not (upload_url.startswith("https://")
            and upload_url.endswith(f"/repos/{repo}/releases/{release_id}/assets")):
        raise Refused(f"the draft release {tag} ({release_id}) has an unexpected upload URL")
    assets = {a.get("name"): a.get("id") for a in release.get("assets") or []}
    for name, path in local.items():
        if have.get(name) == sha256(path):
            continue
        if name in assets:
            if not isinstance(assets[name], int):
                raise Refused(f"asset {name} on the draft release {tag} has no readable ID")
            gh("api", "-X", "DELETE", f"repos/{repo}/releases/assets/{assets[name]}")
        gh("api", "-X", "POST", f"{upload_url}?name={urllib.parse.quote(name)}",
           "-H", "Content-Type: application/octet-stream", "--input", str(path))

    def filled(r: dict | None) -> bool:
        """True once every built file shows with its digest. Only a missing asset or a
        digest not computed yet counts as late; anything else is wrong and refuses."""
        if r is None:
            return False
        if not ours(r):
            raise Refused(f"the draft release {tag} ({release_id}) changed while it was filled")
        shown = asset_digests(r)
        stray = sorted(set(shown) - set(local))
        if stray:
            raise Refused(f"the draft release {tag} gained assets this run did not build: {stray}")
        for name, path in local.items():
            if shown.get(name) is not None and shown[name] != sha256(path):
                raise Refused(f"release asset {name} differs from the one built in this run")
        return all(shown.get(name) is not None for name in local)

    # An uploaded asset may show late, or without its digest for a moment.
    release = settled(lambda: release_by_id(repo, release_id), filled, f"assets of {tag}")
    if not filled(release):
        raise Refused(f"the assets of {tag} did not all show after {READS} reads")

    # Publishing creates the tag at the target; check again just before.
    pointed = tag_commit(repo, tag)
    if pointed is not None and pointed != sha:
        raise Refused(f"tag {tag} appeared and points at {pointed}, not {sha}")
    gh("api", "-X", "PATCH", f"repos/{repo}/releases/{release_id}", "-F", "draft=false")
    # Publishing creates the tag; it may take a moment to show. A tag on another commit is
    # wrong, not late.
    def tagged(c: str | None) -> bool:
        if c is not None and c != sha:
            raise Refused(f"release {tag} is published, but its tag points at {c}, not {sha}")
        return c is not None

    if not tagged(settled(lambda: tag_commit(repo, tag), tagged, f"tag {tag}")):
        raise Refused(f"release {tag} is published, but its tag did not show")

    # The published release, read by ID once it shows as published: the same files.
    def published(r: dict | None) -> bool:
        if r is None or r.get("draft") is True:
            return False
        if r.get("id") != release_id or r.get("tag_name") != tag:
            raise Refused(f"release {release_id} changed while it was published")
        check_assets(r, local)
        return True

    if not published(settled(lambda: release_by_id(repo, release_id), published,
                             f"release {tag}")):
        raise Refused(f"release {tag} did not show as published")
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
