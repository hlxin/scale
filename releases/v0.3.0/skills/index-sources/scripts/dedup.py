"""Find and merge duplicate sources across the whole ledger — every topic, every run.

  python3 -I dedup.py                          # report only (nothing changes)
  python3 -I dedup.py --apply                  # merge the safe cases; list the uncertain pairs (to_review)
  python3 -I dedup.py --merge 12:57,30:31      # merge pairs the user confirmed are the same source
  python3 -I dedup.py --keep-separate 12:57    # the user says they are different sources ("all" = every listed pair)
  --no-export with --apply / --merge: leave the index CSVs and index.db for one export.py after the last step

The skill runs --apply after every index, update and download without asking: only the uncertain pairs reach the user,
and a pair kept separate is never listed (or merged) again (.scripts/dedup_decisions.jsonl).

Safe cases (merged by --apply):
  preprint_vs_published  a preprint row and a published-version row with the same title (+-3 years)
  journal_edition_twin   the same source under two DOIs of one journal (Angewandte ange./anie. editions)
  repository_copy        a repository's own DOI (Zenodo, Figshare, institutional archive) for a journal article
  no_doi_vs_doi          a DOI-less row whose title (+-1 year) matches a row that has a DOI
  same_file              two rows whose downloaded PDFs are byte-identical
  near_title_preprint_or_copy  a preprint/repository/DOI-less copy whose title differs by a word or two from a
                         journal article by the same first author (+-2 years, similarity >= 0.9)
  crossref_preprint_link a preprint and the article Crossref says it became (relation is-preprint-of /
                         has-preprint), whatever the titles — the publisher's own link
  patent_family          the same invention filed in several offices (WO, EP, US, CN ...) or copied to HAL / OSTI:
                         same title, overlapping inventors, years within 6. One row keeps every number as an alias
                         (identifiers scheme 'patent'; index Notes "Same invention also published as ...").
                         Two numbers of one office in the same series (same length: two grants, two applications)
                         are two patents — a series filed together, a continuation, a divisional — never one row.
  si_deposit             a publisher's SI deposit (Figshare ...) indexed as a source although it declares IsSupplementTo
                         another source: it becomes an SI link of that source (si_links), not a row
Also, every --apply turns SI deposits that an older version merged INTO their own source (Figshare DOIs kept as
aliases, supplement_to pointing at itself) back into SI links.
Uncertain (a person decides; listed in to_review and .scripts/dedup_review.csv): same_title_different_doi
(republications, errata, conference+journal versions), near_title_same_author (two journal items with nearly the same
title by the same first author), patent_same_title (two patents with the same specific title, inventors unknown).
A merge keeps one row (published version > has DOI > downloaded > lowest ID): topics, databases, DOIs and missing
fields move onto it; the other row's files move to .scripts/duplicates/ (never deleted). Every merge is logged in
.scripts/logs/dedup_log.jsonl with the full merged row and its topic rows, so a wrong merge can be rebuilt by hand.
Errata/corrections and retracted sources are counted (they are already flagged in Notes).
"""
import argparse
import csv
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (Project, add_project_arg, die, jsonl_append, jsonl_iter, log, norm_doi, norm_title, now_iso,
                     title_hash)
from _download import clone_or_copy
from _cache import Cache
from _ledger import Ledger
from _vectors import after_step
from build_list import edition_twin, is_preprint_doi, is_repository_doi

UNCERTAIN = ("same_title_different_doi", "near_title_same_author", "patent_same_title")
SI_HOSTS = ("10.6084/", "10.25384/")    # Figshare: where ACS, RSC, T&F, SAGE ... deposit a source's SI
# the columns dedup needs (a ledger of millions of sources must not be loaded with abstracts and copies)
SLIM = ("id, key, doi, title, authors, year, journal, doc_type, is_preprint, is_erratum, retracted, downloaded, sha1, "
        "external_ids")


