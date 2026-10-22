"""Community feedback intake: ingest → cluster → propose → a weekly digest for the reviewers.

Anyone comments through GitHub issues, pull-request comments or discussions. On a schedule,
``scale triage`` turns that feedback into a digest of topics for the reviewers:

1. **ingest** — fetch items updated since the last run (``gh`` CLI, or a JSON export),
   normalize them, extract references (record ids, labels and edge types, DOIs, gaps, proposals,
   competency questions) and classify them with transparent rules;
2. **cluster** — group items about the same thing (same thread, shared references,
   near-duplicate titles);
3. **propose** — for each cluster, list decision paths with who must review and what each
   path changes. Proposals come from the built-in rules or from *any* external agent system
   that reads ``queue.json`` and writes ``proposals.json`` (validated against
   ``skills/triage-feedback/proposal.schema.json``);
4. **digest** — render one feedback digest (and optionally publish it as an issue).

Nothing is decided in the digest. A person acts on a topic by opening a pull request (or by labelling the
@scale-agents, .github/workflows/scale-agents.yml, open one on their own); the decision is the pull
request's approving review (governance/review-policy.yaml). Agents never decide. Writing to GitHub is dry-run unless ``--publish`` is given.
"""

from __future__ import annotations

import datetime as _dt
import difflib
import json
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import __version__, layout
from .util import ScaleError, load_doc

MARKER_STATE = "scale-triage-state"
MARKER_ITEM = "<!-- scale-triage:item -->"
DIGEST_LABEL = "feedback-digest"

CATEGORIES = {
    "missing_concept": "The representation cannot express something",
    "extraction_error": "A curated value or locator looks wrong",
    "source_information": "The source is silent, ambiguous or inconsistent",
    "new_source": "A source is proposed for curation",
    "competency_question": "A question the graph should be able to answer",
    "mapping": "Vocabulary or ontology mapping",
    "tooling": "Software, installation or documentation",
    "question": "A question about use",
    "general_comment": "A comment or suggestion to be read by a person",
}

LABEL_RULES = {
    "gap:missing-concept": "missing_concept", "gap:extraction-error": "extraction_error",
    "gap:absent-source-information": "source_information", "gap:ambiguous-source-information": "source_information",
    "new-source": "new_source", "competency-question": "competency_question", "mapping": "mapping",
    "bug": "tooling", "documentation": "tooling", "question": "question",
}

KEYWORD_RULES: list[tuple[str, str]] = [
    ("missing_concept", r"cannot (be )?(express|represent)|can't (express|represent)|no (field|slot|way to (represent|record))|missing concept|need(s)? a (field|slot|class|label|property|concept)|not expressible|schema (lacks|gap)"),
    ("extraction_error", r"wrong value|incorrect(ly)?|mis-?quoted|typo in (the )?(value|record)|should (be|read) [\"'\d]|does not match (the )?(source|paper)|transposed|mismatch"),
    ("source_information", r"not reported|ambiguous|inconsisten|conflict(s|ing)? (in|with) the (paper|source)|the (paper|source) (does not|doesn't) (say|state|report)"),
    ("new_source", r"(please )?(curate|add|include) (this|the following|these) (paper|article|study|dataset|source)s?"),
    ("competency_question", r"competency question|should be able to (answer|query|find)|can (we|i) query"),
    ("mapping", r"voc4cat|chebi|qudt|ontology|vocabulary|exactmatch|closematch|maps? to"),
    ("tooling", r"traceback|exception|install(ation)?|pip |uvx|crash|error:|ci (fails|failed)|typo in (the )?(docs|readme)"),
    ("question", r"^(how|what|which|why|where|can|does|is) .*\?|\bquestion\b"),
]

PATTERNS = {
    "doi": re.compile(r"\b10\.\d{4,9}/[^\s\"'<>)\]]+", re.I),
    "gap": re.compile(r"\bGAP-[0-9A-F]{8}\b"),
    # a proposal: its six-digit number where the text says it is one ("proposal 000001", "Proposal #000001",
    # ".../proposals/000001"); a bare six-digit number may be anything
    "proposal": re.compile(r"(?:(?<=[Pp]roposal )|(?<=[Pp]roposal #)|(?<=proposals/))\d{6}\b"),
    "competency": re.compile(r"\bCQ-\d{2,}\b"),
    "issue_ref": re.compile(r"(?<![\w/])#(\d+)\b"),
}


