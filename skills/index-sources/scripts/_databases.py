"""Search-API fetchers (library module — not run directly). One function per database:

    fetch(query, cursor, since, ctx) -> (records, next_cursor_or_None, total_or_None)

`query` is a string in the database's own syntax, or a dict {"q": ..., "filter": ...} where the database supports an extra
filter (Crossref, OpenAlex, DataCite types). `since` (YYYY-MM-DD or None) restricts results to newer works for update
mode. Records use one normalized shape (see `rec()` below). CATALOG at the end lists every database the skill knows —
automated (keyless or with a key from keys.txt) and the ones it deliberately does not query, with the reason.
Query syntax per database: references/databases.md.
"""
import datetime as _dt
import re
import urllib.parse
import xml.etree.ElementTree as ET

from _common import HTTPFail, clean_text, get_json, http_get, patient, polite_email, reconstruct_abstract

MAX_AUTHORS_KEPT = 50


def rec(**kw):
    r = {"doi": None, "title": "", "abstract": "", "year": None, "journal": None, "publisher": None, "type": None,
         "authors": [], "is_oa": None, "oa_status": None, "license": None, "pdf_url": None, "landing_url": None,
         "version": None, "locations": [], "ids": {}, "cited_by_count": None, "relevance_score": None,
         "keywords": [], "authors_detail": [], "doc_type": None, "license_raw": None}
    r.update({k: v for k, v in kw.items() if v is not None})
    r["authors"] = [a for a in (r.get("authors") or []) if a][:MAX_AUTHORS_KEPT]
    r["authors_detail"] = [a for a in (r.get("authors_detail") or []) if a.get("name")][:MAX_AUTHORS_KEPT]
    if r.get("license") and not r.get("license_raw"):
        r["license_raw"] = r["license"]
    return r


def _orcid(x):
    x = (x or "").strip().rstrip("/")
    return x.rsplit("/", 1)[-1] if x else None


def _q(query):
    return (query.get("q") or "") if isinstance(query, dict) else str(query)


def _int_year(s):
    s = str(s or "")[:4]
    return int(s) if s.isdigit() else None


# ---------------------------------------------------------------- OpenAlex
OALEX_SELECT = ("id,doi,display_name,publication_year,type,language,primary_location,best_oa_location,locations,"
                "open_access,cited_by_count,cited_by_percentile_year,abstract_inverted_index,ids,authorships,"
                "primary_topic,is_retracted,keywords")


def openalex_record(w):
    def loc(l):
        src = l.get("source") or {}
        return {"url": l.get("landing_page_url"), "pdf_url": l.get("pdf_url"), "license": l.get("license"),
                "version": l.get("version"), "is_oa": l.get("is_oa"), "host": src.get("display_name"),
                "host_type": src.get("type"), "source": "openalex"}
    pl = w.get("primary_location") or {}
    bo = w.get("best_oa_location") or {}
    detail = []
    for a in w.get("authorships") or []:
        au = a.get("author") or {}
        detail.append({"name": au.get("display_name") or a.get("raw_author_name"), "orcid": _orcid(au.get("orcid")),
                       "openalex": (au.get("id") or "").rsplit("/", 1)[-1] or None,
                       "institutions": [i.get("display_name") for i in a.get("institutions") or [] if i.get("display_name")],
                       "countries": a.get("countries") or []})
    ids = w.get("ids") or {}
    pct = w.get("cited_by_percentile_year") or {}
    oa = w.get("open_access") or {}
    return rec(doi=w.get("doi"), title=w.get("display_name"), abstract=reconstruct_abstract(w.get("abstract_inverted_index")),
               year=w.get("publication_year"), type=w.get("type"), journal=(pl.get("source") or {}).get("display_name"),
               publisher=(pl.get("source") or {}).get("host_organization_name"),
               authors=[(a.get("author") or {}).get("display_name") for a in (w.get("authorships") or [])],
               is_oa=oa.get("is_oa"), oa_status=oa.get("oa_status"), license=bo.get("license"), pdf_url=bo.get("pdf_url"),
               landing_url=pl.get("landing_page_url"), version=bo.get("version"),
               locations=[loc(l) for l in (w.get("locations") or [])],
               ids={"openalex": w.get("id"), "pmcid": ids.get("pmcid"), "pmid": ids.get("pmid")},
               cited_by_count=w.get("cited_by_count"), percentile_year_min=pct.get("min"),
               percentile_year_max=pct.get("max"), retracted=w.get("is_retracted"), authors_detail=detail,
               keywords=[k.get("display_name") for k in w.get("keywords") or [] if k.get("display_name")])


OPENALEX_PAGE_LIMIT = 100   # page= paging (the only kind OpenAlex allows without a key) stops at 10,000 results


def openalex_budget_ok(resp, reserve=0.004):
    """(ok, usd_left): what is left today = the free daily budget plus any prepaid credit (OpenAlex spends prepaid
    credit only once the free daily budget is used up, so a run goes on while either lasts)."""
    def usd(name):
        try:
            return float(resp.headers.get(name))
        except (TypeError, ValueError):
            return None
    free = usd("X-RateLimit-Remaining-USD")
    if free is None:
        return True, None
    rem = round(free + (usd("X-RateLimit-Prepaid-Remaining-USD") or 0.0), 4)
    return rem > reserve, rem


def fetch_openalex(query, cursor, since, ctx):
    flt = _q(query) if not isinstance(query, dict) else (query.get("filter") or query.get("q"))
    if "type:" not in flt:
        flt += ",type:article|review|preprint"
    if since:
        flt += f",from_publication_date:{since}"
    key = ctx.get("keys", {}).get("openalex")
    params = {"per_page": 200, "select": OALEX_SELECT, "filter": flt}   # OpenAlex maximum: half the requests
    # Without a key OpenAlex pages only with page= (cursor paging past the first page needs a free key: HTTP 401), and
    # page= stops at 10,000 results per query. The resume token is then "page:<n>".
    page = int(str(cursor)[5:]) if str(cursor or "").startswith("page:") else None
    if key:
        params["api_key"] = key
        if page:
            params["page"] = page                      # started without a key: keep paging the same way
        else:
            params["cursor"] = cursor or "*"
    else:
        if cursor and cursor != "*" and not page:
            raise HTTPFail("key", "OpenAlex: this query was being paged with an API key that is missing now; add "
                                  "'openalex: <key>' to ~/.scale/sources/keys.txt and re-run")
        page = page or 1
        if page > OPENALEX_PAGE_LIMIT:
            raise HTTPFail("key", f"OpenAlex without an API key returns at most {OPENALEX_PAGE_LIMIT * 100:,} results "
                                  "per query; add a free key ('openalex: <key>' in ~/.scale/sources/keys.txt) "
                                  "and re-run to get the rest")
        params["page"] = page
    if polite_email():
        params["mailto"] = polite_email()
    if ctx.get("openalex_stop"):
        raise HTTPFail("budget", "OpenAlex daily budget reserve reached; resume after the UTC-midnight reset")
    r = http_get("https://api.openalex.org/works", params=params, tries=5, timeout=(20, 120))
    ok, rem = openalex_budget_ok(r)
    if not ok:
        ctx["openalex_stop"] = True
    d = r.json()
    meta = d.get("meta") or {}
    recs = [openalex_record(w) for w in d.get("results") or []]
    if "page" in params:
        more = recs and params["page"] * 100 < (meta.get("count") or 0)
        nxt = f"page:{params['page'] + 1}" if more else None
    else:
        nxt = meta.get("next_cursor") if recs else None
    return recs, nxt, meta.get("count")


# ---------------------------------------------------------------- Crossref
CR_SELECT = ("DOI,title,abstract,author,published,published-online,published-print,issued,created,container-title,"
             "publisher,type,license,link,is-referenced-by-count,relation,alternative-id,score,update-to")


def crossref_items(d):
    recs = []
    for it in d["message"].get("items") or []:
        yr = None
        for k in ("published", "published-online", "published-print", "issued", "created"):
            dp = (it.get(k) or {}).get("date-parts")
            if dp and dp[0] and dp[0][0]:
                yr = dp[0][0]
                break
        authors, detail = [], []
        for a in it.get("author") or []:
            nm = " ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name")
            if nm:
                authors.append(nm)
                detail.append({"name": nm, "orcid": _orcid(a.get("ORCID")),
                               "institutions": [x.get("name") for x in a.get("affiliation") or [] if x.get("name")]})
        recs.append(rec(doi=it.get("DOI"), title=(it.get("title") or [""])[0], abstract=it.get("abstract"), year=yr,
                        journal=(it.get("container-title") or [None])[0] if it.get("container-title") else None,
                        publisher=it.get("publisher"), type=it.get("type"), authors=authors,
                        crossref_licenses=[{"url": l.get("URL"), "version": l.get("content-version")}
                                           for l in it.get("license") or []],
                        relevance_score=it.get("score"), cited_by_count=it.get("is-referenced-by-count"),
                        relation=it.get("relation"), alternative_id=it.get("alternative-id"),
                        update_to=it.get("update-to"), authors_detail=detail,
                        license_raw=next((l.get("URL") for l in it.get("license") or []
                                          if (l.get("content-version") or "vor") in ("vor", "unspecified")), None)))
    return recs


