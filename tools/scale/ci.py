"""``scale ci spec-changes | proposals | proposal-check``: what a pull request may change, who must review
it, and the proposals it carries.

CI runs this on every pull request (job ``specification-changes``). It compares the branch with the
merge base of ``<ref>`` (what GitHub shows as the pull request's diff) and fails when the branch

- modifies, deletes or adds files inside a release (``releases/<id>/``, a directory holding RELEASE.yaml at
  the merge base) or modifies or deletes a frozen schema file: the frozen kernels in ``core/graph/frozen/`` or
  the catalysis domain's frozen versions in ``domain/graph/frozen/`` (each SHA256SUMS may only gain lines). New
  releases and new frozen versions are additions and pass; README and CHANGELOG files directly under
  ``releases/`` may change;
- changes the specification (``core/graph/``, or the catalysis domain's ``domain/graph/`` files, its schema
  manifest ``graph/scale-graph.yaml`` included, unless the domain is experimental) without adding or
  updating a proposal (``core/proposals/<NNNNNN>/``, ``domain/proposals/<NNNNNN>/``) or a decision record
  (``docs/decisions/``).

It also prints whose review the change needs according to ``.github/CODEOWNERS`` at the merge base
(GitHub reads the base branch's file), and the maintainers of the catalysis domain to consult when ``core/``
changes. The rules are path tests anchored at the repository root.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

from . import codeowners, layout
from .util import ScaleError, load_doc

ALLOWED_RELEASE_NOTES = re.compile(r"^releases/(README|CHANGELOG)(\.md)?$")
SPEC = [re.compile(r"^core/graph/")]
# additions only; SHA256SUMS append-only
FROZEN = re.compile(r"^(core/graph/frozen/|domain/graph/frozen/)")
# a proposal folder is its six-digit number (global; layout.proposal_dirs refuses any other name)
RECORDS = [re.compile(r"^core/proposals/\d{6}/"), re.compile(r"^domain/proposals/\d{6}/"),
           re.compile(r"^docs/decisions/\d{4}-[^/]+\.md$")]
PROPOSAL_PATH = re.compile(r"^(?:core|domain)/proposals/(\d{6})/")


def load_yaml_text(text: str):
    return yaml.safe_load(text)


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if res.returncode != 0:
        raise ScaleError(f"git {' '.join(args)}: {res.stderr.strip() or res.stdout.strip()}")
    return res.stdout


def changed_files(repo: Path, base: str, head: str = "HEAD") -> tuple[str, list[tuple[str, str]]]:
    """(merge base, [(status, path)]) for the branch ``head`` against ``base``; renames count as a
    deletion plus an addition, so moving a file out of a release is a deletion."""
    mb = _git(repo, "merge-base", base, head).strip()
    fields = _git(repo, "diff", "--name-status", "--no-renames", "-z", mb, head).split("\0")
    return mb, [(fields[i][0], fields[i + 1]) for i in range(0, len(fields) - 1, 2)]


def _blob(repo: Path, ref: str, path: str) -> str | None:
    res = subprocess.run(["git", "rev-parse", "--verify", "-q", f"{ref}:{path}"], cwd=repo, capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 else None


def _show(repo: Path, ref: str, path: str) -> str | None:
    res = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=repo, capture_output=True, text=True)
    return res.stdout if res.returncode == 0 else None


def _ls(repo: Path, ref: str, path: str) -> list[str]:
    return [f for f in _git(repo, "ls-tree", "-r", "-z", "--name-only", ref, "--", path).split("\0") if f]


def _release_dirs(repo: Path, ref: str) -> list[str]:
    """Archived release directories at ``ref``: those holding a RELEASE.yaml."""
    files = _ls(repo, ref, layout.RELEASES)
    return sorted({f.rsplit("/", 1)[0] for f in files if f.endswith("/RELEASE.yaml")})


def _domain_status(repo: Path, ref: str, decl: str) -> str | None:
    """The status a domain's DOMAIN.yaml (``decl``, repository-relative) states at ``ref``."""
    text = _show(repo, ref, decl)
    try:
        return (load_yaml_text(text) or {}).get("status") if text is not None else None
    except yaml.YAMLError:       # an unreadable DOMAIN.yaml is reported by `scale domains check`
        return None


