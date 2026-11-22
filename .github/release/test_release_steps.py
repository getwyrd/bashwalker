"""Tests for release_steps.py, offline: PyPI and gh are replaced."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_steps as rs  # noqa: E402

SHA = "a" * 40
OTHER = "b" * 40
REPO = "getwyrd/bashwalker"
WHEEL = "bashwalker-0.1.5-py3-none-any.whl"
SDIST = "bashwalker-0.1.5.tar.gz"


@pytest.fixture
def dist(tmp_path):
    d = tmp_path / "dist"
    d.mkdir()
    (d / WHEEL).write_bytes(b"wheel")
    (d / SDIST).write_bytes(b"sdist")
    return d


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Response:
    def __init__(self, body: dict) -> None:
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def pypi(files: dict[str, bytes] | None):
    def opener(*args, **kwargs):
        if files is None:
            raise urllib.error.HTTPError("u", 404, "x", {}, io.BytesIO())
        return Response({"urls": [{"filename": n, "digests": {"sha256": digest(b)}}
                                  for n, b in files.items()]})
    return opener


# --- pypi-pending -------------------------------------------------------------------------

def test_nothing_on_pypi_uploads_everything(dist):
    assert set(rs.pypi_pending(dist, "0.1.5", pypi(None))) == {SDIST, WHEEL}
    assert {p.name for p in dist.iterdir()} == {SDIST, WHEEL}


def test_a_file_already_uploaded_is_left_out(dist):
    assert rs.pypi_pending(dist, "0.1.5", pypi({WHEEL: b"wheel"})) == [SDIST]
    assert [p.name for p in dist.iterdir()] == [SDIST]


def test_everything_uploaded_leaves_nothing(dist):
    assert rs.pypi_pending(dist, "0.1.5", pypi({WHEEL: b"wheel", SDIST: b"sdist"})) == []


def test_a_different_file_on_pypi_refuses(dist):
    with pytest.raises(rs.Refused, match="differs"):
        rs.pypi_pending(dist, "0.1.5", pypi({WHEEL: b"other build"}))


def test_a_file_this_run_did_not_build_refuses(dist):
    with pytest.raises(rs.Refused, match="did not build"):
        rs.pypi_pending(dist, "0.1.5", pypi({"bashwalker-0.1.5-cp314-linux.whl": b"x"}))


def test_pypi_errors_refuse(dist):
    def down(*a, **k):
        raise urllib.error.HTTPError("u", 503, "x", {}, io.BytesIO())
    with pytest.raises(rs.Refused, match="503"):
        rs.pypi_pending(dist, "0.1.5", down)


# --- github-release -----------------------------------------------------------------------

class FakeGitHub:
    """Releases and tags in memory; answers the gh calls release_steps makes."""

    def __init__(self, tag_sha=None, release=None):
        self.tag_sha = tag_sha
        self.release = release
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> str:
        self.calls.append(args)
        if args[0] == "api" and "matching-refs" in args[1]:
            refs = [] if self.tag_sha is None else [
                {"ref": "refs/tags/v0.1.5", "object": {"type": "commit", "sha": self.tag_sha}}]
            return json.dumps(refs)
        if args[:3] == ("api", "--paginate", "--slurp"):
            return json.dumps([[self.release]] if self.release else [[]])
        if args[:2] == ("release", "create"):
            self.release = {"tag_name": "v0.1.5", "draft": True, "target_commitish": SHA,
                            "assets": []}
            return ""
        if args[:2] == ("release", "upload"):
            for path in args[args.index("--clobber") + 1:]:
                p = Path(path)
                self.release["assets"] = [a for a in self.release["assets"] if a["name"] != p.name]
                self.release["assets"].append(
                    {"name": p.name, "digest": "sha256:" + digest(p.read_bytes())})
            return ""
        if args[:2] == ("release", "edit"):
            self.release["draft"] = False
            self.tag_sha = self.release["target_commitish"]
            return ""
        raise AssertionError(args)


def run(monkeypatch, fake, dist):
    monkeypatch.setattr(rs, "gh", fake)
    rs.github_release(dist, "0.1.5", REPO, SHA)


def test_new_release_is_drafted_filled_and_published(monkeypatch, dist):
    fake = FakeGitHub()
    run(monkeypatch, fake, dist)
    assert fake.release["draft"] is False and fake.tag_sha == SHA
    assert {a["name"] for a in fake.release["assets"]} == {WHEEL, SDIST}


def test_a_partly_uploaded_draft_is_resumed(monkeypatch, dist):
    draft = {"tag_name": "v0.1.5", "draft": True, "target_commitish": SHA,
             "assets": [{"name": WHEEL, "digest": "sha256:" + digest(b"wheel")},
                        {"name": SDIST, "digest": "sha256:" + digest(b"cut off")}]}
    fake = FakeGitHub(release=draft)
    run(monkeypatch, fake, dist)
    uploads = [c for c in fake.calls if c[:2] == ("release", "upload")]
    assert len(uploads) == 1 and uploads[0][-1].endswith(SDIST)
    assert not any(c[:2] == ("release", "create") for c in fake.calls)
    assert fake.release["draft"] is False


def test_an_existing_tag_on_another_commit_refuses(monkeypatch, dist):
    fake = FakeGitHub(tag_sha=OTHER)
    with pytest.raises(rs.Refused, match="points at"):
        run(monkeypatch, fake, dist)
    assert not any(c[0] == "release" for c in fake.calls)


def test_a_draft_targeting_another_commit_refuses(monkeypatch, dist):
    fake = FakeGitHub(release={"tag_name": "v0.1.5", "draft": True,
                               "target_commitish": OTHER, "assets": []})
    with pytest.raises(rs.Refused, match="targets"):
        run(monkeypatch, fake, dist)


def test_a_draft_with_stray_assets_refuses(monkeypatch, dist):
    fake = FakeGitHub(release={"tag_name": "v0.1.5", "draft": True, "target_commitish": SHA,
                               "assets": [{"name": "evil.whl", "digest": "sha256:00"}]})
    with pytest.raises(rs.Refused, match="did not build"):
        run(monkeypatch, fake, dist)


def test_an_already_published_release_is_left_alone(monkeypatch, dist):
    published = {"tag_name": "v0.1.5", "draft": False, "target_commitish": SHA,
                 "assets": [{"name": WHEEL, "digest": "sha256:" + digest(b"wheel")},
                            {"name": SDIST, "digest": "sha256:" + digest(b"sdist")}]}
    fake = FakeGitHub(tag_sha=SHA, release=published)
    run(monkeypatch, fake, dist)
    assert not any(c[0] == "release" for c in fake.calls)


def test_a_published_release_with_other_files_refuses(monkeypatch, dist):
    published = {"tag_name": "v0.1.5", "draft": False, "target_commitish": SHA,
                 "assets": [{"name": WHEEL, "digest": "sha256:" + digest(b"other")},
                            {"name": SDIST, "digest": "sha256:" + digest(b"sdist")}]}
    with pytest.raises(rs.Refused, match="differs"):
        run(monkeypatch, FakeGitHub(tag_sha=SHA, release=published), dist)


def test_main_rejects_a_bad_version(dist, capsys):
    assert rs.main(["pypi-pending", str(dist), "0.1.5rc1"]) == 1
    assert "X.Y.Z" in capsys.readouterr().out