def fetch_crossref(query, cursor, since, ctx):
    q = _q(query)
    flt = (query.get("filter") if isinstance(query, dict) else None) or \
        "type:journal-article,type:posted-content,type:proceedings-article"
    if since:
        flt += f",from-created-date:{since}"
    params = {"query.bibliographic": q, "filter": flt, "rows": 1000, "cursor": cursor or "*", "sort": "score",
              "order": "desc", "select": CR_SELECT}
    if polite_email():
        params["mailto"] = polite_email()
    d = get_json("https://api.crossref.org/works", params=params, tries=6, timeout=(20, 120))
    recs = crossref_items(d)
    return recs, (d["message"].get("next-cursor") if recs else None), d["message"].get("total-results")


# ---------------------------------------------------------------- Semantic Scholar (bulk search)
def fetch_s2(query, cursor, since, ctx):
    fields = ("paperId,externalIds,title,abstract,year,venue,journal,publicationTypes,openAccessPdf,isOpenAccess,"
              "citationCount,influentialCitationCount,authors,publicationDate")
    params = {"query": _q(query), "fields": fields}
    if cursor:
        params["token"] = cursor
    if since:
        params["publicationDateOrYear"] = f"{since}:"
    headers = {"x-api-key": ctx["keys"]["s2"]} if ctx.get("keys", {}).get("s2") else None
    d = patient(get_json, "https://api.semanticscholar.org/graph/v1/paper/search/bulk", params=params,
                headers=headers, tries=2, label="s2")
    recs = []
    for p in d.get("data") or []:
        ex = p.get("externalIds") or {}
        oa = p.get("openAccessPdf") or {}
        recs.append(rec(doi=ex.get("DOI"), title=p.get("title"), abstract=p.get("abstract"), year=p.get("year"),
                        journal=(p.get("journal") or {}).get("name") or p.get("venue"),
                        type=",".join(p.get("publicationTypes") or []),
                        authors=[a.get("name") for a in (p.get("authors") or [])], is_oa=p.get("isOpenAccess"),
                        oa_status=oa.get("status"), license=oa.get("license"), pdf_url=oa.get("url"),
                        ids={"s2": p.get("paperId"), "arxiv": ex.get("ArXiv"), "pmcid": ex.get("PubMedCentral"),
                             "pmid": ex.get("PubMed")},
                        cited_by_count=p.get("citationCount"), influential_citations=p.get("influentialCitationCount")))
    return recs, d.get("token"), d.get("total")


# ---------------------------------------------------------------- Europe PMC
def fetch_europepmc(query, cursor, since, ctx):
    q = _q(query)
    if since:
        q = f"({q}) AND (FIRST_PDATE:[{since} TO 3000-12-31])"
    params = {"query": q, "format": "json", "pageSize": 1000, "cursorMark": cursor or "*", "resultType": "core"}
    d = get_json("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params=params, tries=6, timeout=(20, 180))
    recs = []
    for r in (d.get("resultList") or {}).get("result") or []:
        fts = [{"url": u.get("url"), "style": u.get("documentStyle"), "availability": u.get("availability"),
                "site": u.get("site")} for u in ((r.get("fullTextUrlList") or {}).get("fullTextUrl") or [])]
        recs.append(rec(doi=r.get("doi"), title=r.get("title"), abstract=r.get("abstractText"),
                        year=_int_year(r.get("pubYear")),
                        journal=((r.get("journalInfo") or {}).get("journal") or {}).get("title"),
                        authors=[a.strip() for a in (r.get("authorString") or "").split(",") if a.strip()],
                        is_oa=r.get("isOpenAccess") == "Y", license=r.get("license"),
                        type=",".join((r.get("pubTypeList") or {}).get("pubType") or []),
                        ids={"pmcid": r.get("pmcid"), "pmid": r.get("pmid"),
                             **({"patent": r.get("id")} if r.get("source") == "PAT" else {})},
                        epmc_fulltext=fts, cited_by_count=r.get("citedByCount"),
                        keywords=((r.get("keywordList") or {}).get("keyword") or []),
                        doc_type=("patent" if r.get("source") == "PAT" else "thesis" if r.get("source") == "ETH" else
                                  "preprint" if r.get("source") == "PPR" else None),
                        key=(patent_key("", r.get("id")) if r.get("source") == "PAT" else None),
                        landing_url=(f"https://europepmc.org/article/{r.get('source')}/{r.get('id')}"
                                     if r.get("source") in ("PAT", "ETH", "PPR") else None)))
    nxt = d.get("nextCursorMark")
    if not recs or nxt == cursor:
        nxt = None
    return recs, nxt, d.get("hitCount")


# ---------------------------------------------------------------- OpenAIRE Graph
def fetch_openaire(query, cursor, since, ctx):
    rtype = (query.get("type") if isinstance(query, dict) else None) or "publication"
    params = {"search": _q(query), "type": rtype, "pageSize": 100, "cursor": cursor or "*"}
    if since:
        params["fromPublicationDate"] = since
    d = get_json("https://api.openaire.eu/graph/v1/researchProducts", params=params, tries=6, timeout=(20, 120))
    recs = []
    for r in d.get("results") or []:
        doi = next((p.get("value") for p in (r.get("pids") or []) if p.get("scheme") == "doi"), None)
        locs = []
        for ins in r.get("instances") or []:
            if not doi:
                doi = next((p.get("value") for p in (ins.get("pids") or []) if p.get("scheme") == "doi"), None)
            for u in ins.get("urls") or []:
                locs.append({"url": u, "license": ins.get("license"), "access": (ins.get("accessRight") or {}).get("label"),
                             "type": ins.get("type"), "host": (ins.get("hostedBy") or {}).get("value"),
                             "source": "openaire", "is_oa": (ins.get("accessRight") or {}).get("label") == "OPEN ACCESS"})
        recs.append(rec(doi=doi, title=r.get("mainTitle"), abstract=" ".join(r.get("descriptions") or []),
                        year=_int_year(r.get("publicationDate")), journal=(r.get("container") or {}).get("name"),
                        publisher=r.get("publisher"), authors=[a.get("fullName") for a in (r.get("authors") or [])],
                        is_oa=((r.get("bestAccessRight") or {}).get("label") == "OPEN ACCESS"),
                        oa_status=r.get("openAccessColor"), locations=locs, ids={"openaire": r.get("id")},
                        doc_type=("dataset" if rtype == "dataset" else "software" if rtype == "software" else None),
                        type=r.get("type"),
                        keywords=[(x.get("subject") or {}).get("value") for x in r.get("subjects") or []
                                  if ((x.get("subject") or {}).get("scheme") or "") == "keyword"]))
    nxt = (d.get("header") or {}).get("nextCursor")
    return recs, (nxt if recs else None), (d.get("header") or {}).get("numFound")


# ---------------------------------------------------------------- OSTI
def fetch_osti(query, cursor, since, ctx):
    pg = int(cursor or 1)
    params = {"q": _q(query), "rows": 200, "page": pg}
    if since:
        y, m, dd = since.split("-")
        params["publication_date_start"] = f"{m}/{dd}/{y}"
    r = http_get("https://www.osti.gov/api/v1/records", params=params, headers={"Accept": "application/json"},
                 tries=6, timeout=(20, 120))
    d = r.json()
    tot = int(r.headers.get("X-Total-Count", "0") or 0)
    recs = []
    for x in d or []:
        ft = next((l.get("href") for l in (x.get("links") or []) if l.get("rel") == "fulltext"), None)
        recs.append(rec(doi=x.get("doi"), title=x.get("title"), abstract=x.get("description"),
                        year=_int_year(x.get("publication_date")), journal=x.get("journal_name"),
                        publisher=x.get("publisher"), type=x.get("product_type"),
                        authors=[a if isinstance(a, str) else a.get("name") for a in (x.get("authors") or [])],
                        pdf_url=ft, landing_url=f"https://www.osti.gov/biblio/{x.get('osti_id')}",
                        ids={"osti": x.get("osti_id")}, keywords=[k for k in (x.get("subjects") or [])
                                                                  if isinstance(k, str) and not k[:1].isdigit()]))
    return recs, (str(pg + 1) if recs and pg * 200 < tot else None), tot


# ---------------------------------------------------------------- arXiv
_AX_NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom",
          "os": "http://a9.com/-/spec/opensearch/1.1/"}