def spec_changes(repo: Path, base: str, head: str = "HEAD") -> dict:
    repo = Path(repo).resolve()
    mb, rows = changed_files(repo, base, head)
    releases = _release_dirs(repo, mb)
    violations: list[str] = []
    for status, path in rows:
        if FROZEN.match(path):
            if path.endswith(f"/{layout.FROZEN_SUMS}") and status == "M":
                old, new = _show(repo, mb, path) or "", _show(repo, head, path) or ""
                if not new.startswith(old):
                    violations.append(f"{path}: existing lines changed; SHA256SUMS may only gain lines")
            elif status != "A":
                violations.append(f"{path}: {'deletes' if status == 'D' else 'modifies'} a frozen schema file; frozen "
                                  "versions are additions only")
            continue
        if not path.startswith(f"{layout.RELEASES}/") or ALLOWED_RELEASE_NOTES.match(path):
            continue
        inside = next((d for d in releases if path.startswith(d + "/")), None)
        if inside:
            verb = {"M": "modifies a file of", "D": "deletes a file of", "A": "adds a file to"}.get(status, "changes a file of")
            violations.append(f"{path}: {verb} the release {inside}; releases are immutable (build a new one)")
        elif status != "A":
            violations.append(f"{path}: {'deletes' if status == 'D' else 'modifies'} a file under releases/; only "
                              "README and CHANGELOG files directly under releases/ may change")

    statuses: dict[str, str | None] = {}

    def spec_file(path: str) -> bool:
        if any(rx.match(path) for rx in SPEC):
            return True
        if not re.match(rf"^{layout.DOMAIN}/graph/", path):
            return False
        decl = layout.DOMAIN_DECLARATION
        if decl not in statuses:         # experimental only if experimental at both ends: a promotion PR (stable at
            # head) and a demotion PR (stable at the base) count as stable; an unknown status counts as stable
            known = {s for s in (_domain_status(repo, head, decl), _domain_status(repo, mb, decl)) if s is not None}
            statuses[decl] = "experimental" if known == {"experimental"} else "stable"
        return statuses[decl] != "experimental"

    spec = sorted(p for s, p in rows if spec_file(p))
    records = sorted(p for s, p in rows if s != "D" and any(rx.match(p) for rx in RECORDS))
    if spec and not records:
        violations.append(f"the specification changes ({', '.join(spec[:5])}{' …' if len(spec) > 5 else ''}) without a "
                          f"proposal ({layout.CORE_PROPOSALS}/ or {layout.DOMAIN}/{layout.DOMAIN_PROPOSALS}/) or a "
                          f"decision record ({layout.DECISIONS}/)")

    text = _show(repo, mb, layout.CODEOWNERS)
    source = f"{layout.CODEOWNERS} at the merge base"
    if text is None and (repo / layout.CODEOWNERS).is_file():
        text, source = (repo / layout.CODEOWNERS).read_text(encoding="utf-8"), f"{layout.CODEOWNERS} (working tree)"
    paths = [p for _, p in rows]
    owners = ({"source": source, **codeowners.review_requirements(codeowners.parse(text), paths)} if text is not None
              else {"source": None, "note": f"no {layout.CODEOWNERS}: review routing unknown"})
    core_touched = sorted(p for p in paths if p.startswith(f"{layout.CORE}/"))
    consult = None
    if core_touched:
        teams = []
        m = load_yaml_text(_show(repo, head, layout.DOMAIN_DECLARATION) or "") or {}
        team = (m.get("maintainers") or {}).get("team")
        if team:
            teams.append(team)
        consult = {"paths": core_touched, "domain_teams": teams,
                   "note": "core/ changed: the catalysis domain builds on the science kernel; say in the pull request how "
                           "the catalysis domain is affected (the reviewers review both)"}
    return {"base": base, "merge_base": mb, "head": head, "changed": [{"status": s, "path": p} for s, p in rows],
            "specification_files": spec, "change_records": records, "violations": violations,
            "owners": owners, "core_consultation": consult, "ok": not violations}


def spec_changes_text(res: dict) -> str:
    L = [f"{len(res['changed'])} changed files against {res['base']} (merge base {res['merge_base'][:12]})"]
    if res["specification_files"]:
        L.append(f"specification files changed: {len(res['specification_files'])}; proposals / decision records: "
                 f"{len(res['change_records'])}")
    L += [f"FAIL {v}" for v in res["violations"]] or ["ok: no release or frozen version is modified; specification changes carry their records"]
    L.append("approval: one approving review from a reviewer other than the author (governance/review-policy.yaml)")
    o = res["owners"]
    if o.get("source"):
        L.append(f"review requested from (from {o['source']}; any one reviewer's approval is enough, a code owner's is not required):")
        L += [f"  - any of {' '.join(s)}" for s in o["owner_sets"]] or ["  - none"]
        if o["minimal_reviewers"]:
            L.append(f"  fewest reviewers who own every changed path: {' + '.join(o['minimal_reviewers'])}")
        if o["unowned"]:
            L.append(f"  no owner: {', '.join(o['unowned'][:10])}")
    else:
        L.append(o["note"])
    if res["core_consultation"]:
        c = res["core_consultation"]
        L.append(f"{c['note']}; teams to consult: {', '.join(c['domain_teams']) or 'none declared'}")
    return "\n".join(L)