def name_tokens(names):
    return {t for n in names or [] for t in re.findall(r"[a-z]{2,}", (n or "").lower())}


def same_invention(x, y):
    """Patents x and y name the same inventors ("TAILLEFER MARC; XIA NING" = "Marc Taillefer; Ning Xia")."""
    ax, ay = x.get("authors") or [], y.get("authors") or []
    if not ax or not ay or distinct_patents(x, y):
        return False
    if x.get("year") and y.get("year") and abs(int(x["year"]) - int(y["year"])) > 6:
        return False
    tx, ty = name_tokens(ax), name_tokens(ay)
    return name_tokens(ax[:1]) == name_tokens(ay[:1]) or len(tx & ty) / max(1, len(tx | ty)) >= 0.5


def office_number(p):
    m = re.match(r"^patent:([A-Z]{2})(\d+)$", p.get("key") or "")
    return (m.group(1), m.group(2)) if m else None


def distinct_patents(x, y):
    """Two numbers of one office in the same series (same length) are two different patents, whatever their titles
    and inventors (US1625924 and US1625925, granted the same day); an application and its grant (US2011144382 and
    US8123456, JP2005123456 and JP4567890) differ in length and can still be one invention."""
    a, b = office_number(x), office_number(y)
    return bool(a and b and a[0] == b[0] and a[1] != b[1] and len(a[1]) == len(b[1]))


def patent_order(p):
    """Family representative: a numbered patent (WO, then EP, then US, then others) before HAL / OSTI copies."""
    k = p.get("key") or ""
    num = k[len("patent:"):] if k.startswith("patent:") else ""
    return (0 if num else 1, {"WO": 0, "EP": 1, "US": 2}.get(num[:2], 3), p["id"])


def first_surname(authors):
    a = (authors or [""])[0] or ""
    return (a.split(",")[0] if "," in a else (a.split() or [""])[-1]).lower()


def doc_class(p):
    dt = p.get("doc_type") or ""
    return "data" if dt in ("dataset", "software") else ("patent" if dt == "patent" else "doc")


def keep_order(p):
    return (1 if (p.get("is_preprint") or is_preprint_doi(p.get("doi"))) else 0, 0 if p.get("doi") else 1,
            1 if is_repository_doi(p.get("doi"), p.get("journal")) else 0,
            1 if (p.get("doi") or "").startswith("10.1002/ange.") else 0, 0 if p.get("downloaded") else 1, p["id"])


def decisions_file(proj):
    return proj.scr / "dedup_decisions.jsonl"


def kept_separate(proj):
    """Pairs the user said are different sources: never listed or merged again."""
    out = set()
    for r in jsonl_iter(decisions_file(proj)) or []:
        if r.get("decision") == "separate":
            out.add((min(int(r["a"]), int(r["b"])), max(int(r["a"]), int(r["b"]))))
    return out


def is_si_row(p):
    """A publisher's SI deposit (Figshare) that declares IsSupplementTo a source — not a source itself."""
    return bool((p.get("doi") or "").startswith(SI_HOSTS) and (p.get("external_ids") or {}).get("supplement_to")
                and doc_class(p) != "data")