def fetch_arxiv(query, cursor, since, ctx):
    q = _q(query)
    if since:
        q = f"({q}) AND submittedDate:[{since.replace('-', '')}0000 TO 300012312359]"
    start = int(cursor or 0)
    r = patient(http_get, "https://export.arxiv.org/api/query",
                params={"search_query": q, "start": start, "max_results": 200, "sortBy": "submittedDate",
                        "sortOrder": "descending"}, tries=1, timeout=(20, 120), label="arxiv", max_wait_s=7200)
    root = ET.fromstring(r.content)
    tot = int(root.findtext("os:totalResults", default="0", namespaces=_AX_NS) or 0)
    recs = []
    for e in root.findall("a:entry", _AX_NS):
        aid = (e.findtext("a:id", default="", namespaces=_AX_NS) or "").rsplit("/abs/", 1)[-1]
        aid_nov = re.sub(r"v\d+$", "", aid)
        pdf = next((l.get("href") for l in e.findall("a:link", _AX_NS) if l.get("title") == "pdf"), None)
        recs.append(rec(doi=e.findtext("arxiv:doi", default=None, namespaces=_AX_NS),
                        title=e.findtext("a:title", default="", namespaces=_AX_NS),
                        abstract=e.findtext("a:summary", default="", namespaces=_AX_NS),
                        year=_int_year(e.findtext("a:published", default="", namespaces=_AX_NS)),
                        journal=e.findtext("arxiv:journal_ref", default=None, namespaces=_AX_NS),
                        authors=[a.findtext("a:name", default="", namespaces=_AX_NS) for a in e.findall("a:author", _AX_NS)],
                        is_oa=True, pdf_url=pdf or f"https://arxiv.org/pdf/{aid}",
                        landing_url=f"https://arxiv.org/abs/{aid_nov}", type="preprint", version="submittedVersion",
                        ids={"arxiv": aid_nov}, is_preprint=True))
    return recs, (str(start + 200) if recs and start + 200 < tot else None), tot


# ---------------------------------------------------------------- DOAJ
def fetch_doaj(query, cursor, since, ctx):
    pg = int(cursor or 1)
    url = "https://doaj.org/api/v4/search/articles/" + urllib.parse.quote(_q(query), safe="")
    d = get_json(url, params={"page": pg, "pageSize": 100}, tries=6, timeout=(20, 120))
    recs = []
    for x in d.get("results") or []:
        b = x.get("bibjson") or {}
        doi = next((i.get("id") for i in (b.get("identifier") or []) if (i.get("type") or "").lower() == "doi"), None)
        ft = next((l.get("url") for l in (b.get("link") or []) if l.get("type") == "fulltext"), None)
        y = _int_year(b.get("year"))
        if since and y and y < int(since[:4]):
            continue
        recs.append(rec(doi=doi, title=b.get("title"), abstract=b.get("abstract"), year=y,
                        journal=(b.get("journal") or {}).get("title"), publisher=(b.get("journal") or {}).get("publisher"),
                        authors=[a.get("name") for a in (b.get("author") or [])], is_oa=True, oa_status="gold",
                        landing_url=ft, ids={"doaj": x.get("id")},
                        doaj_journal_license=[l.get("type") for l in ((b.get("journal") or {}).get("license") or [])],
                        keywords=b.get("keywords") or []))
    tot = d.get("total") or 0
    return recs, (str(pg + 1) if (d.get("results") and pg * 100 < min(tot, 1000)) else None), tot  # API caps at 1000


# ---------------------------------------------------------------- HAL
def fetch_hal(query, cursor, since, ctx):
    fl = ("docid,halId_s,doiId_s,title_s,authFullName_s,producedDateY_i,journalTitle_s,publisher_s,fileMain_s,"
          "files_s,openAccess_bool,licence_s,abstract_s,docType_s,uri_s,keyword_s")
    start = int(cursor or 0)
    params = {"q": _q(query), "wt": "json", "rows": 500, "start": start, "fl": fl}
    if since:
        params["fq"] = f"producedDate_tdate:[{since}T00:00:00Z TO *]"
    d = get_json("https://api.archives-ouvertes.fr/search/", params=params, tries=6)
    resp = d.get("response") or {}
    recs = [rec(doi=x.get("doiId_s"), title=(x.get("title_s") or [""])[0], abstract=(x.get("abstract_s") or [""])[0],
                year=x.get("producedDateY_i"), journal=x.get("journalTitle_s"), publisher=x.get("publisher_s"),
                authors=x.get("authFullName_s") or [], type=x.get("docType_s"), is_oa=x.get("openAccess_bool"),
                license=x.get("licence_s"), pdf_url=x.get("fileMain_s"), landing_url=x.get("uri_s"),
                ids={"hal": x.get("halId_s")}, keywords=x.get("keyword_s") or []) for x in resp.get("docs") or []]
    tot = resp.get("numFound") or 0
    return recs, (str(start + 500) if recs and start + 500 < tot else None), tot


# ---------------------------------------------------------------- Zenodo
def fetch_zenodo(query, cursor, since, ctx):
    pg = int(cursor or 1)
    q = _q(query)
    if since:
        q = f"({q}) AND publication_date:[{since} TO *]"
    rtype = (query.get("type") if isinstance(query, dict) else None) or "publication"
    hz = {"Authorization": f"Bearer {ctx['keys']['zenodo']}"} if ctx.get("keys", {}).get("zenodo") else None
    d = get_json("https://zenodo.org/api/records", params={"q": q, "type": rtype, "size": 25, "page": pg}, headers=hz,
                 tries=6)
    hits = d.get("hits") or {}
    recs = []
    for x in hits.get("hits") or []:
        md = x.get("metadata") or {}
        pdfs = [f.get("links", {}).get("self") for f in (x.get("files") or []) if (f.get("key") or "").lower().endswith(".pdf")]
        recs.append(rec(doi=md.get("doi") or x.get("doi"), title=md.get("title"), abstract=md.get("description"),
                        year=_int_year(md.get("publication_date")), journal=(md.get("journal") or {}).get("title"),
                        authors=[c.get("name") for c in (md.get("creators") or [])],
                        type=((md.get("resource_type") or {}).get("subtype") or (md.get("resource_type") or {}).get("type")),
                        is_oa=(md.get("access_right") == "open"), license=(md.get("license") or {}).get("id"),
                        pdf_url=pdfs[0] if pdfs else None, landing_url=(x.get("links") or {}).get("self_html"),
                        ids={"zenodo": x.get("id")}, keywords=md.get("keywords") or []))
    tot = hits.get("total") or 0
    return recs, (str(pg + 1) if recs and pg * 25 < min(tot, 9975) else None), tot


# ---------------------------------------------------------------- PubMed Central (Entrez)
def fetch_pmc(query, cursor, since, ctx):
    start = int(cursor or 0)
    params = {"db": "pmc", "term": _q(query), "retmode": "json", "retmax": 200, "retstart": start,
              "tool": "scale-index-sources"}
    if ctx.get("keys", {}).get("ncbi"):
        params["api_key"] = ctx["keys"]["ncbi"]
    if since:
        params.update({"datetype": "pdat", "mindate": since.replace("-", "/"), "maxdate": "3000/12/31"})
    d = get_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", params=params, tries=6)
    es = d.get("esearchresult") or {}
    ids = es.get("idlist") or []
    tot = int(es.get("count") or 0)
    recs = []
    if ids:
        sp = {"db": "pmc", "id": ",".join(ids), "retmode": "json", "tool": "scale-index-sources"}
        s = get_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi", params=sp, tries=6)
        res = s.get("result") or {}
        for i in ids:
            x = res.get(i) or {}
            aids = {a.get("idtype"): a.get("value") for a in (x.get("articleids") or [])}
            recs.append(rec(doi=aids.get("doi"), title=x.get("title"), year=_int_year(x.get("pubdate")),
                            journal=x.get("fulljournalname"), authors=[a.get("name") for a in (x.get("authors") or [])],
                            ids={"pmcid": aids.get("pmcid") or f"PMC{i}", "pmid": aids.get("pmid")}))
    return recs, (str(start + 200) if ids and start + 200 < tot else None), tot


# ---------------------------------------------------------------- Figshare / OSF / PLOS
def fetch_figshare(query, cursor, since, ctx):
    pg = int(cursor or 1)
    body = {"search_for": _q(query), "page_size": 100, "page": pg}
    if since:
        body["published_since"] = since
    d = http_get("https://api.figshare.com/v2/articles/search", method="POST", json_body=body, tries=6).json()
    recs = [rec(doi=x.get("doi"), title=x.get("title"), year=_int_year(x.get("published_date")),
                type=x.get("defined_type_name"), landing_url=x.get("url_public_html"), ids={"figshare": x.get("id")},
                is_oa=True) for x in d or []]
    return recs, (str(pg + 1) if len(d or []) == 100 and pg < 20 else None), None


def fetch_osf(query, cursor, since, ctx):
    params = {"filter[title]": _q(query), "page[size]": 100}
    if since:
        params["filter[date_created][gte]"] = since
    url = cursor or "https://api.osf.io/v2/preprints/?" + urllib.parse.urlencode(params)
    try:
        d = get_json(url, tries=4)
    except HTTPFail as e:
        if str(e.status).startswith("4"):
            return [], None, 0
        raise
    recs = []
    for x in d.get("data") or []:
        a = x.get("attributes") or {}
        recs.append(rec(doi=a.get("doi") or (x.get("links") or {}).get("preprint_doi"), title=a.get("title"),
                        abstract=a.get("description"), year=_int_year(a.get("date_published")),
                        landing_url=(x.get("links") or {}).get("html"), is_oa=True, type="preprint",
                        version="submittedVersion", ids={"osf": x.get("id")}, is_preprint=True))
    return recs, (d.get("links") or {}).get("next"), ((d.get("links") or {}).get("meta") or {}).get("total")