# ---------------------------------------------------------------- data

@dataclass
class Item:
    key: str                      # e.g. issue-12, comment-981, review-44, discussion-7, dcomment-X
    kind: str                     # issue | pull_request | comment | review_comment | discussion | discussion_comment
    url: str
    author: str
    created_at: str
    updated_at: str
    body: str = ""
    title: str = ""
    number: int | None = None     # issue / PR / discussion number
    thread: str = ""              # key of the root issue/PR/discussion
    labels: list[str] = field(default_factory=list)
    state: str = "open"
    author_association: str = ""
    refs: dict = field(default_factory=dict)
    category: str = ""
    category_basis: str = ""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- fetch

def _gh_json(args: list[str]) -> Any:
    if shutil.which("gh") is None:
        raise ScaleError("gh CLI not found; install it, or pass --from-file with exported items")
    proc = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise ScaleError(f"gh api {' '.join(args[:3])} failed: {proc.stderr.strip()[:300]}")
    out = proc.stdout.strip()
    if not out:
        return []
    data = json.loads(out)
    # --paginate --slurp yields a list of pages
    if isinstance(data, list) and data and all(isinstance(p, list) for p in data):
        return [x for page in data for x in page]
    return data


def fetch_github(repo: str, since: str | None, discussions: bool = True) -> list[dict]:
    """Raw GitHub objects updated since ``since`` (ISO 8601), tagged with ``_kind``."""
    q = ["-f", f"since={since}"] if since else []
    raw: list[dict] = []
    for obj in _gh_json(["-X", "GET", f"repos/{repo}/issues", "-f", "state=all", "-f", "per_page=100", *q, "--paginate", "--slurp"]):
        raw.append({**obj, "_kind": "pull_request" if obj.get("pull_request") else "issue"})
    for obj in _gh_json(["-X", "GET", f"repos/{repo}/issues/comments", "-f", "per_page=100", *q, "--paginate", "--slurp"]):
        raw.append({**obj, "_kind": "comment"})
    for obj in _gh_json(["-X", "GET", f"repos/{repo}/pulls/comments", "-f", "per_page=100", *q, "--paginate", "--slurp"]):
        raw.append({**obj, "_kind": "review_comment"})
    if discussions:
        owner, name = repo.split("/", 1)
        query = """query($owner:String!,$name:String!){repository(owner:$owner,name:$name){discussions(first:50,orderBy:{field:UPDATED_AT,direction:DESC}){nodes{number title body url createdAt updatedAt author{login} category{name} comments(first:50){nodes{id body url createdAt updatedAt author{login}}}}}}}"""
        try:
            data = _gh_json(["graphql", "-f", f"query={query}", "-f", f"owner={owner}", "-f", f"name={name}"])
            for d in data["data"]["repository"]["discussions"]["nodes"]:
                if since and d["updatedAt"] < since:
                    continue
                raw.append({**d, "_kind": "discussion"})
                for c in d["comments"]["nodes"]:
                    raw.append({**c, "_kind": "discussion_comment", "_discussion": d["number"]})
        except (ScaleError, KeyError, TypeError):
            pass  # discussions disabled or not permitted: skip, do not fail the run
    return raw