def find(led, separate=frozenset()):
    everything = [led.row(r) for r in led.q(f"SELECT {SLIM} FROM sources")]
    papers = [p for p in everything if not is_si_row(p)]     # SI rows are handled below, never as copies
    by_th = defaultdict(list)
    for p in papers:
        if len(norm_title(p.get("title")).split()) >= 5:
            by_th[title_hash(p.get("title"))].append(p)
    groups = []
    for ps in by_th.values():
        if len(ps) < 2:
            continue
        ps = sorted(ps, key=keep_order)
        ps = [p for p in ps if not p.get("is_erratum")]
        if len(ps) < 2:
            continue
        keep = ps[0]
        for o in ps[1:]:
            yk, yo = keep.get("year"), o.get("year")
            dy = abs(int(yk) - int(yo)) if yk and yo else 0
            pre = bool(o.get("is_preprint") or is_preprint_doi(o.get("doi")) or keep.get("is_preprint"))
            if not o.get("doi") and dy <= 1:
                groups.append(("no_doi_vs_doi", keep, o))
            elif o.get("doi") and edition_twin(o["doi"]) == keep.get("doi"):
                groups.append(("journal_edition_twin", keep, o))
            elif is_repository_doi(o.get("doi"), o.get("journal")) and not is_repository_doi(keep.get("doi"), keep.get("journal")) \
                    and dy <= 3 and not (o.get("is_erratum") or keep.get("is_erratum")):
                groups.append(("repository_copy", keep, o))
            elif pre and dy <= 3:
                groups.append(("preprint_vs_published", keep, o))
            elif o.get("doi") and keep.get("doi") and dy <= 1 and first_surname(keep.get("authors")) == first_surname(o.get("authors")):
                groups.append(("same_title_different_doi", keep, o))
    # near-identical titles (a word added/removed between preprint and journal version): same first author,
    # years within 2, title similarity >= 0.9. Safe when one side is a preprint/repository copy of a journal article.
    grouped = {(k["id"], o["id"]) for _, k, o in groups} | {(o["id"], k["id"]) for _, k, o in groups}
    by_author = defaultdict(list)
    for p in papers:
        if p.get("is_erratum") or len(norm_title(p.get("title")).split()) < 5:
            continue
        by_author[first_surname(p.get("authors"))].append(p)
    for au, ps in by_author.items():
        if not au or len(ps) < 2:
            continue
        toks = {p["id"]: set(w for w in norm_title(p.get("title")).split() if len(w) > 2) for p in ps}
        byid = {p["id"]: p for p in ps}
        df = defaultdict(int)
        for t in toks.values():
            for w in t:
                df[w] += 1
        inv = defaultdict(list)  # distinctive words only: a candidate pair must share most of them
        for pid, t in toks.items():
            for w in t:
                if df[w] <= 25:
                    inv[w].append(pid)
        for pid, t in toks.items():
            shared = defaultdict(int)
            for w in t:
                if df[w] <= 25:
                    for q in inv[w]:
                        if q > pid:
                            shared[q] += 1
            rare = sum(1 for w in t if df[w] <= 25)
            for q, n in shared.items():
                if n < max(2, 0.6 * rare):
                    continue
                a_, b_ = byid[pid], byid[q]
                if (a_["id"], b_["id"]) in grouped or title_hash(a_.get("title")) == title_hash(b_.get("title")):
                    continue
                ya, yb = a_.get("year"), b_.get("year")
                if ya and yb and abs(int(ya) - int(yb)) > 2:
                    continue
                ta, tb = toks[pid], toks[q]
                if len(ta & tb) / len(ta | tb) < 0.75:
                    continue
                if SequenceMatcher(None, norm_title(a_.get("title")), norm_title(b_.get("title"))).ratio() < 0.9:
                    continue
                keep, o = sorted([a_, b_], key=keep_order)
                copy = (o.get("is_preprint") or is_preprint_doi(o.get("doi")) or is_repository_doi(o.get("doi"), o.get("journal"))
                        or not o.get("doi"))
                journal_keep = keep.get("doi") and not (keep.get("is_preprint") or is_preprint_doi(keep.get("doi"))
                                                        or is_repository_doi(keep.get("doi"), keep.get("journal")))
                groups.append(("near_title_preprint_or_copy" if (copy and journal_keep) else "near_title_same_author", keep, o))
                grouped.add((keep["id"], o["id"]))
    # the publisher's own preprint <-> article links (Crossref relation), cached by classify_access.py
    byid = {p["id"]: p for p in papers}
    for r in Cache(led.proj, "crossref").iter_all(like="%-preprint%"):
        rel = r.get("relation") or {}
        src = led.find_id(doi=norm_doi(r.get("doi")))
        if not src or src not in byid:
            continue
        for kind_rel in ("is-preprint-of", "has-preprint"):
            for x in rel.get(kind_rel) or []:
                other = led.find_id(doi=norm_doi(x.get("id"))) if x.get("id-type") == "doi" else None
                if other and other != src and other in byid:
                    a_, b_ = byid[src], byid[other]
                    pre, pub = (a_, b_) if kind_rel == "is-preprint-of" else (b_, a_)
                    if (pub["id"], pre["id"]) not in grouped:
                        groups.append(("crossref_preprint_link", pub, pre))
                        grouped.add((pub["id"], pre["id"]))
    # patent families
    by_pt = defaultdict(list)
    for p in papers:
        if p.get("doc_type") == "patent" and not p.get("is_erratum") and len(norm_title(p.get("title")).split()) >= 3:
            by_pt[title_hash(p.get("title"))].append(p)
    for ps in by_pt.values():
        if len(ps) < 2:
            continue
        root = {p["id"]: p["id"] for p in ps}
        members = {p["id"]: [p] for p in ps}

        def rt(x):
            while root[x] != x:
                root[x] = root[root[x]]
                x = root[x]
            return x
        for i, x in enumerate(ps):
            for y in ps[i + 1:]:
                rx, ry = rt(x["id"]), rt(y["id"])
                if rx != ry and same_invention(x, y) and not any(
                        distinct_patents(u, v) for u in members[rx] for v in members[ry]):
                    root[ry] = rx            # never joins two patents of one series through a third
                    members[rx] += members.pop(ry)
        comps = defaultdict(list)
        for p in ps:
            comps[rt(p["id"])].append(p)
        reps = []
        for c in comps.values():
            c.sort(key=patent_order)
            reps.append(c[0])
            groups += [("patent_family", c[0], o) for o in c[1:]]
        if len(norm_title(ps[0].get("title")).split()) >= 5:      # a specific title, inventors unknown on one side
            for i, x in enumerate(reps):
                for y in reps[i + 1:]:
                    close = not (x.get("year") and y.get("year")) or abs(int(x["year"]) - int(y["year"])) <= 4
                    if close and (not x.get("authors") or not y.get("authors")) and not distinct_patents(x, y):
                        groups.append(("patent_same_title", *sorted([x, y], key=patent_order)))
    # a publisher's SI deposit indexed as a source: it declares IsSupplementTo another indexed source
    for p in everything:
        if not is_si_row(p):
            continue
        sup = norm_doi((p.get("external_ids") or {}).get("supplement_to"))
        tgt = led.find_id(doi=sup)
        if tgt and tgt != p["id"] and tgt in byid:
            groups.append(("si_deposit", byid[tgt], p))
    papers = everything
    by_sha = defaultdict(list)
    for p in papers:
        if p.get("sha1"):
            by_sha[p["sha1"]].append(p)
    for ps in by_sha.values():
        if len(ps) > 1:
            ps = sorted(ps, key=keep_order)
            groups += [("same_file", ps[0], o) for o in ps[1:]]
    seen, out = set(), []
    for kind, k, o in groups:
        if (k["id"], o["id"]) in seen or k["id"] == o["id"]:
            continue
        if (min(k["id"], o["id"]), max(k["id"], o["id"])) in separate:
            continue   # the user said these are different sources
        if kind not in ("same_file", "patent_family", "patent_same_title", "si_deposit") and \
                (doc_class(k) != doc_class(o) or doc_class(k) == "patent"):
            continue   # a dataset is not its source; patents only merge as a family (title + inventors), never by title
        seen.add((k["id"], o["id"]))
        out.append((kind, k, o))
    stats = {"sources": len(papers), "errata_or_corrections": sum(1 for p in papers if p.get("is_erratum")),
             "retracted": sum(1 for p in papers if p.get("retracted"))}
    return out, stats