def fetch_plos(query, cursor, since, ctx):
    start = int(cursor or 0)
    params = {"q": _q(query), "fl": "id,title_display,abstract,journal,publication_date,author_display", "rows": 100,
              "start": start, "wt": "json"}
    if since:
        params["fq"] = f"publication_date:[{since}T00:00:00Z TO *]"
    d = get_json("https://api.plos.org/search", params=params, tries=5)
    resp = d.get("response") or {}
    recs = [rec(doi=x.get("id"), title=x.get("title_display"), abstract=" ".join(x.get("abstract") or []),
                journal=x.get("journal"), year=_int_year(x.get("publication_date")), authors=x.get("author_display") or [],
                is_oa=True, license="cc-by", publisher="PLOS") for x in resp.get("docs") or []]
    tot = resp.get("numFound") or 0
    return recs, (str(start + 100) if recs and start + 100 < tot else None), tot


# ---------------------------------------------------------------- Crossref preprint servers
def fetch_crossref_preprints(query, cursor, since, ctx):
    """Crossref 'posted-content': ChemRxiv, Research Square, SSRN, Preprints.org, bioRxiv/medRxiv, TechRxiv,
    Authorea / ESS Open Archive, EngrXiv ... (the servers' own APIs are bot-walled or date-listing only)."""
    q = dict(query) if isinstance(query, dict) else {"q": query}
    q["filter"] = "type:posted-content"
    recs, nxt, tot = fetch_crossref(q, cursor, since, ctx)
    for r in recs:
        r["is_preprint"], r["doc_type"], r["version"] = True, "preprint", "submittedVersion"
    return recs, nxt, tot


# ---------------------------------------------------------------- DataCite (datasets, theses, reports, preprints)
SI_DOI_PREFIXES = ("10.6084/", "10.25384/")   # Figshare (ACS, RSC, T&F... SI) — attached to their source, not listed


def fetch_datacite(query, cursor, since, ctx):
    q = _q(query)
    if since:
        q = f"({q}) AND created:[{since} TO *]"
    if cursor and cursor.startswith("http"):
        d = get_json(cursor, tries=5, timeout=(20, 120))
    else:
        params = {"query": q, "page[size]": 100, "page[cursor]": 1}
        types = query.get("types") if isinstance(query, dict) else None
        if types:
            params["resource-type-id"] = types
        d = get_json("https://api.datacite.org/dois", params=params, tries=5, timeout=(20, 120))
    recs = []
    for x in d.get("data") or []:
        a = x.get("attributes") or {}
        t = a.get("types") or {}
        rights = a.get("rightsList") or []
        lic = next((r.get("rightsUri") or r.get("rightsIdentifier") or r.get("rights") for r in rights
                    if "creativecommons" in str(r.get("rightsUri") or r.get("rightsIdentifier") or "").lower()
                    or str(r.get("rightsIdentifier") or "").lower().startswith("cc")), None)
        restricted = any("restricted" in str(r.get("rightsUri") or "") or "closed" in str(r.get("rightsUri") or "")
                         for r in rights)
        abstract = next((dd.get("description") for dd in a.get("descriptions") or []
                         if dd.get("descriptionType") == "Abstract"), "")
        detail = []
        for c in a.get("creators") or []:
            orc = next((i.get("nameIdentifier") for i in c.get("nameIdentifiers") or []
                        if (i.get("nameIdentifierScheme") or "").upper() == "ORCID"), None)
            detail.append({"name": c.get("name"), "orcid": _orcid(orc),
                           "institutions": [f if isinstance(f, str) else f.get("name") for f in c.get("affiliation") or []]})
        sup = [r.get("relatedIdentifier") for r in a.get("relatedIdentifiers") or []
               if r.get("relationType") == "IsSupplementTo" and (r.get("relatedIdentifierType") or "").upper() == "DOI"]
        pub = a.get("publisher")
        recs.append(rec(doi=a.get("doi"), title=((a.get("titles") or [{}])[0] or {}).get("title"), abstract=abstract,
                        year=_int_year(a.get("publicationYear")), publisher=pub if isinstance(pub, str) else (pub or {}).get("name"),
                        journal=(a.get("container") or {}).get("title"),
                        authors=[c.get("name") for c in a.get("creators") or []], authors_detail=detail,
                        type=t.get("resourceTypeGeneral") or t.get("resourceType"),
                        is_oa=(None if restricted else bool(lic) or None), license=lic, landing_url=a.get("url"),
                        keywords=[sj.get("subject") for sj in a.get("subjects") or [] if sj.get("subject")][:15],
                        ids={"datacite": a.get("doi")}, supplement_to=sup or None,
                        is_preprint=(t.get("resourceTypeGeneral") == "Preprint")))
    nxt = (d.get("links") or {}).get("next") if recs else None
    return recs, nxt, (d.get("meta") or {}).get("total")


# ---------------------------------------------------------------- data repositories
def fetch_dataverse(query, cursor, since, ctx):
    start = int(cursor or 0)
    params = {"q": _q(query), "type": "dataset", "per_page": 100, "start": start}
    if since:
        params["fq"] = f"dateSort:[{since}T00:00:00Z TO *]"
    d = get_json("https://dataverse.harvard.edu/api/search", params=params, tries=5, timeout=(20, 120))
    data = d.get("data") or {}
    recs = [rec(doi=(x.get("global_id") or "").replace("doi:", "") if (x.get("global_id") or "").startswith("doi:") else None,
                title=x.get("name"), abstract=x.get("description"), year=_int_year(x.get("published_at")),
                publisher=x.get("publisher"), authors=x.get("authors") or [], type="dataset", doc_type="dataset",
                landing_url=x.get("url"), keywords=x.get("keywords") or [], is_oa=True,
                ids={"dataverse": x.get("global_id")}) for x in data.get("items") or []]
    tot = data.get("total_count") or 0
    return recs, (str(start + 100) if recs and start + 100 < tot else None), tot


def fetch_dryad(query, cursor, since, ctx):
    pg = int(cursor or 1)
    d = get_json("https://datadryad.org/api/v2/search", params={"q": _q(query), "per_page": 100, "page": pg}, tries=5)
    recs = []
    for x in (d.get("_embedded") or {}).get("stash:datasets") or []:
        y = _int_year(x.get("publicationDate"))
        if since and y and str(x.get("publicationDate") or "") < since:
            continue
        detail = [{"name": " ".join(v for v in (a.get("firstName"), a.get("lastName")) if v), "orcid": _orcid(a.get("orcid")),
                   "institutions": [a["affiliation"]] if a.get("affiliation") else []} for a in x.get("authors") or []]
        rel = [w.get("identifier") for w in x.get("relatedWorks") or [] if w.get("relationship") == "primary_article"]
        recs.append(rec(doi=(x.get("identifier") or "").replace("doi:", ""), title=x.get("title"), abstract=x.get("abstract"),
                        year=y, publisher="Dryad", authors=[a["name"] for a in detail], authors_detail=detail,
                        type="dataset", doc_type="dataset", license=x.get("license"), is_oa=True,
                        landing_url=f"https://datadryad.org/stash/dataset/{x.get('identifier')}",
                        keywords=x.get("keywords") or [], ids={"dryad": x.get("id")}, supplement_to=rel or None))
    tot = d.get("total") or 0
    return recs, (str(pg + 1) if (d.get("_embedded") or {}).get("stash:datasets") and pg * 100 < tot else None), tot


def fetch_mcloud(query, cursor, since, ctx):
    """Materials Cloud Archive (computational materials science / catalysis datasets)."""
    pg = int(cursor or 1)
    q = _q(query)
    if since:
        q = f"({q}) AND publication_date:[{since} TO *]"
    d = get_json("https://archive.materialscloud.org/api/records", params={"q": q, "size": 100, "page": pg}, tries=5)
    hits = d.get("hits") or {}
    recs = []
    for h in hits.get("hits") or []:
        md = h.get("metadata") or {}
        detail = []
        for c in md.get("creators") or []:
            po = c.get("person_or_org") or {}
            orc = next((i.get("identifier") for i in po.get("identifiers") or [] if i.get("scheme") == "orcid"), None)
            detail.append({"name": po.get("name"), "orcid": _orcid(orc),
                           "institutions": [a.get("name") for a in c.get("affiliations") or [] if a.get("name")]})
        r0 = (md.get("rights") or [{}])[0] or {}
        recs.append(rec(doi=((h.get("pids") or {}).get("doi") or {}).get("identifier"), title=md.get("title"),
                        abstract=md.get("description"), year=_int_year(md.get("publication_date")),
                        publisher="Materials Cloud", authors=[a["name"] for a in detail], authors_detail=detail,
                        type="dataset", doc_type="dataset", license=r0.get("id") or (r0.get("props") or {}).get("url"),
                        license_raw=(r0.get("props") or {}).get("url") or r0.get("id"), is_oa=True,
                        landing_url=(h.get("links") or {}).get("self_html"), ids={"mcloud": h.get("id")},
                        keywords=[sj.get("subject") for sj in md.get("subjects") or [] if sj.get("subject")]))
    tot = (hits.get("total") or 0) if isinstance(hits.get("total"), int) else ((hits.get("total") or {}).get("value") or 0)
    return recs, (str(pg + 1) if recs and pg * 100 < min(tot, 10000) else None), tot


