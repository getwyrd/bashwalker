"""Tests for preflight.py, offline: gh and PyPI are replaced."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import preflight as pf  # noqa: E402

SHA = "a" * 40
ENV = {"GITHUB_REPOSITORY": "getwyrd/bashwalker", "GITHUB_REF": "refs/heads/main",
       "GITHUB_SHA": SHA}


class Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://pypi.org", code, "x", {}, io.BytesIO())


def opener_raising(exc):
    def opener(*args, **kwargs):
        raise exc
    return opener


PROTECTED = {"protection_rules": [{"type": "required_reviewers",
                                   "reviewers": [{"type": "User", "reviewer": {"id": 1}}]}],
             "deployment_branch_policy": {"protected_branches": False,
                                          "custom_branch_policies": True}}


def fake_gh(tags=(), runs=None, environment=PROTECTED):
    runs = [{"databaseId": 1, "headSha": SHA, "status": "completed", "conclusion": "success"}] \
        if runs is None else runs

    def gh(*args: str) -> str:
        if args[0] == "api" and "/environments/" in args[1]:
            if environment is None:
                raise pf.Refused("gh api failed: HTTP 404")
            return json.dumps(environment)
        if args[0] == "api":
            return json.dumps([{"ref": f"refs/tags/{t}"} for t in tags])
        if args[:2] == ("run", "list"):
            return json.dumps(runs)
        raise AssertionError(args)
    return gh


@pytest.fixture
def released(monkeypatch):
    """A repo where every check passes for version 0.1.5."""
    monkeypatch.setattr(pf, "project_version", lambda root=pf.ROOT: "0.1.5")
    monkeypatch.setattr(pf, "gh", fake_gh())
    monkeypatch.setattr(pf, "on_pypi", lambda v: False)
    return monkeypatch


def test_all_checks_pass(released):
    assert pf.preflight(ENV) == "0.1.5"


@pytest.mark.parametrize("ref", ["refs/heads/feature", "refs/tags/v0.1.5", ""])
def test_only_main(released, ref):
    with pytest.raises(pf.Refused, match="only from main"):
        pf.preflight(dict(ENV, GITHUB_REF=ref))


def test_existing_tag_refuses(released):
    released.setattr(pf, "gh", fake_gh(tags=["v0.1.5"]))
    with pytest.raises(pf.Refused, match="already exists"):
        pf.preflight(ENV)


def test_tag_prefix_is_not_a_match(released):
    released.setattr(pf, "gh", fake_gh(tags=["v0.1.50"]))
    assert pf.preflight(ENV) == "0.1.5"


def test_version_on_pypi_refuses(released):
    released.setattr(pf, "on_pypi", lambda v: True)
    with pytest.raises(pf.Refused, match="PyPI already has"):
        pf.preflight(ENV)


@pytest.mark.parametrize("runs, passes", [
    ([{"databaseId": 1, "headSha": SHA, "status": "completed", "conclusion": "failure"}], False),
    ([{"databaseId": 1, "headSha": SHA, "status": "in_progress", "conclusion": ""}], False),
    ([{"databaseId": 1, "headSha": SHA, "status": "completed", "conclusion": "success"},
      {"databaseId": 2, "headSha": SHA, "status": "completed", "conclusion": "failure"}], False),
    ([{"databaseId": 2, "headSha": SHA, "status": "completed", "conclusion": "success"},
      {"databaseId": 1, "headSha": SHA, "status": "completed", "conclusion": "failure"}], True),
])
def test_newest_ci_run_decides(released, runs, passes):
    released.setattr(pf, "gh", fake_gh(runs=runs))
    if passes:
        assert pf.preflight(ENV) == "0.1.5"
    else:
        with pytest.raises(pf.Refused, match="has not passed"):
            pf.preflight(ENV)


def test_no_ci_run_refuses(released):
    other = [{"databaseId": 1, "headSha": "b" * 40, "status": "completed", "conclusion": "success"}]
    released.setattr(pf, "gh", fake_gh(runs=other))
    with pytest.raises(pf.Refused, match="no ci.yml push run"):
        pf.preflight(ENV)


@pytest.mark.parametrize("environment", [
    {},
    {"protection_rules": [], "deployment_branch_policy": PROTECTED["deployment_branch_policy"]},
    {"protection_rules": PROTECTED["protection_rules"], "deployment_branch_policy": None},
    {"protection_rules": PROTECTED["protection_rules"],
     "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False}},
])
def test_unprotected_environment_refuses(released, environment):
    released.setattr(pf, "gh", fake_gh(environment=environment))
    with pytest.raises(pf.Refused, match="pypi environment"):
        pf.preflight(ENV)


def test_missing_environment_refuses(released):
    released.setattr(pf, "gh", fake_gh(environment=None))
    with pytest.raises(pf.Refused, match="404"):
        pf.preflight(ENV)


def test_unreadable_gh_answer_refuses(released):
    released.setattr(pf, "gh", lambda *a: "not json")
    with pytest.raises(pf.Refused, match="unreadable"):
        pf.preflight(ENV)


def test_bad_sha_refuses(released):
    with pytest.raises(pf.Refused, match="missing"):
        pf.preflight(dict(ENV, GITHUB_SHA="main"))


def test_pypi_answers():
    assert pf.on_pypi("0.1.5", opener=lambda *a, **k: Response(200)) is True
    assert pf.on_pypi("0.1.5", opener=opener_raising(http_error(404))) is False
    for exc in (http_error(503), urllib.error.URLError("down"), TimeoutError()):
        with pytest.raises(pf.Refused):
            pf.on_pypi("0.1.5", opener=opener_raising(exc))


@pytest.mark.parametrize("text, ok", [
    ('[project]\nversion = "0.1.5"\n', True),
    ('[project]\nversion = "0.1.5rc1"\n', False),
    ('[project]\nversion = "v0.1.5"\n', False),
    ('[project]\nname = "x"\n', False),
    ("not toml [", False),
])
def test_project_version(tmp_path, text, ok):
    (tmp_path / "pyproject.toml").write_text(text)
    if ok:
        assert pf.project_version(tmp_path) == "0.1.5"
    else:
        with pytest.raises(pf.Refused):
            pf.project_version(tmp_path)


def test_this_repos_version_is_valid():
    assert pf.VERSION.fullmatch(pf.project_version())