def changed_proposals(repo: Path, base: str, head: str = "HEAD", status: str | None = None) -> list[dict]:
    """The proposals with a file changed between ``base`` and ``head`` (a direct diff: on main after a push,
    the push's before and after commits), with their status at ``head`` (the working tree when ``head`` is
    HEAD); with ``status``, only those. The apply-proposals workflow applies the ones still ``proposed``."""
    if set(base) == {"0"}:
        raise ScaleError(f"base {base} is no commit (a new branch); name the commit to compare with")
    fields = _git(repo, "diff", "--name-status", "--no-renames", "-z", base, head).split("\0")
    rows = [(fields[i][0], fields[i + 1]) for i in range(0, len(fields) - 1, 2)]
    ids = sorted({m.group(1) for _, p in rows if (m := PROPOSAL_PATH.match(p))})
    out = []
    for pid in ids:
        d = layout.proposal_dir(repo, pid)
        if d is None or not (d / "proposal.yaml").is_file():
            continue                                        # removed by the push
        st = (load_yaml_text((d / "proposal.yaml").read_text()) or {}).get("status")
        if status is None or st == status:
            out.append({"proposal": pid, "path": d.relative_to(repo).as_posix(), "status": st})
    return out


def _stale(cs: Path, repo: Path, v: dict) -> str | None:
    """Why a proposal's committed reports no longer describe it, from what needs no restricted data: the
    proposal is built again (in a scratch copy, so the committed ``candidate/`` is left as it is) and its tier,
    schema diff and candidate files must equal the committed ones; None when they do. A proposal.yaml that no
    longer builds is an error (ScaleError)."""
    import json
    import shutil
    import tempfile
    from . import pgraph
    from .pgraph_proposal import _resolved, build, candidate_differences, diff_specs, load_proposal, tier
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp) / cs.name
        shutil.copytree(cs, t, ignore=shutil.ignore_patterns("candidate", "approvals"))
        cand = build(t, repo)
        _, man, *_ = _resolved(repo, load_proposal(t))
        diff = json.loads(json.dumps(diff_specs(pgraph.load_spec(man), pgraph.load_spec(cand))))
        if tier(diff) != v.get("tier") or diff != v.get("diff"):
            return (f"its schema diff (tier {tier(diff)}) differs from the committed validation_report.json's "
                    f"(tier {v.get('tier')})")
        if not (cs / "candidate").is_dir() or candidate_differences(t / "candidate", cs / "candidate"):
            return "the candidate it builds differs from the committed candidate/"
    return None


def _without_data(c: dict, cs: Path, repo: Path, absent: list[str]) -> dict:
    """The row of a proposal some of whose declared inputs are not in the repository, while no restricted copy
    is set either (CI). It is "needs restricted data" only when its committed
    validation_report.json, written by a check with the data, records every one of them as a restricted input
    and passed, and is current: the proposal still builds, to the committed candidate, tier and schema diff
    (``_stale``). Otherwise it fails: a wrong path, reports never produced (or failing) with the data, or
    reports older than the proposal."""
    val = cs / "validation_report.json"
    try:
        v = load_doc(val) if val.is_file() else None
    except (OSError, ValueError) as exc:
        return {**c, "result": "failed", "why": f"{val.name} cannot be read: {exc}"}
    named = ", ".join(absent)
    if not isinstance(v, dict) or v.get("proposal") != c["proposal"]:
        return {**c, "result": "failed", "why": f"not in the repository: {named}; and there is no committed "
                f"validation_report.json for proposal {c['proposal']}: run `scale proposal check` with the restricted "
                f"copy ({layout.RESTRICTED_ENV}) and commit its public reports, or correct the path"}
    recorded = set(((v.get("restricted") or {}).get("inputs")) or [])
    unknown = [a for a in absent if a not in recorded]
    if unknown:
        return {**c, "result": "failed", "why": f"not in the repository: {', '.join(unknown)}; and the committed "
                "validation_report.json does not record it as restricted data: a wrong path?"}
    if v.get("ok") is not True:
        return {**c, "result": "failed", "committed": v, "why": f"{named} is restricted data and the committed "
                "validation_report.json (from a check with it) did not pass"}
    try:
        stale = _stale(cs, repo, v)
    except ScaleError as exc:
        stale = f"it no longer builds ({exc})"
    if stale:
        return {**c, "result": "failed", "why": f"{named} is restricted data and the committed reports are "
                f"out of date: {stale}; run `scale proposal check` with the data ({layout.RESTRICTED_ENV}) and "
                "commit its public reports"}
    return {**c, "result": "needs restricted data", "committed": v,
            "why": f"{named} is restricted data, not here; its committed reports passed"}