def merge(proj, led, keep, other, kind):
    """Fold `other` into `keep`. If only `other` was downloaded, its files are renamed to keep's ID (they stay in
    sources/); otherwise other's files move to .scripts/duplicates/."""
    dup_dir = proj.scr / "duplicates"
    dup_dir.mkdir(parents=True, exist_ok=True)
    snapshot = json.loads(json.dumps({"row": other, "topics": led.topics_of(other["id"])}, default=str))
    transfer = bool(other.get("downloaded")) and not keep.get("downloaded") and kind != "same_file"
    oid, kid = str(other["id"]), str(keep["id"])
    moved = []
    kt = {t["topic"]: t for t in led.topics_of(keep["id"])}
    for t in led.topics_of(other["id"]):
        new_pdf, new_si = None, []
        for f in [t.get("path")] + json.loads(t.get("si_paths") or "[]"):
            if not f or not (proj.root / f).exists():
                continue
            src = proj.root / f
            if transfer and src.name.startswith(oid):
                dst = src.with_name(kid + src.name[len(oid):])
                shutil.move(str(src), str(dst))
                if f == t.get("path"):
                    new_pdf = proj.rel(dst)
                else:
                    new_si.append(proj.rel(dst))
            else:
                dst = dup_dir / f"{oid}__{src.name}"
                shutil.move(str(src), str(dst))
                moved.append(proj.rel(dst))
        fields = {}
        k = kt.get(t["topic"])
        if not k or (k.get("relevance") is None and t.get("relevance") is not None):
            fields.update(relevance=t.get("relevance"), relevance_note=t.get("relevance_note"),
                          relevance_method=t.get("relevance_method"), in_scope=t.get("in_scope"))
        if new_pdf:
            fields.update(path=new_pdf, si_paths=new_si)
        led.set_topic(keep["id"], t["topic"], **fields)
        src_rel = next((x.get("path") for x in kt.values() if x.get("path")), None)
        if not k and not new_pdf and keep.get("downloaded") and src_rel and (proj.root / src_rel).exists():
            dst = proj.pdf_dir(t["topic"], keep.get("access_type") or "Free-to-read") / Path(src_rel).name
            clone_or_copy(proj.root / src_rel, dst)
            led.set_topic(keep["id"], t["topic"], path=proj.rel(dst))
    upd = {"databases": sorted(set(keep.get("databases") or []) | set(other.get("databases") or []))}
    for f in ("abstract", "journal", "publisher", "year", "cited_by", "link", "doc_type", "last_checked"):
        if not keep.get(f) and other.get(f):
            upd[f] = other[f]
            if f == "abstract":
                upd["abstract_source"] = other.get("abstract_source")
    if not keep.get("authors_detail") and other.get("authors_detail"):
        upd["authors_detail"] = other["authors_detail"]
    kw = list(keep.get("keywords") or [])
    for k in other.get("keywords") or []:
        if k.lower() not in {x.lower() for x in kw}:
            kw.append(k)
    if kw != (keep.get("keywords") or []):
        upd["keywords"] = kw[:25]
    ext = dict(other.get("external_ids") or {})
    ext.update({k: v for k, v in (keep.get("external_ids") or {}).items() if v})
    upd["external_ids"] = ext
    from _common import access_rank
    if not transfer and not keep.get("downloaded") and other.get("access_type") and \
            access_rank(other["access_type"]) < access_rank(keep.get("access_type")):
        # the merged copy (often a preprint or repository version) is more open: the source is readable through it
        for f in ("access_type", "license", "license_label", "license_url", "license_source", "oa_status"):
            upd[f] = other.get(f)
        seen_v = {(v.get("pdf_url") or v.get("url")) for v in keep.get("versions") or []}
        upd["versions"] = (keep.get("versions") or []) + [v for v in other.get("versions") or []
                                                          if (v.get("pdf_url") or v.get("url")) not in seen_v]
        upd["dl_status"], upd["dl_note"] = None, None
    if transfer:
        for f in ("downloaded", "access_type", "license", "license_evidence", "access_basis", "version",
                  "download_source", "download_url", "download_date", "page_count", "sha1", "si_status", "si_files",
                  "license_label", "license_url", "license_source"):
            upd[f] = other.get(f)
        upd["si_files"] = [kid + n[len(oid):] if n.startswith(oid) else n for n in (other.get("si_files") or [])]
        upd["dl_status"], upd["dl_note"] = None, None
    led.x("UPDATE sources SET sha1=NULL WHERE id=?", (other["id"],))
    led.set(keep["id"], **upd)
    for d in led.aliases(other["id"]):
        led.x("UPDATE dois SET source_id=? WHERE doi=?", (keep["id"], d))
    if re.match(r"^(patent:[A-Z0-9]{3,}|nodoi:\S+|[a-z_]+:\S+)$", str(other.get("key") or "")) and \
            not str(other["key"]).startswith("10."):
        led.add_dois(keep["id"], [other["key"]])   # 'patent:EP2043970' / 'nodoi:...': later search hits land on keep
    # topics (Topic A/B/C) and curation results follow the kept source
    if not led.q("SELECT 1 FROM source_subjects WHERE source_id=?", (keep["id"],)):
        led.x("UPDATE source_subjects SET source_id=? WHERE source_id=?", (keep["id"], other["id"]))
    led.x("DELETE FROM source_subjects WHERE source_id=?", (other["id"],))
    led.x("UPDATE OR IGNORE extractions SET source_id=? WHERE source_id=?", (keep["id"], other["id"]))
    led.x("DELETE FROM extractions WHERE source_id=?", (other["id"],))
    led.x("DELETE FROM source_topics WHERE source_id=?", (other["id"],))
    led.x("DELETE FROM sources WHERE id=?", (other["id"],))
    jsonl_append(proj.logs / "dedup_log.jsonl", {"kind": kind, "kept": keep["id"], "merged": other["id"],
                                                 "kept_doi": keep.get("doi"), "merged_doi": other.get("doi"),
                                                 "files_transferred": transfer, "files_moved": moved, "ts": now_iso(),
                                                 "merged_row": snapshot["row"], "merged_topics": snapshot["topics"]})
    return moved