def normalize(raw: list[dict]) -> list[Item]:
    items: list[Item] = []
    for o in raw:
        kind = o.get("_kind")
        user = (o.get("user") or o.get("author") or {}) or {}
        if user.get("type") == "Bot" or MARKER_ITEM in (o.get("body") or "") or DIGEST_LABEL in [l.get("name") for l in o.get("labels", []) if isinstance(l, dict)]:
            continue  # skip bots and the triage system's own output
        login = user.get("login", "ghost")
        common = dict(url=o.get("html_url") or o.get("url", ""), author=login,
                      created_at=o.get("created_at") or o.get("createdAt", ""),
                      updated_at=o.get("updated_at") or o.get("updatedAt", ""),
                      body=o.get("body") or "", author_association=o.get("author_association", ""))
        if kind in ("issue", "pull_request"):
            n = o["number"]
            items.append(Item(key=f"{'pr' if kind == 'pull_request' else 'issue'}-{n}", kind=kind, number=n,
                              thread=f"{'pr' if kind == 'pull_request' else 'issue'}-{n}", title=o.get("title", ""),
                              labels=[l["name"] if isinstance(l, dict) else l for l in o.get("labels", [])],
                              state=o.get("state", "open"), **common))
        elif kind == "comment":
            n = int(str(o.get("issue_url", "")).rstrip("/").split("/")[-1] or 0)
            items.append(Item(key=f"comment-{o['id']}", kind=kind, number=n, thread=f"issue-{n}", **common))
        elif kind == "review_comment":
            n = int(str(o.get("pull_request_url", "")).rstrip("/").split("/")[-1] or 0)
            body = common.pop("body")
            path = o.get("path")
            items.append(Item(key=f"review-{o['id']}", kind=kind, number=n, thread=f"pr-{n}",
                              body=(f"[on {path}] " if path else "") + body, **common))
        elif kind == "discussion":
            n = o["number"]
            items.append(Item(key=f"discussion-{n}", kind=kind, number=n, thread=f"discussion-{n}",
                              title=o.get("title", ""), labels=[f"discussion:{(o.get('category') or {}).get('name', '')}"], **common))
        elif kind == "discussion_comment":
            n = o["_discussion"]
            items.append(Item(key=f"dcomment-{o['id']}", kind=kind, number=n, thread=f"discussion-{n}", **common))
    return items


# ---------------------------------------------------------------- references and classification

@dataclass
class Vocabulary:
    record_ids: set[str]
    classes: set[str]
    prefixes: set[str]

    @classmethod
    def from_repo(cls, repo: Path) -> "Vocabulary":
        """The names feedback may mention: the labels and edge types of every domain's scale-catal schema
        (head and frozen versions: feedback may name a concept a later version replaced), and the record
        ids and prefixes of the example graphs."""
        from . import pgraph
        classes: set[str] = set()
        for man in layout.graph_manifests(repo, experimental=True).values():
            for m in [man, *sorted(layout.frozen_graph_dir(man).glob("scale-catal-*.yaml"))]:
                try:
                    spec = pgraph.load_spec(m)
                except (ScaleError, OSError):
                    continue
                classes |= set(spec.get("nodes") or {}) | set(spec.get("abstract") or {}) | set(spec.get("edges") or {})
        ids: set[str] = set()
        prefixes: set[str] = set()
        for p in [x for base in layout.example_roots(repo) for x in base.rglob("*.json")
                  if not layout.is_excluded(x.relative_to(repo))]:
            try:
                doc = load_doc(p)
            except Exception:
                continue
            if isinstance(doc, dict) and isinstance(doc.get("graph"), dict) and isinstance(doc.get("nodes"), list):
                recs = [r for r in doc["nodes"] + (doc.get("links") or []) if isinstance(r, dict) and "id" in r]
                ids |= {r["id"] for r in recs}
                prefixes |= {r["id"].split(":", 1)[0] for r in recs if ":" in r["id"]}
        return cls(ids, classes, prefixes)


def extract_refs(text: str, vocab: Vocabulary) -> dict:
    refs: dict[str, list] = {k: sorted(set(p.findall(text))) for k, p in PATTERNS.items()}
    refs["issue_ref"] = sorted({int(x) for x in refs["issue_ref"]})
    pre = "|".join(sorted((re.escape(p) for p in vocab.prefixes), key=len, reverse=True)) or "ex"
    cand = set(re.findall(rf"\b(?:{pre}):[A-Za-z0-9_./-]*[A-Za-z0-9_]", text))
    refs["records"] = sorted(c for c in cand if c in vocab.record_ids)
    refs["unknown_records"] = sorted(c for c in cand if c not in vocab.record_ids and "/" in c)
    refs["classes"] = sorted(c for c in vocab.classes if re.search(rf"\b{c}\b", text))
    return {k: v for k, v in refs.items() if v}


