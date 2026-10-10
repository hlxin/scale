"""Is a newer tool published? The check reads the canonical repository's tags, caches the answer for a
day, never raises and never changes anything."""

import shutil
import subprocess

from scale import __version__
from scale.updates import remote_latest, tool_status


def test_remote_check_reads_tags_and_caches(tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    remote.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(remote), *a], check=True, capture_output=True)   # noqa: E731
    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "--allow-empty", "-m", "x")
    for t in ("v0.3.0", "v9.1.0", "v10.0.0"):
        git("tag", t)
    monkeypatch.delenv("SCALE_NO_UPDATE_CHECK", raising=False)
    res = remote_latest(tmp_path / "cache", url=str(remote))
    assert res["checked"] and res["latest_tag"] == "v10.0.0"
    shutil.rmtree(remote)                                                # second call is served from the cache
    assert remote_latest(tmp_path / "cache", url=str(remote))["cached"]
    assert remote_latest(tmp_path / "other", url=str(remote))["checked"] is False   # unreachable → no exception


def test_tool_notice_when_newer_tag_is_published(monkeypatch):
    import scale.updates as upd
    monkeypatch.setattr(upd, "remote_latest", lambda *a, **k: {"checked": True, "latest_tag": "v99.0.0",
                                                               "url": "https://example.org/x.git"})
    st = tool_status()
    assert st["tool_version"] == __version__
    assert "v99.0.0" in st["notice"] and "scale-catal@99.0.0" in st["notice"]
    monkeypatch.setattr(upd, "remote_latest", lambda *a, **k: {"checked": True, "latest_tag": f"v{__version__}"})
    assert "notice" not in tool_status()


def test_the_check_is_off_in_tests():
    assert remote_latest()["checked"] is False                         # conftest sets SCALE_NO_UPDATE_CHECK