def fold_si(proj, led, parent, other):
    """An SI deposit indexed as a source becomes an SI link of the source it belongs to; the row goes (logged in full)."""
    snapshot = json.loads(json.dumps({"row": other, "topics": led.topics_of(other["id"])}, default=str))
    sup = norm_doi((other.get("external_ids") or {}).get("supplement_to")) or parent.get("doi")
    dois = [d for d in (led.aliases(other["id"]) or [other.get("doi")]) if d and not d.startswith(("patent:", "nodoi:"))]
    led.add_si_links([{"parent_doi": sup, "si_doi": d, "url": f"https://doi.org/{d}", "title": other.get("title"),
                       "source": "; ".join(other.get("databases") or [])} for d in dois])
    moved, dup_dir = [], proj.scr / "duplicates"
    for t in led.topics_of(other["id"]):
        for f in [t.get("path")] + json.loads(t.get("si_paths") or "[]"):
            if f and (proj.root / f).exists():
                dup_dir.mkdir(parents=True, exist_ok=True)
                dst = dup_dir / f"{other['id']}__{Path(f).name}"
                shutil.move(str(proj.root / f), str(dst))
                moved.append(proj.rel(dst))
    for tbl in ("dois", "source_topics", "source_subjects", "extractions"):
        led.x(f"DELETE FROM {tbl} WHERE source_id=?", (other["id"],))
    led.x("DELETE FROM sources WHERE id=?", (other["id"],))
    jsonl_append(proj.logs / "dedup_log.jsonl", {"kind": "si_deposit", "kept": parent["id"], "merged": other["id"],
                                                 "kept_doi": parent.get("doi"), "merged_doi": other.get("doi"),
                                                 "si_links": dois, "files_moved": moved, "ts": now_iso(),
                                                 "merged_row": snapshot["row"], "merged_topics": snapshot["topics"]})