def classify(item: Item) -> tuple[str, str]:
    for lab in item.labels:
        if lab in LABEL_RULES:
            return LABEL_RULES[lab], f"label {lab}"
    text = f"{item.title}\n{item.body}".lower()
    for cat, rx in KEYWORD_RULES:
        if re.search(rx, text, re.M):
            if cat == "extraction_error" and not item.refs.get("records") and not item.refs.get("doi"):
                continue  # claims of wrong values need a record or source reference
            return cat, f"keyword rule {cat}"
    if item.refs.get("doi") and not item.refs.get("records"):
        return "new_source", "mentions a DOI not yet in the graph"
    return "general_comment", "no rule matched; read by a person"


# ---------------------------------------------------------------- clustering

PRIORITY = ["missing_concept", "extraction_error", "source_information", "competency_question", "mapping",
            "new_source", "tooling", "question", "general_comment"]


def cluster(items: list[Item]) -> list[dict]:
    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_key = {i.key: i for i in items}
    for i in items:
        find(i.key)
        union(i.key, i.thread) if i.thread in by_key else None
    shared: dict[str, list[str]] = {}
    for i in items:
        for k in ("gap", "proposal", "competency", "records"):
            for r in i.refs.get(k, []):
                shared.setdefault(f"{k}:{r}", []).append(i.thread or i.key)
        for n in i.refs.get("issue_ref", []):
            for t in (f"issue-{n}", f"pr-{n}"):
                if t in by_key:
                    union(i.thread or i.key, t)
    for keys in shared.values():
        for k in keys[1:]:
            if k in by_key and keys[0] in by_key:
                union(keys[0], k)
    roots = [i for i in items if i.kind in ("issue", "pull_request", "discussion")]
    for a_idx, a in enumerate(roots):
        for b in roots[a_idx + 1:]:
            if a.title and b.title and difflib.SequenceMatcher(None, a.title.lower(), b.title.lower()).ratio() > 0.85:
                union(a.key, b.key)
    groups: dict[str, list[Item]] = {}
    for i in items:
        root = find(i.thread) if i.thread in by_key else find(i.key)
        groups.setdefault(root, []).append(i)
    clusters = []
    for root, members in groups.items():
        members.sort(key=lambda x: x.created_at)
        cats = {m.category for m in members}
        category = next(c for c in PRIORITY if c in cats)
        head = next((m for m in members if m.title), members[0])
        refs: dict[str, set] = {}
        for m in members:
            for k, v in m.refs.items():
                refs.setdefault(k, set()).update(v)
        anchor = next((m for m in members if m.kind in ("issue", "pull_request", "discussion")), members[0])
        cid = "T" + {"issue": "", "pull_request": "P", "discussion": "D"}.get(anchor.kind, "C") + str(anchor.number or anchor.key.split("-")[-1])
        clusters.append({
            "cluster_id": cid, "category": category, "category_label": CATEGORIES[category],
            "title": head.title or (head.body[:80] + ("…" if len(head.body) > 80 else "")),
            "participants": sorted({m.author for m in members}),
            "items": [{"key": m.key, "kind": m.kind, "url": m.url, "author": m.author, "category": m.category,
                       "basis": m.category_basis, "excerpt": (m.title + " — " if m.title else "") + m.body[:400]} for m in members],
            "refs": {k: sorted(v) for k, v in refs.items()},
            "updated_at": max(m.updated_at for m in members),
        })
    clusters.sort(key=lambda c: (PRIORITY.index(c["category"]), -len(c["participants"]), c["cluster_id"]))
    return clusters


def ingest(raw: list[dict], vocab: Vocabulary) -> dict:
    items = normalize(raw)
    for i in items:
        i.refs = extract_refs(f"{i.title}\n{i.body}", vocab)
        i.category, i.category_basis = classify(i)
    clusters = cluster(items)
    return {"generated_at": _now(), "scale_version": __version__, "items": [asdict(i) for i in items],
            "clusters": clusters, "summary": {c: sum(1 for k in clusters if k["category"] == c) for c in CATEGORIES}}


# ---------------------------------------------------------------- proposals

REVIEWERS = {
    "missing_concept": ["domain"], "extraction_error": ["domain"], "source_information": ["domain"],
    "new_source": ["domain"], "competency_question": ["domain"], "mapping": ["domain"],
    "tooling": ["maintainer"], "question": [], "general_comment": ["maintainer"],
}


