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


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(rs, "READ_DELAY", 0, raising=False)


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

UPLOAD = "https://uploads.github.com/repos/getwyrd/bashwalker/releases/{id}/assets"


def asset(asset_id: int, name: str, data: bytes) -> dict:
    return {"id": asset_id, "name": name, "digest": "sha256:" + digest(data)}


def draft_of(target: str, release_id: int = 77, assets=(), draft: bool = True) -> dict:
    return {"id": release_id, "tag_name": "v0.1.5", "draft": draft, "target_commitish": target,
            "upload_url": UPLOAD.format(id=release_id) + "{?name,label}", "assets": list(assets)}


class FakeGitHub:
    """Releases and tags in memory; answers the gh calls release_steps makes."""

    def __init__(self, tag_sha=None, release=None, lag=0, others=()):
        self.tag_sha = tag_sha
        self.release = release
        # Other releases GitHub lists besides the one under test.
        self.others = list(others)
        self.next_asset = 100
        self.calls: list[tuple[str, ...]] = []
        # How many reads after each write still show the state from before it.
        self.lag = lag
        self.stale = 0
        self.seen_release, self.seen_tag = release, tag_sha

    def _wrote(self) -> None:
        self.stale = self.lag

    def _read(self):
        if self.stale:
            self.stale -= 1
            return self.seen_release, self.seen_tag
        self.seen_release = json.loads(json.dumps(self.release)) if self.release else None
        self.seen_tag = self.tag_sha
        return self.seen_release, self.seen_tag

    def __call__(self, *args: str) -> str:
        self.calls.append(args)
        if args[0] == "api" and "matching-refs" in args[1]:
            _, tag_sha = self._read()
            refs = [] if tag_sha is None else [
                {"ref": "refs/tags/v0.1.5", "object": {"type": "commit", "sha": tag_sha}}]
            return json.dumps(refs)
        if args[:3] == ("api", "--paginate", "--slurp"):
            release, _ = self._read()
            listed = [release] if release else []
            return json.dumps([listed + self.others])
        if args[:3] == ("api", "-X", "POST") and args[3].startswith("https://uploads."):
            assert args[3].startswith(UPLOAD.format(id=self.release["id"]) + "?name="), args
            p = Path(args[args.index("--input") + 1])
            assert all(a["name"] != p.name for a in self.release["assets"]), "upload over asset"
            self.next_asset += 1
            self.release["assets"].append({"id": self.next_asset, "name": p.name,
                                           "digest": "sha256:" + digest(p.read_bytes())})
            self._wrote()
            return "{}"
        if args[:3] == ("api", "-X", "DELETE"):
            gone = int(args[3].rsplit("/", 1)[1])
            self.release["assets"] = [a for a in self.release["assets"] if a.get("id") != gone]
            self._wrote()
            return ""
        if args[:3] == ("api", "-X", "POST"):
            self.release = draft_of(SHA)
            self._wrote()
            return json.dumps(self.release)
        if args[:3] == ("api", "-X", "PATCH"):
            assert args[3].endswith(f"/releases/{self.release['id']}"), args
            self.release["draft"] = False
            self.tag_sha = self.release["target_commitish"]
            self._wrote()
            return json.dumps(self.release)
        if args[0] == "api" and "/releases/" in args[1]:
            release, _ = self._read()
            wanted = int(args[1].rsplit("/", 1)[1])
            for r in ([release] if release else []) + self.others:
                if r.get("id") == wanted:
                    return json.dumps(r)
            raise rs.Refused("gh api failed: Not Found (HTTP 404)")
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
    draft = draft_of(SHA, assets=[asset(1, WHEEL, b"wheel"), asset(2, SDIST, b"cut off")])
    fake = FakeGitHub(release=draft)
    run(monkeypatch, fake, dist)
    posts = [c for c in fake.calls if c[:3] == ("api", "-X", "POST")]
    deletes = [c for c in fake.calls if c[:3] == ("api", "-X", "DELETE")]
    assert len(posts) == 1 and posts[0][-1].endswith(SDIST)  # the upload, no new draft
    assert len(deletes) == 1 and deletes[0][3].endswith("/releases/assets/2")
    assert fake.release["draft"] is False


def test_an_existing_tag_on_another_commit_refuses(monkeypatch, dist):
    fake = FakeGitHub(tag_sha=OTHER)
    with pytest.raises(rs.Refused, match="points at"):
        run(monkeypatch, fake, dist)
    assert not any(c[0] == "release" or c[1:2] == ("-X",) for c in fake.calls)


def test_a_draft_targeting_another_commit_refuses(monkeypatch, dist):
    fake = FakeGitHub(release=draft_of(OTHER))
    with pytest.raises(rs.Refused, match="targets"):
        run(monkeypatch, fake, dist)


def test_a_draft_with_stray_assets_refuses(monkeypatch, dist):
    fake = FakeGitHub(release=draft_of(SHA, assets=[{"id": 9, "name": "evil.whl",
                                                     "digest": "sha256:00"}]))
    with pytest.raises(rs.Refused, match="did not build"):
        run(monkeypatch, fake, dist)