def unmerge_self_si(proj, led):
    """Older versions merged a source's own SI deposit INTO the source (Figshare DOIs as aliases, supplement_to pointing
    at the source itself): turn those aliases back into SI links of the source."""
    n = 0
    rows = [led.row(r) for r in led.q("SELECT id, doi, external_ids FROM sources WHERE external_ids LIKE '%supplement_to%'")]
    with led.tx():
        for p in rows:
            ext = dict(p.get("external_ids") or {})
            sup = norm_doi(ext.get("supplement_to"))
            if not sup or led.find_id(doi=sup) != p["id"]:
                continue
            si = [d for d in led.aliases(p["id"]) if d.startswith(SI_HOSTS) and d != p.get("doi")]
            led.add_si_links([{"parent_doi": sup, "si_doi": d, "url": f"https://doi.org/{d}", "title": None,
                               "source": "figshare"} for d in si])
            for d in si:
                led.x("DELETE FROM dois WHERE doi=? AND source_id=?", (d, p["id"]))
            ext.pop("supplement_to", None)
            led.set(p["id"], external_ids=ext)
            jsonl_append(proj.logs / "dedup_log.jsonl", {"kind": "si_unmerged", "kept": p["id"], "si_links": si,
                                                         "ts": now_iso()})
            n += 1
    return n