def rule_proposal(c: dict) -> dict:
    cat, refs = c["category"], c.get("refs", {})
    recs = ", ".join(refs.get("records", [])) or "the records referenced"
    O = lambda i, action, desc, cons: {"id": i, "action": action, "description": desc, "consequence": cons}
    opts = {
        "missing_concept": [
            O("A", "change_schema", "Change the schema in a pull request (skills/evolve-schema): the edit, fixtures, counterexamples, the version raised, affected queries.",
              "New concepts enter as provisional; the pull request needs one person's approving review "
              "(@scale-agents open it on their own)."),
            O("B", "map_to_existing", "Show that an existing label, edge type or property (or an external vocabulary term) already expresses it" +
              (f" (labels mentioned: {', '.join(refs['classes'])})" if refs.get("classes") else "") + "; document how to use it.",
              "No schema change; curation guidance updated."),
            O("C", "defer_discussion", "Move to a discussion to collect more use cases before modeling.", "No change now.")],
        "extraction_error": [
            O("A", "re_extract", f"Re-check {recs} against the source and correct the record (skills/curate-corpus).",
              "Record values change; the documents' tests updated in the same PR."),
            O("B", "not_an_error", "Explain why the recorded value matches the source (quote and locator).", "No change."),
            O("C", "source_ambiguity", "Record the ambiguity as ambiguous_in_source and keep both readings.", "Record gains explicit missingness (missing_reason ambiguous_in_source).")],
        "source_information": [
            O("A", "record_missingness", f"Declare the value missing with the right reason on {recs}.", "Queries that need it report missing_context."),
            O("B", "seek_source", "Look in SI / source data or contact the authors; re-curate if found.", "Possible record update later.")],
        "new_source": [
            O("A", "curate", "Curate the source (check licence first; short excerpts only).", "New records under the current schema version."),
            O("B", "decline", "Out of scope or licence does not allow curation; explain.", "No change.")],
        "competency_question": [
            O("A", "add_competency_question", "Add domain/competency/cq-NN with a graph query plan, the public documents it runs on and its expectation; `scale domains cq` runs it.",
              "If it returns a schema gap, a missing_concept path follows."),
            O("B", "answer_existing", "Show an existing plan already answers it.", "Documentation only.")],
        "mapping": [
            O("A", "add_mapping", "Record the correspondence (an exact or close match to the external term) where the label or property is described, in a pull request.", "Schema description changes."),
            O("B", "decline", "Explain why the relation does not hold.", "No change.")],
        "tooling": [
            O("A", "fix", "Fix in a normal pull request with tests.", "No scientific meaning change."),
            O("B", "close", "Cannot reproduce or not a defect; explain.", "No change.")],
        "question": [O("A", "answer", "Answer with pointers to docs/skills; convert to a competency question if it reveals a gap.", "None.")],
        "general_comment": [
            O("A", "acknowledge", "Acknowledge and link to the relevant doc or issue.", "None."),
            O("B", "convert", "Convert into a specific issue (missing concept, extraction error, source information, competency question).",
              "Enters the matching path next cycle.")],
    }[cat]
    return {"cluster_id": c["cluster_id"], "category": cat, "summary": c["title"], "options": opts,
            "recommended_option": None, "rationale": "Rule-based proposal; no option is recommended — experts decide.",
            "reviewers_required": REVIEWERS[cat], "decision_needed": bool(REVIEWERS[cat]) and cat not in ("question",),
            "confidence": 0.5, "proposed_by": f"scale rules {__version__}"}