# ---------------------------------------------------------------- government / regional / domain
def fetch_ntrs(query, cursor, since, ctx):
    """NASA Technical Reports Server (NASA and NACA reports, conference papers, theses)."""
    start = int(cursor or 0)
    params = {"q": _q(query), "page.size": 100, "page.from": start}
    if since:
        params["published.gte"] = since
    d = get_json("https://ntrs.nasa.gov/api/citations/search", params=params, tries=5, timeout=(20, 120))
    recs = []
    for x in d.get("results") or []:
        pubs = x.get("publications") or []
        cp = x.get("copyright") or {}
        dl = next(((l.get("links") or {}).get("pdf") for l in x.get("downloads") or [] if (l.get("mimetype") or "") == "application/pdf"), None)
        public = (x.get("distribution") == "PUBLIC") and bool(x.get("downloadsAvailable"))
        recs.append(rec(title=x.get("title"), abstract=x.get("abstract"),
                        year=_int_year((pubs[0] if pubs else {}).get("publicationDate") or x.get("distributionDate")),
                        journal=(pubs[0] if pubs else {}).get("publicationName"), publisher="NASA",
                        authors=[((a.get("meta") or {}).get("author") or {}).get("name") for a in x.get("authorAffiliations") or []],
                        type=x.get("stiType"), is_oa=public or None,
                        license=("public-domain" if public and cp.get("belongsToUsGov") else None),
                        pdf_url=(f"https://ntrs.nasa.gov{dl}" if dl and public else None),
                        landing_url=f"https://ntrs.nasa.gov/citations/{x.get('id')}", ids={"ntrs": x.get("id")},
                        keywords=x.get("keywords") or [], key=f"ntrs:{x.get('id')}"))
    tot = (d.get("stats") or {}).get("total") or 0
    return recs, (str(start + 100) if recs and start + 100 < tot else None), tot


_JS_NS = {"a": "http://www.w3.org/2005/Atom", "prism": "http://prismstandard.org/namespaces/basic/2.0/",
          "os": "http://a9.com/-/spec/opensearch/1.1/"}


def _jstage_call(q, start, yfrom=None, yto=None):
    params = {"service": 3, "text": q, "count": 1000, "start": start}
    if yfrom:
        params["pubyearfrom"] = yfrom
    if yto:
        params["pubyearto"] = yto
    r = http_get("https://api.jstage.jst.go.jp/searchapi/do", params=params, tries=5, timeout=(20, 120))
    root = ET.fromstring(r.content)
    status = root.findtext("a:result/a:status", default="", namespaces=_JS_NS) or root.findtext("result/status", default="")
    return root, status


def fetch_jstage(query, cursor, since, ctx):
    """J-STAGE (Japanese journals and proceedings). The API answers WARN_002 when a query matches too much, so broad
    queries are walked one publication year at a time (cursor = 'year:start')."""
    q = _q(query)
    this_year = _dt.date.today().year
    first_year = int(since[:4]) if since else 1950
    if cursor and ":" in cursor:
        year, start = (int(x) for x in cursor.split(":"))
    else:
        root, status = _jstage_call(q, 1, first_year if since else None)
        if status != "WARN_002":
            return _jstage_parse(root), None, int(root.findtext("os:totalResults", default="0", namespaces=_JS_NS) or 0)
        year, start = this_year, 1
    root, status = _jstage_call(q, start, year, year)
    recs = [] if status == "WARN_002" else _jstage_parse(root)
    tot = int(root.findtext("os:totalResults", default="0", namespaces=_JS_NS) or 0)
    if recs and start + 1000 <= tot:
        nxt = f"{year}:{start + 1000}"
    else:
        nxt = f"{year - 1}:1" if year - 1 >= first_year else None
    return recs, nxt, None


def _jstage_parse(root):
    out = []
    for e in root.findall("a:entry", _JS_NS):
        def en(tag):
            node = e.find(f"a:{tag}/a:en", _JS_NS)
            txt = (node.text or "").strip() if node is not None else ""
            if not txt:
                node = e.find(f"a:{tag}/a:ja", _JS_NS)
                txt = (node.text or "").strip() if node is not None else ""
            return txt
        names = [n.text for n in e.findall("a:author/a:en/a:name", _JS_NS) if n.text] or \
                [n.text for n in e.findall("a:author/a:ja/a:name", _JS_NS) if n.text]
        out.append(rec(doi=e.findtext("prism:doi", default=None, namespaces=_JS_NS), title=en("article_title"),
                       year=_int_year(e.findtext("a:pubyear", default="", namespaces=_JS_NS)), journal=en("material_title"),
                       authors=names, landing_url=en("article_link"), is_oa=True,
                       ids={"jstage": e.findtext("a:cdjournal", default=None, namespaces=_JS_NS)}))
    return out


def fetch_cinii(query, cursor, since, ctx):
    """CiNii Research (Japanese research outputs incl. theses and KAKEN reports)."""
    start = int(cursor or 1)
    params = {"q": _q(query), "format": "json", "count": 200, "start": start}
    if since:
        params["from"] = since[:4]
    if ctx.get("keys", {}).get("cinii"):
        params["appid"] = ctx["keys"]["cinii"]
    d = get_json("https://cir.nii.ac.jp/opensearch/articles", params=params, tries=5, timeout=(20, 120))
    recs = []
    for it in d.get("items") or []:
        ids = it.get("dc:identifier") or []
        ids = ids if isinstance(ids, list) else [ids]
        doi = next((i.get("@value") for i in ids if isinstance(i, dict) and i.get("@type") == "cir:DOI"), None)
        recs.append(rec(doi=doi, title=it.get("title"), abstract=it.get("description"),
                        year=_int_year(it.get("prism:publicationDate")), journal=it.get("prism:publicationName"),
                        publisher=it.get("dc:publisher"), authors=it.get("dc:creator") or [], type=it.get("dc:type"),
                        landing_url=(it.get("link") or {}).get("@id"),
                        ids={"cinii": ((it.get("link") or {}).get("@id") or "").rsplit("/", 1)[-1] or None}))
    tot = int(d.get("opensearch:totalResults") or 0)
    return recs, (str(start + 200) if recs and start + 200 <= min(tot, 10000) else None), tot


def fetch_eric(query, cursor, since, ctx):
    """ERIC (chemistry / chemical-engineering education literature)."""
    start = int(cursor or 0)
    q = _q(query)
    if since:
        q = f"({q}) AND publicationdateyear:[{since[:4]} TO 3000]"
    params = {"search": q, "format": "json", "rows": 200, "start": start,
              "fields": "id,title,author,description,publicationdateyear,publicationtype,source,subject,url,e_fulltextauth,peerreviewed"}
    d = get_json("https://api.ies.ed.gov/eric/", params=params, tries=5)
    resp = d.get("response") or {}
    recs = []
    for x in resp.get("docs") or []:
        eid = x.get("id") or ""
        ft = f"https://files.eric.ed.gov/fulltext/{eid}.pdf" if x.get("e_fulltextauth") == 1 else None
        recs.append(rec(title=x.get("title"), abstract=x.get("description"), year=x.get("publicationdateyear"),
                        journal=x.get("source"), authors=x.get("author") or [], type=x.get("publicationtype"),
                        pdf_url=ft, is_oa=bool(ft) or None, landing_url=x.get("url") or f"https://eric.ed.gov/?id={eid}",
                        keywords=x.get("subject") or [], ids={"eric": eid}, key=f"eric:{eid}" if eid else None))
    tot = resp.get("numFound") or 0
    return recs, (str(start + 200) if recs and start + 200 < tot else None), tot


def fetch_europepmc_patents(query, cursor, since, ctx):
    q = _q(query)
    return fetch_europepmc(f"({q}) AND SRC:PAT", cursor, since, ctx)


def fetch_openaire_data(query, cursor, since, ctx):
    q = dict(query) if isinstance(query, dict) else {"q": query}
    q["search"] = q.get("q")
    q.setdefault("type", "dataset")
    return fetch_openaire(q, cursor, since, ctx)


# ---------------------------------------------------------------- databases that need a key (keys.txt)
def _need(ctx, name):
    k = ctx.get("keys", {}).get(name)
    if not k:
        raise HTTPFail("nokey", f"needs `{name}: <key>` in ~/.scale/sources/keys.txt")
    return k


def fetch_core(query, cursor, since, ctx):
    key = _need(ctx, "core")
    off = int(cursor or 0)
    q = _q(query)
    if since:
        q = f"({q}) AND yearPublished>={since[:4]}"
    d = get_json("https://api.core.ac.uk/v3/search/works", params={"q": q, "limit": 100, "offset": off},
                 headers={"Authorization": f"Bearer {key}"}, tries=5, timeout=(20, 180))
    recs = []
    for x in d.get("results") or []:
        recs.append(rec(doi=x.get("doi"), title=x.get("title"), abstract=x.get("abstract"), year=x.get("yearPublished"),
                        journal=((x.get("journals") or [{}])[0] or {}).get("title"), publisher=x.get("publisher"),
                        authors=[a.get("name") for a in x.get("authors") or []], type=x.get("documentType"),
                        pdf_url=x.get("downloadUrl") or None, is_oa=bool(x.get("downloadUrl")) or None,
                        landing_url=next((l.get("url") for l in x.get("links") or [] if l.get("type") == "display"), None),
                        ids={"core": x.get("id")}))
    tot = d.get("totalHits") or 0
    return recs, (str(off + 100) if recs and off + 100 < min(tot, 10000) else None), tot