def test_an_already_published_release_is_left_alone(monkeypatch, dist):
    published = draft_of(SHA, draft=False,
                         assets=[asset(1, WHEEL, b"wheel"), asset(2, SDIST, b"sdist")])
    fake = FakeGitHub(tag_sha=SHA, release=published)
    run(monkeypatch, fake, dist)
    assert not any(c[0] == "release" or c[1:2] == ("-X",) for c in fake.calls)


def test_a_published_release_with_other_files_refuses(monkeypatch, dist):
    published = draft_of(SHA, draft=False,
                         assets=[asset(1, WHEEL, b"other"), asset(2, SDIST, b"sdist")])
    with pytest.raises(rs.Refused, match="differs"):
        run(monkeypatch, FakeGitHub(tag_sha=SHA, release=published), dist)


def test_reads_that_lag_the_writes_are_retried(monkeypatch, dist):
    """#48: the list right after `gh release create` did not show the new draft yet."""
    fake = FakeGitHub(lag=2)
    run(monkeypatch, fake, dist)
    assert fake.release["draft"] is False and fake.tag_sha == SHA
    creates = [c for c in fake.calls
               if c[:3] == ("api", "-X", "POST") and not c[3].startswith("https://")]
    assert len(creates) == 1


def test_a_lag_longer_than_the_retries_still_refuses(monkeypatch, dist):
    fake = FakeGitHub(lag=rs.READS + 1)
    with pytest.raises(rs.Refused, match="can't be found"):
        run(monkeypatch, fake, dist)


def test_another_draft_is_never_published(monkeypatch, dist):
    """Codex on #48: while our new draft lags, an older draft with the same tag and files,
    targeting another commit, must not be taken for it."""
    old = draft_of(OTHER, release_id=12,
                   assets=[asset(1, WHEEL, b"wheel"), asset(2, SDIST, b"sdist")])
    fake = FakeGitHub(lag=2)
    monkeypatch.setattr(rs, "gh", fake)
    monkeypatch.setattr(rs, "find_release", lambda repo, tag: None)
    fake.others = [old]
    rs.github_release(dist, "0.1.5", REPO, SHA)
    patches = [c for c in fake.calls if c[:3] == ("api", "-X", "PATCH")]
    assert len(patches) == 1 and patches[0][3].endswith("/releases/77")
    # Nothing touched the other draft: not its assets, not its state.
    assert old["draft"] is True and [a["id"] for a in old["assets"]] == [1, 2]
    assert all("/releases/12" not in c[3] for c in fake.calls if c[1:2] == ("-X",))


def test_an_unexpected_upload_url_refuses(monkeypatch, dist):
    draft = draft_of(SHA)
    draft["upload_url"] = "https://uploads.github.com/repos/getwyrd/bashwalker/releases/12/assets"
    fake = FakeGitHub(release=draft)
    with pytest.raises(rs.Refused, match="upload URL"):
        run(monkeypatch, fake, dist)
    assert not any(c[1:2] == ("-X",) for c in fake.calls)


class Tampered(FakeGitHub):
    """After the upload, the next read shows a changed draft; the reads after it are stale
    copies from before. The change must refuse at once, not wait for a stale good read."""

    def __init__(self, change, **kw):
        super().__init__(**kw)
        self.change = change
        self.armed = False

    def __call__(self, *args: str) -> str:
        out = super().__call__(*args)
        if args[:3] == ("api", "-X", "POST") and args[3].startswith("https://uploads."):
            self.armed = True
        return out

    def _read(self):
        release, tag = super()._read()
        if self.armed and release is not None:
            self.armed = False
            bad = json.loads(json.dumps(release))
            self.change(bad)
            self.stale = 3  # the next reads show the good state from before
            return bad, tag
        return release, tag


@pytest.mark.parametrize("change, message", [
    (lambda r: r.update(target_commitish=OTHER), "changed while it was filled"),
    (lambda r: r["assets"].append({"id": 5, "name": "evil.whl", "digest": "sha256:00"}),
     "gained assets"),
    (lambda r: r["assets"][-1].update(digest="sha256:" + "0" * 64), "differs"),
])
def test_a_wrong_state_refuses_at_once(monkeypatch, dist, change, message):
    fake = Tampered(change)
    with pytest.raises(rs.Refused, match=message):
        run(monkeypatch, fake, dist)
    assert not any(c[:3] == ("api", "-X", "PATCH") for c in fake.calls)


def test_an_asset_without_its_digest_yet_is_waited_for(monkeypatch, dist):
    def no_digest(r):
        r["assets"][-1]["digest"] = None
    fake = Tampered(no_digest)
    run(monkeypatch, fake, dist)
    assert fake.release["draft"] is False


def test_settled_raises_a_refusal_only_on_the_last_try():
    answers = iter([rs.Refused("transient"), None, "ok"])

    def read():
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return a
    assert rs.settled(read, lambda r: r == "ok", "x") == "ok"

    def always():
        raise rs.Refused("down")
    with pytest.raises(rs.Refused, match="down"):
        rs.settled(always, lambda r: True, "x")


def test_main_rejects_a_bad_version(dist, capsys):
    assert rs.main(["pypi-pending", str(dist), "0.1.5rc1"]) == 1
    assert "X.Y.Z" in capsys.readouterr().out
