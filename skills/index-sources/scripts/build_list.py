"""Index step 3 — build the topic's paper list from the raw search hits and merge it into the ledger.

  1. topic gate (config['gate']) drops loose matches; SI deposits (DOI ...s001, Figshare files, "Supporting
     information" records, deposits that declare IsSupplementTo a paper) are not papers: they become SI links of the
     paper they belong to (si_links table; the index SI column says "Available (n deposits)")
  2. dedup: same DOI; same patent (jurisdiction + number); preprint <-> published version (shared title + preprint DOI
     prefix or Crossref relation); DOI-less records attached by title (+-1 year) or grouped by title+first author+year
  3. merge into .scripts/ledger.sqlite: existing papers (other topics / earlier runs) gain this topic; new papers get
     the next free ID and today's date in `Date added`; document type, keywords, authors with ORCID/affiliations kept
Writes .scripts/<topic>/candidates.jsonl (per-paper copy/license hints for classify_access.py) and refreshes the
topic's index CSVs and publications/papers.db. Safe to re-run.

usage: python3 -I build_list.py --topic <slug> [--run since-2026-09-01] [--batches N] [--no-export]
--run limits the input to one search run (update mode on a big topic: only the new raw hits are read; DOIs already in
the ledger are matched, title-level duplicates across runs are caught by dedup.py).
--batches N splits the raw files into N groups processed one after another in this process (several million raw hits
would not fit in memory at once); the index CSVs and papers.db are written once at the end. --no-export skips that
final refresh (run export.py later). --si-links-only re-reads the raw hits only to link SI deposits to their papers.
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (PREPRINT_PREFIXES, SOURCE_LABEL, Gate, Project, add_project_arg, is_erratum,  # noqa: F401
                     is_preprint_doi, jsonl_iter, json_write_atomic, load_config, log, norm_doc_type, norm_doi,
                     norm_title, now_iso, title_hash, update_state)
from _ledger import Ledger
from _topics import Vocab, apply_vocab

SRC_RANK = ["crossref", "openalex", "scopus", "wos", "europepmc", "pmc", "springer", "ieee", "lens", "openaire", "core",
            "osti", "ntrs", "hal", "doaj", "s2", "ads", "arxiv", "crossref_preprints", "citations", "jstage", "cinii",
            "datacite", "zenodo", "plos", "figshare", "osf", "dryad", "dataverse", "mcloud", "openaire_data", "eric",
            "lens_patents", "epo", "europepmc_patents", "manual"]
SI_TITLE_RX = re.compile(r"^\s*(supporting information|supplementary (information|material|data|file|figures?|tables?)s?|"
                         r"electronic supplementary|supplemental (information|material|data)|si for\b|additional file)", re.I)


# DOIs minted by repositories for copies of articles published elsewhere (Zenodo, Figshare, institutional archives)
REPOSITORY_PREFIXES = ("10.5281/", "10.6084/", "10.5445/", "10.17615/", "10.7892/", "10.3929/", "10.18154/", "10.34734/",
                       "10.17863/", "10.25560/", "10.26083/", "10.14279/", "10.15488/", "10.18419/", "10.24406/",
                       "10.5167/", "10.13140/", "10.48548/", "10.17169/", "10.11588/", "10.15495/", "10.18452/",
                       "10.17877/", "10.25673/", "10.26092/", "10.22028/", "10.48693/", "10.35097/")
REPOSITORY_NAME_RX = re.compile(r"(repositor|zenodo|figshare|kitopen|research collection|\bboris\b|publications? server|"
                                r"institutional|eprints|dspace|digital commons|open archive|archive ouverte|juser|"
                                r"scholarship@|research portal|pure portal|\bepub\b|opus\b|edoc\b|refubium|"
                                r"mediatum|tuprints|elib\b)", re.I)


def is_repository_doi(doi, journal=None):
    return bool(doi) and (doi.startswith(REPOSITORY_PREFIXES) or bool(REPOSITORY_NAME_RX.search(journal or "")))


def edition_twin(doi):
    """Angewandte Chemie publishes every paper twice: 10.1002/ange.X (German) and 10.1002/anie.X (International)."""
    if doi and doi.startswith("10.1002/ange."):
        return "10.1002/anie." + doi[len("10.1002/ange."):]
    if doi and doi.startswith("10.1002/anie."):
        return "10.1002/ange." + doi[len("10.1002/anie."):]
    return None


def doi_preference(d):
    return (1 if is_preprint_doi(d) else 0, 1 if is_repository_doi(d) else 0, 1 if d.startswith("10.1002/ange.") else 0)


def surname(name):
    name = (name or "").strip()
    if not name:
        return ""
    return name.split(",")[0].strip().lower() if "," in name else name.split()[-1].lower()


def rank(src):
    return SRC_RANK.index(src) if src in SRC_RANK else len(SRC_RANK)


SI_PREFIX_RX = re.compile(r"^\s*(supporting information|supplementary (information|materials?|data|files?|figures?|tables?)|"
                          r"electronic supplementary (information|material)|supplemental (information|materials?|data)|"
                          r"additional files? ?\d*)\s*(for|to|of)?\s*[:\-–—]?\s*", re.I)
DATA_TYPES = {"dataset", "software", "model", "workflow", "computationalnotebook", "datapaper", "physicalobject"}
ARTICLE_TYPES = {"journalarticle", "article", "preprint", "postedcontent", "conferencepaper", "proceedingsarticle"}


def _type_token(r):
    return re.sub(r"[^a-z]", "", str(r.get("type") or "").lower())


def si_parent(r, title_parent=None):
    """DOI of the paper an SI deposit belongs to: the ACS-style '<paper DOI>.s001', the deposit's IsSupplementTo
    relation, or a paper of the same batch whose title it repeats ('Supporting information for: <title>')."""
    doi = r.get("doi") or ""
    m = re.match(r"^(10\.\d{4,9}/.+?)\.s\d{3}$", doi)
    if m:
        return m.group(1)
    for x in r.get("supplement_to") or []:
        d = norm_doi(x) if isinstance(x, str) else None
        if d and d != doi:
            return d
    if title_parent:
        t = SI_PREFIX_RX.sub("", r.get("title") or "")
        if len(norm_title(t).split()) >= 5:
            return title_parent.get(title_hash(t))
    return None


def si_link(r, parent):
    url = r.get("landing_url") or r.get("pdf_url") or (f"https://doi.org/{r['doi']}" if r.get("doi") else None)
    return {"parent_doi": parent, "si_doi": r.get("doi") or url, "url": url, "title": (r.get("title") or "")[:300],
            "source": r.get("source")}


def is_si_deposit(r):
    doi = r.get("doi") or ""
    if r.get("supplement_to") and _type_token(r) not in DATA_TYPES | ARTICLE_TYPES:
        return True   # 'journal contribution' / text / figure that declares IsSupplementTo a paper: that paper's SI
    if re.search(r"\.s\d{3}$", doi):
        return True
    if SI_TITLE_RX.search(r.get("title") or ""):
        return True
    if doi.startswith(("10.6084/", "10.25384/")) and (str(r.get("type") or "").lower() not in (
            "journal contribution", "preprint", "conference contribution", "text", "journalarticle", "preprint")):
        return True   # Figshare files deposited by publishers (ACS, RSC, T&F ...) as a paper's SI
    return r.get("source") == "figshare" and (r.get("type") or "").lower() not in (
        "journal contribution", "preprint", "conference contribution")


def merge(group):
    group = sorted(group, key=lambda r: rank(r.get("source")))
    m = {"dois_all": [], "title": "", "authors": [], "year": None, "journal": None, "publisher": None, "type": None,
         "abstract": "", "databases": [], "external_ids": {}, "cited_by": None, "percentile": None,
         "is_preprint": False, "retracted": False, "is_oa_any": False, "oa_status": None, "oa_urls": [],
         "landing_urls": [], "locations": [], "licenses_seen": [], "crossref_licenses": [], "relation": None,
         "alternative_id": None, "epmc_fulltext": [], "update_to": None, "link": None, "relevance_score": None,
         "keywords": [], "authors_detail": [], "doc_types": [], "key": None, "abstract_source": None,
         "supplement_to": None, "decision": None}
    seen = set()
    for r in group:
        src = r.get("source")
        for s in [src] + list(r.get("found_in") or []):   # found_in: a WoS / Scopus export (import_list.py)
            if s not in m["databases"]:
                m["databases"].append(s)
        d = r.get("doi")
        if d and d not in m["dois_all"]:
            m["dois_all"].append(d)
        t = r.get("title") or ""
        if (len(t) > len(m["title"]) and src in ("crossref", "openalex", "europepmc", "s2", "arxiv")) or not m["title"]:
            m["title"] = t or m["title"]
        if not m["authors"] and r.get("authors"):
            m["authors"] = [a for a in r["authors"] if a]
        if len(r.get("authors_detail") or []) > len(m["authors_detail"]) and any(
                a.get("orcid") or a.get("institutions") for a in r.get("authors_detail") or []):
            m["authors_detail"] = r["authors_detail"]
        for k in r.get("keywords") or []:
            if k and k not in m["keywords"]:
                m["keywords"].append(k)
        dt = r.get("doc_type") or (norm_doc_type(r.get("type"), r.get("is_preprint")) if r.get("type") else None)
        if dt:
            m["doc_types"].append(dt)
        if r.get("key") and not m["key"]:
            m["key"] = r["key"]
        if r.get("supplement_to") and not m["supplement_to"]:
            m["supplement_to"] = r["supplement_to"]
        if r.get("decision"):
            m["decision"] = r["decision"]     # an imported list's scope decision (the latest import wins)
        for k in ("year", "journal", "publisher", "type", "oa_status"):
            if m[k] in (None, "") and r.get(k) not in (None, ""):
                m[k] = r[k]
        if len(r.get("abstract") or "") > len(m["abstract"]):
            m["abstract"] = r["abstract"]
            m["abstract_source"] = r.get("abstract_source") or SOURCE_LABEL.get(src, src)
        m["is_oa_any"] |= bool(r.get("is_oa"))
        m["retracted"] |= bool(r.get("retracted"))
        if r.get("cited_by_count") is not None and (m["cited_by"] is None or src == "openalex"):
            m["cited_by"] = r["cited_by_count"]
        if r.get("percentile_year_min") is not None and m["percentile"] is None:
            m["percentile"] = r["percentile_year_min"]
        if r.get("relevance_score") is not None and m["relevance_score"] is None:
            m["relevance_score"] = r["relevance_score"]
        for k, v in (r.get("ids") or {}).items():
            if v and not m["external_ids"].get(k):
                m["external_ids"][k] = v
        if r.get("license"):
            m["licenses_seen"].append({"source": src, "license": r["license"], "version": r.get("version"),
                                       "raw": r.get("license_raw") or r["license"]})
        for k in ("crossref_licenses", "epmc_fulltext"):
            if r.get(k) and not m[k]:
                m[k] = r[k]
        for k in ("relation", "alternative_id", "update_to"):
            if r.get(k) and not m[k]:
                m[k] = r[k]
        if r.get("is_preprint") or is_preprint_doi(d) or src in ("arxiv", "osf"):
            m["is_preprint"] = True
        if r.get("pdf_url") and r["pdf_url"] not in seen:
            seen.add(r["pdf_url"])
            m["oa_urls"].append({"url": r["pdf_url"], "source": src, "license": r.get("license"),
                                 "version": r.get("version") or ("submittedVersion" if src in ("arxiv", "osf") else None)})
        if r.get("landing_url") and r["landing_url"] not in seen:
            seen.add(r["landing_url"])
            m["landing_urls"].append({"url": r["landing_url"], "source": src})
        for l in r.get("locations") or []:
            key = (l.get("pdf_url") or "") + "|" + (l.get("url") or "")
            if key not in seen:
                seen.add(key)
                m["locations"].append(l)
    vor = sorted([d for d in m["dois_all"] if not is_preprint_doi(d)], key=doi_preference)
    m["doi"] = (vor or m["dois_all"] or [None])[0]
    m["preprint_dois"] = [d for d in m["dois_all"] if is_preprint_doi(d)]
    m["is_preprint"] = bool(m["dois_all"] and not vor) or (not m["dois_all"] and m["is_preprint"])
    m["is_erratum"] = is_erratum(m["title"], m["type"], m["doi"]) or any(
        (u.get("type") or "").lower() in ("retraction", "correction", "erratum") for u in (m["update_to"] or []))
    if not m["doi"]:
        m["link"] = (m["landing_urls"] or m["oa_urls"] or [{}])[0].get("url")
    # document type: the most specific type any source gave (patent/dataset/thesis/review beat a generic 'article')
    pri = ["erratum", "patent", "dataset", "software", "thesis", "review", "conference-paper", "book-chapter", "book",
           "report", "editorial", "letter", "preprint", "article", "other"]
    dts = sorted(set(m["doc_types"]), key=lambda t: pri.index(t) if t in pri else 99)
    m["doc_type"] = dts[0] if dts else norm_doc_type(m["type"], m["is_preprint"])
    if m["doc_type"] == "erratum" and not m["is_erratum"]:
        # one source typed it as a correction, but neither its title nor its DOI is a notice: a research paper
        m["doc_type"] = next((t for t in dts if t != "erratum"), "article")
    if m["doc_type"] == "preprint" and not m["is_preprint"] and "article" in dts:
        m["doc_type"] = "article"          # a published version was merged with its preprint
    if m["doc_type"] in ("article", "other") and m["is_preprint"]:
        m["doc_type"] = "preprint"
    if m["supplement_to"]:
        m["external_ids"]["supplement_to"] = norm_doi(m["supplement_to"][0]) or m["supplement_to"][0]
    return m


def dedup(recs):
    by_doi, nodoi, by_key = defaultdict(list), [], defaultdict(list)
    for r in recs:
        if r.get("doi"):
            by_doi[r["doi"]].append(r)
        elif r.get("key"):
            by_key[r["key"]].append(r)
        else:
            nodoi.append(r)
    th_index, gyear = defaultdict(set), {}
    for d, g in by_doi.items():
        for r in g:
            if len(norm_title(r.get("title")).split()) >= 5:
                th_index[title_hash(r.get("title"))].add(d)
            if r.get("year"):
                gyear[d] = r["year"]
    parent = {d: d for d in by_doi}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    linked = 0
    for ds in th_index.values():
        ds = sorted(ds)
        for a in ds[1:]:
            b = ds[0]
            ya, yb = gyear.get(a), gyear.get(b)
            copy = is_preprint_doi(a) or is_preprint_doi(b) or is_repository_doi(a) or is_repository_doi(b)
            if copy and (not ya or not yb or abs(int(ya) - int(yb)) <= 3):
                union(b, a)
                linked += 1
    for d in list(by_doi):
        tw = edition_twin(d)
        if tw and tw in parent:
            union(d, tw)
            linked += 1
    for d, g in by_doi.items():
        for r in g:
            for k in ("has-preprint", "is-preprint-of"):
                for x in (r.get("relation") or {}).get(k) or []:
                    od = norm_doi(x.get("id")) if x.get("id-type") == "doi" else None
                    if od and od in parent:
                        union(d, od)
                        linked += 1
    groups = defaultdict(list)
    for d, g in by_doi.items():
        groups[find(d)].extend(g)
    fb, attached = defaultdict(list), 0
    for r in nodoi:
        th, tgt = title_hash(r.get("title")), None
        if len(norm_title(r.get("title")).split()) >= 5:
            for d in th_index.get(th, ()):
                y = gyear.get(d)
                if not y or not r.get("year") or abs(int(y) - int(r["year"])) <= 1:
                    tgt = find(d)
                    break
        if tgt:
            groups[tgt].append(r)
            attached += 1
        else:
            fb[f"{th}_{surname((r.get('authors') or [''])[0])}_{r.get('year')}"].append(r)
    merged = [merge(g) for g in groups.values()] + [merge(g) for g in fb.values()] + [merge(g) for g in by_key.values()]
    return merged, {"doi_groups": len(by_doi), "preprint_links": linked, "nodoi_attached": attached,
                    "nodoi_groups": len(fb), "keyed_groups": len(by_key)}


def split_files(files, n):
    """n groups of consecutive raw files with about the same total size (a file goes where its middle falls)."""
    if n <= 1 or len(files) <= 1:
        return [files]
    n = min(n, len(files))
    total = sum(f.stat().st_size for f in files) or 1
    groups, cur, acc = [], [], 0
    for f in files:
        size = f.stat().st_size
        if cur and len(groups) < n - 1 and acc + size / 2 > total * (len(groups) + 1) / n:
            groups.append(cur)
            cur = []
        cur.append(f)
        acc += size
    return groups + ([cur] if cur else [])


def merge_hints(hp, hints, partial):
    """candidates.jsonl: write this batch's hints; with partial, keep the other papers' hints (streamed line by line,
    never loaded whole — the file reaches gigabytes on a large topic)."""
    tmp = Path(str(hp) + ".tmp")
    new_ids = {h["paper_id"] for h in hints}
    with open(tmp, "w", encoding="utf-8") as out:
        if partial and hp.exists():
            with open(hp, encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    m = re.match(r'\{"paper_id": (\d+)', line)
                    pid = int(m.group(1)) if m else json.loads(line).get("paper_id")
                    if pid not in new_ids:
                        out.write(line if line.endswith("\n") else line + "\n")
        for h in hints:
            out.write(json.dumps(h, ensure_ascii=False) + "\n")
    tmp.replace(hp)


def build_batch(proj, led, topic, gate, year_from, files, vocab):
    recs, si_recs, n_raw, n_off, n_si, n_old = [], [], 0, 0, 0, 0
    for f in files:
        for r in jsonl_iter(f):
            n_raw += 1
            if is_si_deposit(r):
                n_si += 1
                si_recs.append(r)
                continue
            if r.get("source") != "manual" and not gate.passes(r.get("title"), r.get("abstract")):
                n_off += 1
                continue
            y = str(r.get("year") or "")[:4]
            if year_from and r.get("source") != "manual" and y.isdigit() and int(y) < int(year_from):
                n_old += 1          # sources that filter by registration date (DataCite, Crossref) let older works in
                continue
            recs.append(r)
    log(f"raw={n_raw} si_deposits={n_si} off_topic={n_off} kept={len(recs)}")
    title_parent = {}
    for r in recs:
        if r.get("doi") and len(norm_title(r.get("title")).split()) >= 5:
            title_parent.setdefault(title_hash(r.get("title")), r["doi"])
    links = [si_link(r, p) for r in si_recs for p in [si_parent(r, title_parent)] if p]
    del si_recs, title_parent
    cands, dstats = dedup(recs)
    del recs
    created = existing = errata = decided = 0
    hints, created_ids, ids = [], [], []
    with led.tx():
        for m in cands:
            pid, new = led.upsert(m, topic)
            d = m.get("decision")
            if d:                  # import_list.py --scope file / in: a manual decision the screening keeps
                led.set_topic(pid, topic, relevance=d.get("relevance"), relevance_note=(d.get("note") or None),
                              relevance_method="manual", in_scope=int(bool(d.get("in_scope"))))
                decided += 1
            ids.append(pid)
            created += new
            if new:
                created_ids.append(pid)
            existing += not new
            upd = {}
            if m["is_erratum"]:
                upd["is_erratum"] = 1
                errata += 1
            if m["retracted"]:
                upd["retracted"] = 1
            if upd:
                led.set(pid, **upd)
            hints.append({"paper_id": pid, "doi": m["doi"], "dois_all": m["dois_all"], "preprint_dois": m["preprint_dois"],
                          "oa_urls": m["oa_urls"], "landing_urls": m["landing_urls"], "locations": m["locations"],
                          "licenses_seen": m["licenses_seen"], "crossref_licenses": m["crossref_licenses"],
                          "epmc_fulltext": m["epmc_fulltext"], "is_oa_any": m["is_oa_any"], "oa_status": m["oa_status"],
                          "external_ids": m["external_ids"], "alternative_id": m["alternative_id"],
                          "relevance_score": m["relevance_score"]})
        n_links = led.add_si_links(links)
    n_topics = 0
    for i in range(0, len(ids), 20000):      # vocabulary topics for the papers of this batch that have none yet
        ch = ids[i:i + 20000]
        rows = []
        for j in range(0, len(ch), 900):
            part = ch[j:j + 900]
            rows += led.topic_rows(topic, f"AND p.id IN ({','.join('?' * len(part))})", tuple(part))
        n_topics += apply_vocab(led, vocab, rows, only_missing=True)
    stats = {"raw_records": n_raw, "si_deposits_set_aside": n_si, "si_links_added": n_links,
             "off_topic_dropped_by_gate": n_off, "older_than_year_from": n_old, "unique_papers": len(cands),
             "new_in_ledger": created, "already_in_ledger": existing, "errata_or_corrections": errata,
             "manual_decisions": decided,
             "topics_assigned": n_topics, **dstats}
    return stats, hints, created_ids


def main():
    ap = add_project_arg(argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter))
    ap.add_argument("--topic", required=True)
    ap.add_argument("--run", action="append", default=None, help="only these raw runs (full, since-YYYY-MM-DD, manual)")
    ap.add_argument("--batches", type=int, default=1, help="process the raw files in N groups (large topics)")
    ap.add_argument("--no-export", action="store_true", help="do not refresh the index CSVs and papers.db at the end")
    ap.add_argument("--si-links-only", action="store_true", help="only link SI deposits in the raw hits to their papers")
    a = ap.parse_args()
    proj = Project(a.project)
    cfg = load_config(proj, a.topic)
    gate = Gate(cfg.get("gate"))
    year_from = (cfg.get("search") or {}).get("year_from")
    raw_dir = proj.topic_dir(a.topic) / "raw"
    files = sorted(f for r in a.run for f in (raw_dir / r).glob("*.jsonl")) if a.run else sorted(raw_dir.rglob("*.jsonl"))
    led = Ledger(proj)
    if a.si_links_only:
        n_si = n_links = 0
        links = []
        for f in files:
            for r in jsonl_iter(f):
                if is_si_deposit(r):
                    n_si += 1
                    p = si_parent(r)
                    if p:
                        links.append(si_link(r, p))
            if len(links) >= 5000:
                with led.tx():
                    n_links += led.add_si_links(links)
                links = []
        with led.tx():
            n_links += led.add_si_links(links)
        if not a.no_export:
            led.export(topics=[a.topic])
        print(json.dumps({"si_deposits": n_si, "si_links_added": n_links}))
        return
    vocab = Vocab(proj)
    run_started = now_iso()
    groups = split_files(files, a.batches)
    hp = proj.topic_dir(a.topic) / "candidates.jsonl"
    totals, created_all = Counter(), []
    for i, g in enumerate(groups, 1):
        if len(groups) > 1:
            log(f"batch {i}/{len(groups)}: {len(g)} raw files")
        st, hints, created_ids = build_batch(proj, led, a.topic, gate, year_from, g, vocab)
        merge_hints(hp, hints, partial=bool(a.run) or i > 1)
        totals.update(st)
        created_all += created_ids
        del hints
    if not a.no_export:
        led.export(topics=[a.topic])
    stats = {**dict(totals), "batches": len(groups), "database": None if a.no_export else led.last_publish, "new_ids": created_all[:50],
             "run_started": run_started, "built_at": now_iso()}
    if a.no_export:
        stats["next"] = "export.py --topic " + a.topic + " (index CSVs and papers.db were not refreshed)"

    def fn(st):
        st["build_list"] = stats
        st.setdefault("build_list_runs", {})[",".join(a.run) if a.run else "all"] = stats
        st.setdefault("steps_done", [])
        if "build_list" not in st["steps_done"]:
            st["steps_done"].append("build_list")
    update_state(proj, a.topic, fn)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