def topics_csv(led, pid):
    return ", ".join(t["topic"] for t in led.topics_of(pid))


def review_rows(led, groups):
    """The uncertain pairs, side by side, for the user."""
    out = []
    for kind, k, o in groups:
        if kind not in UNCERTAIN:
            continue
        row = {"pair": f"{k['id']}:{o['id']}", "kind": kind}
        for side, p in (("a", k), ("b", o)):
            row.update({f"{side}_id": p["id"], f"{side}_title": p.get("title") or "", f"{side}_doi": p.get("doi") or "",
                        f"{side}_year": p.get("year") or "", f"{side}_venue": p.get("journal") or "",
                        f"{side}_doc_type": p.get("doc_type") or "", f"{side}_downloaded": p.get("downloaded") or "",
                        f"{side}_topics": topics_csv(led, p["id"])})
        out.append(row)
    return out


def write_review(proj, rows):
    path = proj.scr / "dedup_review.csv"
    cols = ["pair", "kind"] + [f"{s}_{f}" for s in ("a", "b") for f in ("id", "title", "doi", "year", "venue", "doc_type",
                                                                        "downloaded", "topics")]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return proj.rel(path)


def parse_pairs(s):
    pairs = []
    for x in (s or "").replace(" ", "").split(","):
        if not x:
            continue
        p = x.replace("+", ":").split(":")
        if len(p) != 2 or not all(v.isdigit() for v in p) or p[0] == p[1]:
            die(f"pairs look like 12:57 (two different source IDs), got {x!r}")
        pairs.append((int(p[0]), int(p[1])))
    return pairs