def validate_proposal(p: dict, clusters: dict[str, dict]) -> list[str]:
    """Check an externally produced proposal (see skills/triage-feedback/proposal.schema.json)."""
    errs = []
    for k in ("cluster_id", "category", "summary", "options", "proposed_by"):
        if k not in p:
            errs.append(f"missing {k}")
    if errs:
        return errs
    if p["cluster_id"] not in clusters:
        errs.append(f"unknown cluster {p['cluster_id']}")
    if p["category"] not in CATEGORIES:
        errs.append(f"unknown category {p['category']}")
    ids = [o.get("id") for o in p["options"]]
    if not p["options"] or len(ids) != len(set(ids)) or not all(o.get("action") and o.get("description") for o in p["options"]):
        errs.append("options must be non-empty with unique ids, an action and a description")
    if p.get("recommended_option") not in (None, *ids):
        errs.append("recommended_option is not one of the options")
    if not isinstance(p.get("confidence", 0.5), (int, float)) or not 0 <= p.get("confidence", 0.5) <= 1:
        errs.append("confidence must be between 0 and 1")
    if p.get("decision") or p.get("approved"):
        errs.append("proposals may not contain decisions; humans decide")
    return errs


def merge_proposals(queue: dict, external: list[dict] | None) -> tuple[list[dict], list[dict]]:
    clusters = {c["cluster_id"]: c for c in queue["clusters"]}
    by_id = {c: rule_proposal(cl) for c, cl in clusters.items()}
    rejected = []
    for p in external or []:
        errs = validate_proposal(p, clusters)
        if errs:
            rejected.append({"cluster_id": p.get("cluster_id"), "errors": errs})
            continue
        p.setdefault("reviewers_required", REVIEWERS[p["category"]])
        p.setdefault("decision_needed", True)
        by_id[p["cluster_id"]] = p
    return [by_id[c] for c in clusters], rejected


# ---------------------------------------------------------------- digest

def render_digest(queue: dict, proposals: list[dict], repo: str, since: str | None, rejected: list[dict]) -> str:
    clusters = {c["cluster_id"]: c for c in queue["clusters"]}
    need = [p for p in proposals if p.get("decision_needed")]
    info = [p for p in proposals if not p.get("decision_needed")]
    L = [f"# SCALE feedback digest — {queue['generated_at'][:10]}", "",
         f"Feedback since `{since or 'the beginning'}`: **{len(queue['items'])}** items in **{len(queue['clusters'])}** topics; "
         f"**{len(need)}** may need a change.", "",
         "**How to act on a topic:** open a pull request that takes one of its options (or comment on the issue with the "
         "option, and @scale-agents open a pull request on their own). Every "
         "change is decided by an approving review of its pull request (governance/review-policy.yaml). Agents "
         "prepared these options; they do not decide.", ""]
    for p in need + info:
        c = clusters[p["cluster_id"]]
        L += [f"## {p['cluster_id']} · {CATEGORIES[p['category']]} — {p['summary']}", "",
              f"Participants: {', '.join('@' + a for a in c['participants'])} · reviewers needed: "
              f"{', '.join(p.get('reviewers_required') or ['none'])} · proposed by: {p['proposed_by']}"
              + (f" (confidence {p['confidence']:.1f})" if isinstance(p.get("confidence"), (int, float)) else ""), ""]
        for it in c["items"][:6]:
            L.append(f"- [{it['kind']}]({it['url']}) by @{it['author']}: {it['excerpt'][:160].replace(chr(10), ' ')}")
        if len(c["items"]) > 6:
            L.append(f"- … {len(c['items']) - 6} more")
        if c["refs"]:
            L.append("- references: " + "; ".join(f"{k}: {', '.join(map(str, v))}" for k, v in c["refs"].items()))
        L += ["", "| option | action | what it means | consequence |", "|---|---|---|---|"]
        for o in p["options"]:
            star = " ⭐" if o["id"] == p.get("recommended_option") else ""
            L.append(f"| **{o['id']}**{star} | `{o['action']}` | {o['description']} | {o.get('consequence', '')} |")
        if p.get("rationale"):
            L += ["", f"_Rationale:_ {p['rationale']}"]
        L.append("")
    if rejected:
        L += ["## Proposals rejected by validation", ""] + [f"- {r['cluster_id']}: {'; '.join(r['errors'])}" for r in rejected] + [""]
    state = {"since": queue["generated_at"], "repo": repo, "clusters": [p["cluster_id"] for p in proposals]}
    L.append(f"<!-- {MARKER_STATE}: {json.dumps(state)} -->")
    return "\n".join(L) + "\n"