def fetch_scopus(query, cursor, since, ctx):
    key = _need(ctx, "scopus")
    q = _q(query)
    if since:
        q = f"({q}) AND PUBYEAR > {int(since[:4]) - 1}"
    headers = {"X-ELS-APIKey": key, "Accept": "application/json"}
    if ctx.get("keys", {}).get("scopus_insttoken"):
        headers["X-ELS-Insttoken"] = ctx["keys"]["scopus_insttoken"]
    d = get_json("https://api.elsevier.com/content/search/scopus",
                 params={"query": q, "count": 200, "cursor": cursor or "*", "view": "STANDARD"},
                 headers=headers, tries=5, timeout=(20, 120))
    sr = d.get("search-results") or {}
    recs = []
    for e in sr.get("entry") or []:
        if e.get("error"):
            continue
        recs.append(rec(doi=e.get("prism:doi"), title=e.get("dc:title"), year=_int_year(e.get("prism:coverDate")),
                        journal=e.get("prism:publicationName"), authors=[e.get("dc:creator")] if e.get("dc:creator") else [],
                        type=e.get("subtypeDescription"), is_oa=(str(e.get("openaccessFlag")).lower() == "true") or None,
                        cited_by_count=int(e["citedby-count"]) if str(e.get("citedby-count") or "").isdigit() else None,
                        ids={"scopus": e.get("eid")}))
    nxt = ((sr.get("cursor") or {}).get("@next")) if recs else None
    return recs, nxt, int(sr.get("opensearch:totalResults") or 0)


def fetch_springer(query, cursor, since, ctx):
    key = _need(ctx, "springer")
    s = int(cursor or 1)
    q = _q(query)
    if since:
        q = f"({q}) onlinedatefrom:{since}"
    d = get_json("https://api.springernature.com/meta/v2/json", params={"q": q, "s": s, "p": 100, "api_key": key},
                 tries=5, timeout=(20, 120))
    recs = []
    for x in d.get("records") or []:
        ab = x.get("abstract")
        if isinstance(ab, dict):
            ab = " ".join(str(v) for v in ab.values() if isinstance(v, str))
        pdf = next((u.get("value") for u in x.get("url") or [] if u.get("format") == "pdf"), None)
        oa = str(x.get("openaccess")).lower() == "true"
        recs.append(rec(doi=x.get("doi"), title=x.get("title"), abstract=ab, year=_int_year(x.get("publicationDate")),
                        journal=x.get("publicationName"), publisher=x.get("publisher"),
                        authors=[c.get("creator") for c in x.get("creators") or [] if c.get("creator")],
                        type=x.get("contentType"), is_oa=oa or None, pdf_url=pdf if oa else None,
                        keywords=x.get("keyword") or []))
    tot = int(((d.get("result") or [{}])[0] or {}).get("total") or 0)
    return recs, (str(s + 100) if recs and s + 100 <= tot else None), tot


def fetch_wos(query, cursor, since, ctx):
    key = _need(ctx, "wos")
    pg = int(cursor or 1)
    q = _q(query)
    if since:
        q = f"({q}) AND PY=({since[:4]}-{_dt.date.today().year})"
    d = get_json("https://api.clarivate.com/apis/wos-starter/v1/documents",
                 params={"q": q, "limit": 50, "page": pg, "db": "WOS"}, headers={"X-ApiKey": key}, tries=5)
    recs = []
    for h in d.get("hits") or []:
        src, ids = h.get("source") or {}, h.get("identifiers") or {}
        cit = next((c.get("count") for c in h.get("citations") or [] if c.get("db") == "WOS"), None)
        recs.append(rec(doi=ids.get("doi"), title=h.get("title"), year=src.get("publishYear"), journal=src.get("sourceTitle"),
                        authors=[a.get("displayName") for a in (h.get("names") or {}).get("authors") or []],
                        type=",".join(h.get("types") or []), cited_by_count=cit, ids={"wos": h.get("uid")},
                        keywords=(h.get("keywords") or {}).get("authorKeywords") or []))
    tot = (d.get("metadata") or {}).get("total") or 0
    return recs, (str(pg + 1) if recs and pg * 50 < tot else None), tot


def _lens_query(q, since, date_field):
    base = {"query_string": {"query": q}}
    if since:
        return {"bool": {"must": base, "filter": {"range": {date_field: {"gte": since}}}}}
    return base


def fetch_lens(query, cursor, since, ctx):
    key = _need(ctx, "lens")
    body = {"scroll_id": cursor, "scroll": "2m"} if cursor else {
        "query": _lens_query(_q(query), since, "date_published"), "size": 100, "scroll": "2m",
        "include": ["lens_id", "title", "abstract", "authors", "year_published", "external_ids", "source",
                    "publication_type", "open_access", "keywords", "scholarly_citations_count"]}
    d = http_get("https://api.lens.org/scholarly/search", method="POST", json_body=body,
                 headers={"Authorization": f"Bearer {key}"}, tries=5, timeout=(20, 120)).json()
    recs = []
    for x in d.get("data") or []:
        doi = next((e.get("value") for e in x.get("external_ids") or [] if e.get("type") == "doi"), None)
        detail = []
        for a in x.get("authors") or []:
            nm = " ".join(v for v in (a.get("first_name"), a.get("last_name")) if v)
            orc = next((i.get("value") for i in a.get("ids") or [] if i.get("type") == "orcid"), None)
            detail.append({"name": nm, "orcid": _orcid(orc),
                           "institutions": [f.get("name") for f in a.get("affiliations") or [] if f.get("name")]})
        oa = x.get("open_access") or {}
        recs.append(rec(doi=doi, title=x.get("title"), abstract=x.get("abstract"), year=x.get("year_published"),
                        journal=(x.get("source") or {}).get("title"), publisher=(x.get("source") or {}).get("publisher"),
                        authors=[a["name"] for a in detail], authors_detail=detail, type=x.get("publication_type"),
                        is_oa=bool(oa.get("colour") and oa.get("colour") != "unknown") or None, license=oa.get("license"),
                        keywords=x.get("keywords") or [], cited_by_count=x.get("scholarly_citations_count"),
                        landing_url=f"https://www.lens.org/lens/scholar/article/{x.get('lens_id')}/main",
                        ids={"lens": x.get("lens_id")}))
    return recs, (d.get("scroll_id") if recs else None), d.get("total")


def _patent_rec(jur, num, kind, title, abstract, year, applicants, inventors, link, src_id, family=None, ptype=None):
    pn = "-".join(x for x in (jur, num, kind) if x)
    venue = f"{jur} patent" + (" application" if (ptype or "").upper().find("APPLICATION") >= 0 or (kind or "").startswith("A") and jur in ("US", "EP", "WO", "CN") else "")
    return rec(title=title, abstract=abstract, year=year, journal=venue, publisher="; ".join(applicants[:3]) or None,
               authors=inventors, type="patent", doc_type="patent", landing_url=link, is_oa=True,
               license="patent-document", ids={"patent": pn, **src_id, **({"patent_family": family} if family else {})},
               key=patent_key(jur, num))


def patent_key(jur, num):
    """'patent:EP1234567' — jurisdiction + number without the kind code, so an application (A1) and its grant (B1)
    found in different databases fall together."""
    return "patent:" + re.sub(r"[^A-Z0-9]", "", f"{jur or ''}{num or ''}".upper())


def fetch_lens_patents(query, cursor, since, ctx):
    key = _need(ctx, "lens")
    body = {"scroll_id": cursor, "scroll": "2m"} if cursor else {
        "query": _lens_query(_q(query), since, "date_published"), "size": 100, "scroll": "2m",
        "include": ["lens_id", "jurisdiction", "doc_number", "kind", "date_published", "biblio.invention_title",
                    "abstract", "biblio.parties.applicants", "biblio.parties.inventors", "families.simple_family.id",
                    "publication_type"]}
    d = http_get("https://api.lens.org/patent/search", method="POST", json_body=body,
                 headers={"Authorization": f"Bearer {key}"}, tries=5, timeout=(20, 120)).json()

    def pick(items):
        items = items or []
        en = [i.get("text") for i in items if (i.get("lang") or "").lower() == "en" and i.get("text")]
        return en[0] if en else next((i.get("text") for i in items if i.get("text")), None)
    recs = []
    for x in d.get("data") or []:
        b = x.get("biblio") or {}
        parties = b.get("parties") or {}
        apps = [((a.get("extracted_name") or {}).get("value")) for a in parties.get("applicants") or []]
        invs = [((a.get("extracted_name") or {}).get("value")) for a in parties.get("inventors") or []]
        recs.append(_patent_rec(x.get("jurisdiction"), x.get("doc_number"), x.get("kind"), pick(b.get("invention_title")),
                                pick(x.get("abstract")), _int_year(x.get("date_published")), [a for a in apps if a],
                                [i for i in invs if i], f"https://www.lens.org/lens/patent/{x.get('lens_id')}",
                                {"lens": x.get("lens_id")}, ((x.get("families") or {}).get("simple_family") or {}).get("id"),
                                x.get("publication_type")))
    return recs, (d.get("scroll_id") if recs else None), d.get("total")