def apply_safe(proj, led, separate):
    """Merge every safe pair; repeat while merges uncover new safe pairs (A~B~C chains)."""
    by_kind = Counter()
    for _ in range(3):
        groups, _stats = find(led, separate)
        gone, n = set(), 0
        for kind, k, o in groups:
            if kind in UNCERTAIN or k["id"] in gone or o["id"] in gone:
                continue
            with led.tx():
                if kind == "si_deposit":
                    fold_si(proj, led, led.get(k["id"]), led.get(o["id"]))
                else:
                    merge(proj, led, led.get(k["id"]), led.get(o["id"]), kind)
            gone.add(o["id"])
            by_kind[kind] += 1
            n += 1
        if not n:
            break
    return by_kind


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="merge the safe cases; list the uncertain pairs")
    g.add_argument("--merge", metavar="A:B,...", help="merge pairs the user confirmed")
    g.add_argument("--keep-separate", metavar="A:B,...|all", help="record pairs the user says are different sources")
    ap.add_argument("--show", type=int, default=10, help="examples / uncertain pairs to print")
    ap.add_argument("--no-export", action="store_true", help="do not refresh the index CSVs and index.db")
    a = ap.parse_args()
    proj = Project(a.project)
    led = Ledger(proj)
    separate = kept_separate(proj)
    if a.keep_separate:
        if a.keep_separate.strip().lower() == "all":
            pairs = [(k["id"], o["id"]) for kind, k, o in find(led, separate)[0] if kind in UNCERTAIN]
        else:
            pairs = parse_pairs(a.keep_separate)
        jsonl_append(decisions_file(proj), [{"a": min(x, y), "b": max(x, y), "decision": "separate", "at": now_iso()}
                                            for x, y in pairs])
        print(json.dumps({"kept_separate": len(pairs), "pairs": [f"{x}:{y}" for x, y in pairs],
                          "decisions": proj.rel(decisions_file(proj))}))
        return
    if a.merge:
        merged, refused = [], []
        for x, y in parse_pairs(a.merge):
            p, q = led.get(x), led.get(y)
            if not p or not q:
                refused.append({"pair": f"{x}:{y}", "reason": "no such source ID (already merged?)"})
                continue
            if doc_class(p) != doc_class(q):
                refused.append({"pair": f"{x}:{y}", "reason": "a dataset, a paper and a patent are never merged with "
                                                              "each other"})
                continue
            keep, other = sorted([p, q], key=patent_order if doc_class(p) == "patent" else keep_order)
            with led.tx():
                merge(proj, led, keep, other, "user_confirmed")
            jsonl_append(decisions_file(proj), {"a": min(x, y), "b": max(x, y), "decision": "merged", "kept": keep["id"],
                                                "at": now_iso()})
            merged.append({"kept": keep["id"], "merged": other["id"]})
        vec = None
        if merged and not a.no_export:
            led.export()
            vec = after_step(proj, led)            # a merged source's passages move to the ID it kept
        print(json.dumps({"merged": merged, "refused": refused, "vector_store": vec}))
        return
    report = {}
    if a.apply:
        n_si = unmerge_self_si(proj, led)
        by_kind = apply_safe(proj, led, separate)
        if n_si:
            by_kind["si_unmerged"] = n_si
        if by_kind and not a.no_export:
            led.export()
            report["vector_store"] = after_step(proj, led)
        report["merged"] = sum(v for k, v in by_kind.items() if k != "si_unmerged")
        report["merged_by_kind"] = dict(by_kind)
        log(f"merged {report['merged']} duplicate rows")
    groups, stats = find(led, separate)
    by_kind = defaultdict(list)
    for kind, k, o in groups:
        by_kind[kind].append({"keep": k["id"], "keep_doi": k.get("doi"), "other": o["id"], "other_doi": o.get("doi"),
                              "title": (k.get("title") or "")[:100]})
    review = review_rows(led, groups)
    report = {**stats, **report, ("remaining" if a.apply else "duplicates"): {k: len(v) for k, v in by_kind.items()}}
    if not a.apply:
        report["examples"] = {k: v[:a.show] for k, v in by_kind.items()}
    report["to_review"] = len(review)
    if review:
        report["review_file"] = write_review(proj, review)
        report["uncertain_pairs"] = [{k: r[k] for k in ("pair", "kind", "a_title", "a_doi", "a_year", "a_venue",
                                                         "b_title", "b_doi", "b_year", "b_venue")} for r in review[:a.show]]
        report["next"] = ("ask the user about the uncertain pairs, then dedup.py --keep-separate all | "
                          "--merge A:B,... (never merge them without the user)")
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