def last_state(repo: str) -> dict | None:
    issues = _gh_json(["-X", "GET", f"repos/{repo}/issues", "-f", f"labels={DIGEST_LABEL}", "-f", "state=all", "-f", "per_page=1"])
    if not issues:
        return None
    m = re.search(rf"<!-- {MARKER_STATE}: (.*?) -->", issues[0].get("body") or "")
    return json.loads(m.group(1)) | {"issue": issues[0]["number"]} if m else None


def publish_digest(repo: str, body: str, queue: dict, dry_run: bool = True) -> dict:
    title = f"SCALE feedback digest — {queue['generated_at'][:10]}"
    threads = sorted({i["thread"] for i in queue["items"] if i["thread"].startswith(("issue-", "pr-"))})
    if dry_run:
        return {"dry_run": True, "would_create_issue": title, "would_comment_on": threads}
    proc = subprocess.run(["gh", "issue", "create", "--repo", repo, "--title", title, "--label", DIGEST_LABEL, "--body", body],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise ScaleError(proc.stderr.strip())
    url = proc.stdout.strip()
    notified = []
    for thread in threads:
        num = thread.split("-")[1]
        msg = f"{MARKER_ITEM}\nThanks! This feedback is in the SCALE feedback digest for the reviewers: {url}"
        subprocess.run(["gh", "issue", "comment", num, "--repo", repo, "--body", msg], capture_output=True, text=True)
        notified.append(thread)
    return {"dry_run": False, "digest": url, "notified": notified}


def suggest_url(repo: str, record: str | None, text: str, title: str | None = None) -> str:
    """A pre-filled 'comment or suggestion' issue URL — no tooling needed by the commenter."""
    from urllib.parse import urlencode
    params = {"template": "comment.yml", "title": title or (f"Comment on {record}" if record else "Comment"),
              "record": record or "", "comment": text}
    return f"https://github.com/{repo}/issues/new?{urlencode(params)}"


def catalogue_markdown(doc: dict, repo: str) -> str:
    """A readable catalogue of a scale-catal document's records, with a pre-filled comment link per record."""
    g = doc.get("graph") or {}
    nodes = {n["id"]: n for n in doc.get("nodes", [])}
    cell = lambda x: str(x).replace("|", "\\|").replace("\n", " ")   # noqa: E731

    def value(props: dict) -> str:
        def one(k: str, v: dict) -> str:
            if v["status"] != "present":
                return f"{k}: {v['status']}"
            target = v.get("target")
            target = f" ({(nodes[target].get('props') or {}).get('name') or target})" if target in nodes else (
                f" ({target})" if target else "")
            return f"{k} {v.get('value', '')} {v.get('unit', '')}".strip() + target
        shown = []
        for k, v in props.items():
            items = v if isinstance(v, list) else [v]
            shown += [one(k, x) for x in items if isinstance(x, dict) and "status" in x]
        return "; ".join(shown)
    L = [f"# Records: {g.get('title') or g.get('graph_id', '')}", "",
         f"scale-catal `{g.get('schema_version')}` · follows {', '.join(g.get('follows_domains') or []) or 'no checklist'}. "
         "Generated by `scale catalogue`; do not edit by hand.", "",
         (g.get("scope") or g.get("description") or "").strip(), "",
         f"**Spotted something?** Use the 💬 link next to any record, or [open a comment]({suggest_url(repo, None, '')}). "
         "No knowledge of the schema is needed.", ""]
    for lab in sorted({n["label"] for n in nodes.values()}):
        L += [f"## {lab}", "", "| record | name | values | evidence | |", "|---|---|---|---|---|"]
        for n in sorted((n for n in nodes.values() if n["label"] == lab), key=lambda n: n["id"]):
            props = n.get("props") or {}
            ev = [", ".join(str(x) for x in [e.get("source"), e.get("locator")] if x)
                  for e in props.get("evidence") or [] if isinstance(e, dict)]
            link = suggest_url(repo, n["id"], f"About {n['id']} ({props.get('name', '')}): ")
            L.append(f"| `{n['id']}` | {cell(props.get('name', ''))} | {cell(value(props))[:160]} | "
                     f"{cell('; '.join(ev))[:120]} | [💬]({link}) |")
        L.append("")
    return "\n".join(L) + "\n"