def fetch_ieee(query, cursor, since, ctx):
    key = _need(ctx, "ieee")
    start = int(cursor or 1)
    params = {"querytext": _q(query), "apikey": key, "max_records": 200, "start_record": start, "format": "json"}
    if since:
        params["start_year"] = since[:4]
    d = get_json("https://ieeexploreapi.ieee.org/api/v1/search/articles", params=params, tries=5)
    recs = []
    for a in d.get("articles") or []:
        oa = (a.get("access_type") or "").upper() == "OPEN_ACCESS"
        recs.append(rec(doi=a.get("doi"), title=a.get("title"), abstract=a.get("abstract"), year=a.get("publication_year"),
                        journal=a.get("publication_title"), publisher=a.get("publisher"),
                        authors=[x.get("full_name") for x in (a.get("authors") or {}).get("authors") or []],
                        type=a.get("content_type"), is_oa=oa or None, pdf_url=a.get("pdf_url") if oa else None,
                        landing_url=a.get("html_url"), cited_by_count=a.get("citing_source_count"),
                        keywords=((a.get("index_terms") or {}).get("author_terms") or {}).get("terms") or [],
                        ids={"ieee": a.get("article_number")}))
    tot = d.get("total_records") or 0
    return recs, (str(start + 200) if recs and start + 200 <= tot else None), tot


def fetch_ads(query, cursor, since, ctx):
    key = _need(ctx, "ads")
    start = int(cursor or 0)
    q = _q(query)
    if since:
        q = f"({q}) pubdate:[{since[:7]} TO 9999-12]"
    d = get_json("https://api.adsabs.harvard.edu/v1/search/query",
                 params={"q": q, "fl": "bibcode,doi,title,abstract,author,year,pub,doctype,property,citation_count,keyword",
                         "rows": 200, "start": start}, headers={"Authorization": f"Bearer {key}"}, tries=5)
    resp = d.get("response") or {}
    recs = []
    for x in resp.get("docs") or []:
        props = x.get("property") or []
        recs.append(rec(doi=(x.get("doi") or [None])[0], title=(x.get("title") or [""])[0], abstract=x.get("abstract"),
                        year=_int_year(x.get("year")), journal=x.get("pub"), authors=x.get("author") or [],
                        type=x.get("doctype"), is_oa=("OPENACCESS" in props) or None,
                        cited_by_count=x.get("citation_count"), keywords=x.get("keyword") or [],
                        landing_url=f"https://ui.adsabs.harvard.edu/abs/{x.get('bibcode')}", ids={"ads": x.get("bibcode")},
                        is_preprint=(x.get("doctype") == "eprint")))
    tot = resp.get("numFound") or 0
    return recs, (str(start + 200) if recs and start + 200 < tot else None), tot


_EPO_TOKEN = {"token": None, "exp": 0}


def _epo_token(ctx):
    import base64
    import time as _t
    k, s = _need(ctx, "epo_key"), _need(ctx, "epo_secret")
    if _EPO_TOKEN["token"] and _t.time() < _EPO_TOKEN["exp"] - 60:
        return _EPO_TOKEN["token"]
    auth = base64.b64encode(f"{k}:{s}".encode()).decode()
    r = http_get("https://ops.epo.org/3.2/auth/accesstoken", method="POST",
                 headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
                 params={"grant_type": "client_credentials"}, tries=3)
    d = r.json()
    _EPO_TOKEN.update(token=d.get("access_token"), exp=_t.time() + int(d.get("expires_in") or 1200))
    return _EPO_TOKEN["token"]


def fetch_epo(query, cursor, since, ctx):
    """EPO Open Patent Services (EP, WO and worldwide DOCDB bibliographic data). Queries use CQL, e.g.
    ta="carbon dioxide" and ta=electroreduction. OPS returns at most 2,000 results per query."""
    tok = _epo_token(ctx)
    start = int(cursor or 1)
    q = _q(query)
    if since:
        q = f"({q}) and pd>={since.replace('-', '')}"
    r = http_get("https://ops.epo.org/3.2/rest-services/published-data/search/biblio", params={"q": q},
                 headers={"Authorization": f"Bearer {tok}", "Accept": "application/json",
                          "X-OPS-Range": f"{start}-{start + 99}"}, tries=4, timeout=(20, 120))
    d = r.json().get("ops:world-patent-data", {}).get("ops:biblio-search", {})
    tot = int(d.get("@total-result-count") or 0)
    docs = ((d.get("ops:search-result") or {}).get("exchange-documents")) or []
    docs = docs if isinstance(docs, list) else [docs]

    def txt(x):
        if isinstance(x, list):
            en = [i for i in x if isinstance(i, dict) and i.get("@lang") == "en"]
            x = (en or x)[0] if x else {}
        return (x or {}).get("$") if isinstance(x, dict) else (x if isinstance(x, str) else None)
    recs = []
    for doc in docs:
        e = doc.get("exchange-document") or {}
        b = e.get("bibliographic-data") or {}
        parties = b.get("parties") or {}

        def names(block, tag):
            items = (parties.get(block) or {}).get(tag) or []
            items = items if isinstance(items, list) else [items]
            out = []
            for it in items:
                if (it.get("@data-format") or "") != "epodoc":
                    nm = txt((it.get(f"{tag}-name") or {}).get("name"))
                    if nm:
                        out.append(nm.strip(", "))
            return out
        ab = e.get("abstract")
        ab = ab if isinstance(ab, list) else [ab] if ab else []
        abstract = next((txt(a.get("p")) for a in ab if a.get("@lang") == "en"), None) or (txt(ab[0].get("p")) if ab else None)
        pubref = (b.get("publication-reference") or {}).get("document-id") or []
        pubref = pubref if isinstance(pubref, list) else [pubref]
        date = next((txt(p.get("date")) for p in pubref if p.get("@document-id-type") == "docdb"), None)
        jur, num, kind = e.get("@country"), e.get("@doc-number"), e.get("@kind")
        recs.append(_patent_rec(jur, num, kind, txt(b.get("invention-title")), abstract, _int_year(date),
                                names("applicants", "applicant"), names("inventors", "inventor"),
                                f"https://worldwide.espacenet.com/patent/search?q=pn%3D{jur}{num}{kind}", {"epo": f"{jur}{num}{kind}"},
                                e.get("@family-id")))
    nxt = str(start + 100) if recs and start + 100 <= min(tot, 2000) else None
    return recs, nxt, tot


# ---------------------------------------------------------------- registry
FETCHERS = {"openalex": fetch_openalex, "crossref": fetch_crossref, "crossref_preprints": fetch_crossref_preprints,
            "s2": fetch_s2, "europepmc": fetch_europepmc, "europepmc_patents": fetch_europepmc_patents,
            "openaire": fetch_openaire, "openaire_data": fetch_openaire_data, "osti": fetch_osti, "arxiv": fetch_arxiv,
            "doaj": fetch_doaj, "hal": fetch_hal, "zenodo": fetch_zenodo, "pmc": fetch_pmc, "figshare": fetch_figshare,
            "osf": fetch_osf, "plos": fetch_plos, "datacite": fetch_datacite, "dataverse": fetch_dataverse,
            "dryad": fetch_dryad, "mcloud": fetch_mcloud, "ntrs": fetch_ntrs, "jstage": fetch_jstage, "cinii": fetch_cinii,
            "eric": fetch_eric, "core": fetch_core, "scopus": fetch_scopus, "springer": fetch_springer, "wos": fetch_wos,
            "lens": fetch_lens, "lens_patents": fetch_lens_patents, "ieee": fetch_ieee, "ads": fetch_ads, "epo": fetch_epo,
            "citations": fetch_openalex}

