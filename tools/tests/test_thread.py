"""`scale thread N`: an issue or pull request with everything said on it, the line comments of reviews included, read
with GET requests only, oldest first."""

import json

from scale.thread import fetch, markdown

PR = {"title": "Rename", "state": "open", "user": {"login": "claude[bot]"}, "author_association": "NONE",
      "body": "Answers #16", "pull_request": {}}
COMMENTS = [{"created_at": "2026-10-11T13:10:00Z", "user": {"login": "ada"}, "author_association": "COLLABORATOR",
             "body": "Looks good overall."}]
REVIEWS = [{"submitted_at": "2026-10-11T13:20:00Z", "user": {"login": "ada"}, "author_association": "COLLABORATOR",
            "state": "CHANGES_REQUESTED", "body": "See the line comments."},
           {"submitted_at": None, "user": {"login": "ada"}, "state": "PENDING", "body": "draft"}]
LINES = [{"created_at": "2026-10-11T13:19:00Z", "user": {"login": "ada"}, "author_association": "COLLABORATOR",
          "path": "README.md", "line": 78, "diff_hunk": "@@ -75,4 +75,4 @@\n-scale-graph numbering\n+scale-catal numbering",
          "in_reply_to_id": None, "id": 7, "body": "This is history: keep scale-graph."}]


def runner(calls):
    def run(args):
        calls.append(args)
        path, _, query = args[0].partition("?")
        page = int(query.rsplit("page=", 1)[1]) if "page=" in query else 1
        data = {"repos/o/r/issues/20": PR, "repos/o/r/issues/20/comments": COMMENTS,
                "repos/o/r/pulls/20/reviews": REVIEWS, "repos/o/r/pulls/20/comments": LINES}[path]
        return json.dumps(data if page == 1 or not isinstance(data, list) else [])
    return run


def test_a_pull_request_thread_holds_its_line_comments_in_order():
    calls = []
    t = fetch(20, "o/r", runner(calls))
    assert t["kind"] == "pull request" and [e["kind"] for e in t["events"]] == ["comment", "line comment", "review"]
    line = t["events"][1]
    assert (line["path"], line["line"], line["body"]) == ("README.md", 78, "This is history: keep scale-graph.")
    assert all(not any(a in ("-X", "--method", "-f", "-F", "--field", "--raw-field", "--input") for a in c) for c in calls)
    text = markdown(t)
    assert "line comment by ada (COLLABORATOR) on `README.md` line 78" in text and "+scale-catal numbering" in text
    assert "CHANGES_REQUESTED" in text and "draft" not in text          # a pending review is not submitted


def test_an_issue_has_no_reviews():
    issue = {**PR, "body": "Please rename"}
    issue.pop("pull_request")
    run = lambda args: json.dumps({"repos/o/r/issues/16": issue}.get(args[0].partition("?")[0], []))  # noqa: E731
    t = fetch(16, "o/r", run)
    assert t["kind"] == "issue" and t["events"] == [] and "(no text)" not in markdown(t)
