"""The repository, through the GitHub REST API: the commons as it is on main, the contributions still open, and a new
pull request.

The service writes with its own token (``SCALE_WEB_GITHUB_TOKEN``: a bot account's fine-grained token, or a GitHub
App's installation token, allowed to write contents and pull requests of the repository), never with the user's: the
pull request is the bot's, it credits the contributor by GitHub login, and a reviewer approves and merges it. Branches
are ``contrib/<slug>``; main is never written.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
BRANCH_PREFIX = "contrib/"


def http(method: str, url: str, token: str, body: dict | None = None, raw: bool = False):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "scale-catal web",
        **({"Content-Type": "application/json"} if data else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        out = r.read()
    return out.decode("utf-8") if raw else (json.loads(out) if out else {})


class Repo:
    def __init__(self, name: str, token: str, folder: str, request: Callable = http):
        self.name, self.token, self.folder, self.request = name, token, folder.strip("/"), request

    def _api(self, method: str, path: str, body: dict | None = None):
        return self.request(method, f"{API}/repos/{self.name}{path}", self.token, body)

    def _raw(self, sha: str, path: str) -> str:
        return self.request("GET", f"{RAW}/{self.name}/{sha}/{urllib.parse.quote(path)}", self.token, None, raw=True)

    def main_sha(self) -> str:
        return self._api("GET", "/git/ref/heads/main")["object"]["sha"]

    def fetch_folder(self, dest: Path, sha: str | None = None) -> str:
        """The commons folder as it is on main (or at ``sha``), written under ``dest``; returns the commit."""
        sha = sha or self.main_sha()
        tree = self._api("GET", f"/git/trees/{sha}?recursive=1")
        prefix = self.folder + "/"
        for item in tree.get("tree", []):
            if item["type"] == "blob" and item["path"].startswith(prefix):
                p = dest / item["path"][len(prefix):]
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(self._raw(sha, item["path"]), encoding="utf-8")
        return sha

    def open_contributions(self) -> list[dict]:
        """The open pull requests from ``contrib/`` branches, each with the source parts it adds."""
        out = []
        for pr in self._api("GET", "/pulls?state=open&per_page=100"):
            if not pr["head"]["ref"].startswith(BRANCH_PREFIX):
                continue
            files = self._api("GET", f"/pulls/{pr['number']}/files?per_page=100")
            parts = {}
            for f in files:
                path = f["filename"]
                if path.startswith(f"{self.folder}/parts/sources/") and path.endswith(".json") and f["status"] != "removed":
                    parts[Path(path).stem] = json.loads(self._raw(pr["head"]["sha"], path))
            out.append({"number": pr["number"], "url": pr["html_url"], "title": pr["title"], "sources": parts})
        return out

    def open_pull_request(self, base_sha: str, branch: str, files: dict[str, str], title: str, body: str,
                          message: str, reviewers: list[str] | None = None) -> dict:
        """One commit on a new branch from ``base_sha`` with ``files`` (paths in the commons folder), and its pull
        request against main."""
        base_tree = self._api("GET", f"/git/commits/{base_sha}")["tree"]["sha"]
        tree = self._api("POST", "/git/trees", {"base_tree": base_tree, "tree": [
            {"path": f"{self.folder}/{rel}", "mode": "100644", "type": "blob", "content": text}
            for rel, text in sorted(files.items())]})
        commit = self._api("POST", "/git/commits", {"message": message, "tree": tree["sha"], "parents": [base_sha]})
        try:
            self._api("POST", "/git/refs", {"ref": f"refs/heads/{branch}", "sha": commit["sha"]})
        except urllib.error.HTTPError as e:
            if e.code == 422:
                raise FileExistsError(f"the branch {branch} exists: this source has a contribution open") from e
            raise
        pr = self._api("POST", "/pulls", {"title": title, "head": branch, "base": "main", "body": body,
                                          "maintainer_can_modify": True})
        if reviewers:
            try:
                self._api("POST", f"/pulls/{pr['number']}/requested_reviewers", {"reviewers": reviewers})
            except urllib.error.HTTPError:
                pass                                    # the pull request stands; reviewers are asked by hand then
        return {"number": pr["number"], "url": pr["html_url"], "branch": branch}