# Every database the skill knows. status: auto (keyless) | key (needs the named keys in keys.txt) | covered (found through
# another database) | excluded (not queried, with the reason). default: queried for a new topic unless deselected.
CATALOG = {
    # broad aggregators
    "openalex": dict(status="auto", group="aggregator", default=True, optional_key="openalex",
                     covers="~250M works; citations, OA locations, institutions; filter syntax"),
    "crossref": dict(status="auto", group="aggregator", default=True, optional_key="crossref",
                     covers="every Crossref DOI; publisher-deposited licenses; relevance-ranked (loose)"),
    "s2": dict(status="auto", group="aggregator", default=True, optional_key="s2",
               covers="Semantic Scholar ~200M sources; strong CS/physics coverage; slow without a key"),
    "openaire": dict(status="auto", group="aggregator", default=True,
                     covers="OpenAIRE Graph: EU repositories, funder links, theses"),
    "core": dict(status="key", group="aggregator", default=True, keys=["core"],
                 covers="CORE ~300M OA records from repositories, full-text search"),
    "lens": dict(status="key", group="aggregator", default=True, keys=["lens"],
                 covers="Lens.org scholarly works (Microsoft Academic heritage + Crossref + PubMed)"),
    "scopus": dict(status="key", group="index", default=True, keys=["scopus"],
                   covers="Elsevier Scopus abstract & citation index (key + institutional entitlement)"),
    "wos": dict(status="key", group="index", default=True, keys=["wos"],
                covers="Web of Science Starter API (key; institutional subscription)"),
    "springer": dict(status="key", group="publisher", default=True, keys=["springer"],
                     covers="Springer Nature metadata incl. Nature, BMC, SpringerOpen"),
    "ieee": dict(status="key", group="publisher", default=True, keys=["ieee"],
                 covers="IEEE Xplore (electrochemical energy, sensors, power-to-X engineering)"),
    # repositories and preprints
    "europepmc": dict(status="auto", group="repository", default=True,
                      covers="Europe PMC: PubMed, PMC, preprints (bioRxiv, ChemRxiv, Research Square ...), theses"),
    "pmc": dict(status="auto", group="repository", default=True, optional_key="ncbi", covers="PubMed Central full-text OA"),
    "arxiv": dict(status="auto", group="preprint", default=True,
                  covers="arXiv (cond-mat, physics.chem-ph, materials); paced 1 request / 3 s"),
    "crossref_preprints": dict(status="auto", group="preprint", default=True,
                               covers="preprint servers registered in Crossref: ChemRxiv, Research Square, SSRN, "
                                      "Preprints.org, bioRxiv, medRxiv, TechRxiv, EngrXiv, Authorea, ESS Open Archive"),
    "osf": dict(status="auto", group="preprint", default=True, covers="OSF Preprints (title search): EngrXiv legacy, "
                                                                        "SocArXiv, PsyArXiv and other OSF servers"),
    "hal": dict(status="auto", group="repository", default=True, covers="HAL (French open archive)"),
    "zenodo": dict(status="auto", group="repository", default=True, optional_key="zenodo",
                   covers="Zenodo publications (and datasets with {\"type\": \"dataset\"})"),
    "figshare": dict(status="auto", group="repository", default=True,
                     covers="Figshare articles; publisher SI files are attached to their source, not listed"),
    "doaj": dict(status="auto", group="publisher", default=True,
                 covers="DOAJ fully-OA journals (MDPI, Frontiers, Hindawi, SAGE Open, RSC Advances ...)"),
    "plos": dict(status="auto", group="publisher", default=True, covers="PLOS journals"),
    "osti": dict(status="auto", group="government", default=True,
                 covers="OSTI.GOV: US DOE reports, journal articles, theses, patents (catalysis-heavy)"),
    "ntrs": dict(status="auto", group="government", default=True,
                 covers="NASA Technical Reports Server (CO2 electrolysis, ISRU, life support)"),
    "ads": dict(status="key", group="domain", default=True, keys=["ads"],
                covers="NASA ADS (physics, planetary/ISRU catalysis)"),
    # regional
    "jstage": dict(status="auto", group="regional", default=True, covers="J-STAGE: Japanese journals and proceedings"),
    "cinii": dict(status="auto", group="regional", default=True, optional_key="cinii",
                  covers="CiNii Research: Japanese articles, theses, KAKEN reports"),
    # datasets
    "datacite": dict(status="auto", group="dataset", default=True,
                     covers="DataCite DOIs: datasets, theses, reports, preprints from Zenodo, Dryad, institutional "
                            "repositories, Mendeley Data ..."),
    "openaire_data": dict(status="auto", group="dataset", default=True, covers="OpenAIRE research datasets"),
    "dataverse": dict(status="auto", group="dataset", default=True, covers="Harvard Dataverse datasets"),
    "dryad": dict(status="auto", group="dataset", default=True, covers="Dryad datasets (often linked to a paper)"),
    "mcloud": dict(status="auto", group="dataset", default=True,
                   covers="Materials Cloud Archive (DFT / computational catalysis datasets)"),
    # patents
    "europepmc_patents": dict(status="auto", group="patent", default=True,
                              covers="EPO patent abstracts indexed by Europe PMC (biocatalysis-leaning, keyless)"),
    "lens_patents": dict(status="key", group="patent", default=True, keys=["lens"],
                         covers="Lens.org patents: 150M+ records, 100+ jurisdictions"),
    "epo": dict(status="key", group="patent", default=True, keys=["epo_key", "epo_secret"],
                covers="EPO Open Patent Services (EP, WO, worldwide DOCDB); CQL queries"),
    "citations": dict(status="auto", group="citation", default=False,
                      covers="forward citation chasing through OpenAlex (search.py --citing); not a query database"),
    # education (off by default)
    "eric": dict(status="auto", group="domain", default=False, covers="ERIC: chemistry-education literature"),
    # found through another database
    "chemrxiv": dict(status="covered", via="crossref_preprints, europepmc, s2",
                     reason="ChemRxiv's own API sits behind a Cloudflare challenge; its DOIs (10.26434) are in Crossref"),
    "biorxiv": dict(status="covered", via="crossref_preprints, europepmc", reason="the bioRxiv/medRxiv API lists by date only"),
    "medrxiv": dict(status="covered", via="crossref_preprints, europepmc", reason="same API as bioRxiv"),
    "research_square": dict(status="covered", via="crossref_preprints, europepmc", reason="no search API; DOIs 10.21203"),
    "ssrn": dict(status="covered", via="crossref_preprints", reason="no search API; DOIs 10.2139"),
    "engrxiv": dict(status="covered", via="crossref_preprints, osf", reason="DOIs 10.31224 in Crossref"),
    "essoar": dict(status="covered", via="crossref_preprints", reason="now ESS Open Archive on Authorea (10.22541)"),
    "techrxiv": dict(status="covered", via="crossref_preprints", reason="DOIs 10.36227 in Crossref"),
    "preprints_org": dict(status="covered", via="crossref_preprints", reason="DOIs 10.20944 in Crossref"),
    "socarxiv": dict(status="covered", via="osf", reason="hosted on OSF"),
    "psyarxiv": dict(status="covered", via="osf", reason="hosted on OSF (out of domain)"),
    "pubmed": dict(status="covered", via="europepmc", reason="Europe PMC indexes all of PubMed"),
    "unpaywall": dict(status="covered", via="classify_access.py",
                      reason="not a search engine: every DOI is looked up there for access type and license"),
    "publisher_oa": dict(status="covered", via="crossref, openalex, doaj",
                         reason="BMC, Elsevier OA, Frontiers, Hindawi, MDPI, SAGE Open, SpringerOpen and Wiley OA have no "
                                "search APIs; their sources are indexed through Crossref/OpenAlex/DOAJ and downloaded from "
                                "their CDNs"),
    "jstor_open": dict(status="covered", via="crossref", reason="no public search API"),
    "scielo": dict(status="covered", via="crossref, openalex, doaj", reason="search.scielo.org is behind a bot challenge"),
    "citeseerx": dict(status="covered", via="s2, openalex", reason="service offline (redirects to the Wayback Machine)"),
    "catalysis_hub": dict(status="covered", via="openalex, crossref",
                          reason="its GraphQL endpoint did not answer (2026-10); its datasets cite journal papers"),
    "nomad": dict(status="covered", via="datacite", reason="computational data entries, not literature"),
    "custom_url": dict(status="covered", via="import_list.py --url",
                       reason="a journal TOC, lab page or reference list is imported by DOI extraction"),
    # deliberately not queried
    "base": dict(status="excluded", reason="BASE answers only IP-registered clients (ask Bielefeld UB to register the "
                                           "institution's IP, then it can be wired)"),
    "dimensions": dict(status="excluded", reason="needs an institutional Dimensions API subscription"),
    "dblp": dict(status="excluded", reason="bot wall (Anubis) on the API; CS venues are covered by S2/OpenAlex"),
    "ia_scholar": dict(status="excluded", reason="scholar.archive.org answers scripted clients with a verification "
                                                 "page; the Wayback Machine is used for dead OA links instead"),
    "google_scholar": dict(status="excluded", reason="no API and its terms forbid scraping"),
    "google_patents": dict(status="excluded", reason="no official API (BigQuery needs a Google Cloud project); "
                                                     "patents come from Lens, EPO and Europe PMC"),
    "wipo_patentscope": dict(status="excluded", reason="no free API"),
    "patentsview": dict(status="excluded", reason="search.patentsview.org no longer resolves (2026-10); US patents "
                                                  "come from Lens/EPO, US patent PDFs from the USPTO image server"),
    "researchgate": dict(status="excluded", reason="terms forbid scraping; uploads there are often unlicensed"),
    "academia_edu": dict(status="excluded", reason="terms forbid scraping; uploads there are often unlicensed"),
    "scifinder_reaxys": dict(status="excluded", reason="subscription platforms whose terms forbid bulk export"),
    "cnki_wanfang": dict(status="excluded", reason="subscription platforms without a public API"),
    "proquest": dict(status="excluded", reason="subscription; theses are partly covered by OpenAIRE, DataCite, HAL, CORE"),
    "repec": dict(status="excluded", reason="economics only; no API"),
    "shadow_libraries": dict(status="excluded", reason="Sci-Hub, LibGen and similar pirate sites are never used"),
}
NOT_AUTOMATED = {k: v["reason"] for k, v in CATALOG.items() if v["status"] in ("excluded", "covered")}


def keys_needed(src):
    return CATALOG.get(src, {}).get("keys") or []


def default_databases(keys=None):
    """Databases queried for a new topic: every keyless default plus the key databases whose keys are present."""
    keys = keys or {}
    out = []
    for k, v in CATALOG.items():
        if k in FETCHERS and v.get("default"):
            if v["status"] == "auto" or all(keys.get(n) for n in keys_needed(k)):
                out.append(k)
    return out


def iso_or_none(s):
    if not s:
        return None
    _dt.date.fromisoformat(s)  # raises on a bad date
    return s