def proposal_checks(repo: Path, base: str, head: str = "HEAD") -> dict:
    """Run ``scale proposal check`` on every proposal a pull request changes (against the merge base of
    ``base``) whose status is draft or proposed; any error fails. A proposal whose inputs are restricted data
    cannot be checked without them (CI has none): only when the data is not here, every input missing from
    the repository is one its committed validation_report.json records as restricted, that report passed, and
    the proposal still builds to the committed candidate, tier and diff, is it reported as "needs restricted data", with the summary the report gives, and does not fail. A
    proposal that holds files in ``approvals/`` fails: approvals come only from GitHub reviews, recorded after
    the merge."""
    from .pgraph_proposal import check, declared_inputs, load_proposal
    repo = Path(repo).resolve()
    mb = _git(repo, "merge-base", base, head).strip()
    data = layout.restricted_root(repo)
    rows = []
    for c in changed_proposals(repo, mb, head):
        if c["status"] not in ("draft", "proposed"):
            rows.append({**c, "result": "skipped", "why": f"status {c['status']}: history, not checked again"})
            continue
        cs = repo / c["path"]
        held = sorted(p.name for p in (cs / "approvals").iterdir()) if (cs / "approvals").is_dir() else []
        if held:
            rows.append({**c, "result": "failed", "why": f"approvals/ holds {', '.join(held)}: approvals come only from "
                         "this pull request's GitHub reviews, which the apply-proposals workflow records after the "
                         "merge; remove these files"})
            continue
        try:
            absent = [] if data is not None else [r for r in declared_inputs(load_proposal(cs)) if not (repo / r).exists()]
            if absent:
                rows.append(_without_data(c, cs, repo, absent))
                continue
            res = check(cs, repo)
            rows.append({**c, "result": "ok" if res["ok"] else "failed", "check": res})
        except ScaleError as exc:
            rows.append({**c, "result": "failed", "why": str(exc)})
    return {"repo": str(repo), "merge_base": mb, "proposals": rows, "ok": not any(r["result"] == "failed" for r in rows)}


COMMENT_MARK = "<!-- scale-ci:proposal-check -->"


def proposal_comment(res: dict) -> str:
    """The one (sticky) pull-request comment with each proposal's check: tier, diff counts, fixtures, migration
    effects and competency results, from the reports the check wrote."""
    L = [COMMENT_MARK, "### Proposal check", ""]
    if not res["proposals"]:
        L.append("This pull request changes no proposal.")
    for r in res["proposals"]:
        L.append(f"**{r['proposal']}** (`{r['path']}`, status {r['status']}): **{r['result']}**")
        chk = r.get("check")
        if chk:
            diff = ", ".join(f"{v} {k}" for k, v in chk["diff"].items() if v) or "no change"
            L.append(f"- tier {chk['tier']}; schema diff: {diff}")
            L.append(f"- fixtures {chk['fixtures']}/{chk['fixtures_total']} as expected")
            mig = Path(res["repo"]) / r["path"] / "migration_assessment.json"
            m = load_doc(mig) if mig.is_file() else {}
            if m:
                L.append(f"- migration: {m.get('summary')} ({len(m.get('documents') or [])} documents assessed); competency "
                         f"questions changed: {sum(1 for q in m.get('competency') or [] if q.get('changed'))} of "
                         f"{len(m.get('competency') or [])}")
            L += [f"- problem: {x}" for x in chk["problems"]] + [f"- blocking: {x}" for x in chk["blocking"]]
            L += [f"- warning: {x}" for x in chk.get("warnings") or []]
        elif r["result"] == "needs restricted data":
            v = r["committed"]
            L.append(f"- not checked here: its inputs are restricted data (a restricted copy, {layout.RESTRICTED_ENV}). Its committed reports "
                     f"(checked {v.get('checked_at')} with the data): tier {v.get('tier')}, ok {v.get('ok')}.")
        elif r.get("why"):
            L.append(f"- {r['why']}")
        L.append("")
    L.append("Approval: one approving review from a reviewer other than the author (governance/review-policy.yaml). "
             "After the merge, a person starts the apply-proposals workflow for each proposal, with this pull request's "
             "number (it needs the repository secret APPLY_TOKEN); a proposal in the owner's own pull request, merged "
             "before a second reviewer joins, the owner applies in a pull request under the bootstrap rule (`scale proposal decide --bootstrap-bypass`, then "
             "`scale proposal apply --confirm`). Applying a proposal raises the schema version.")
    return "\n".join(L) + "\n"
