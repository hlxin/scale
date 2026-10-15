# Troubleshooting (symptom → cause → fix)

| Symptom | Cause | Fix |
|---|---|---|
| `--count-only` shows hundreds of thousands of Crossref / Zenodo / DataCite hits | relevance-ranked sources match any word | expected; read `estimated_on_topic_per_source` (loose sources = page-1 lower bound); the full search stops each loose query by itself at the relevance tail |
| `build_list` reports `off_topic_dropped_by_gate` ≈ all raw records and few papers | gate too strict (missing synonyms/acronyms) | add terms to the gate groups, re-run `build_list.py` (no new search) |
| index full of unrelated papers | gate empty or too loose | tighten `all_groups`, re-run `build_list.py`; papers already in the ledger stay — screen them out or ask the user |
| `init_topic --check`: "must be a filter" for OpenAlex | OpenAlex queries are filter expressions | write `title_and_abstract.search:<words>` |
| `keys.py`: `WARNING: 'opendalex' ... is not a key name any source reads — did you mean 'openalex'?` | a typo in the service name: the key is ignored and the source runs without it | ask the user to rename it in keys.txt (keep the key itself) |
| `openalex: budget reserve reached (usd_left=...)` | the free daily budget ($1 with a key) and any prepaid credit are spent | re-run after 00:00 UTC, or the user adds prepaid credit at openalex.org; prepaid credit is spent automatically after the free budget |
| `openalex ...: 429-quota Insufficient budget ... shared by everyone on your network` | without a key OpenAlex uses one small daily budget per IP address (a campus network uses it up fast) | ask the user to add a free key: `openalex: <key>` in `~/.paper-acquisition/keys.txt` (README); or re-run after 00:00 UTC |
| classify_access: `unpaywall: daily cap reached` / `"complete": false` | Unpaywall gets at most 90,000 calls per UTC day on this machine (it asks for under 100,000); OpenAlex has a daily budget | expected on large topics: the pending papers keep an empty access type; re-run classify_access after 00:00 UTC; an OpenAlex key (`openalex: <key>`) makes OpenAlex answer most DOIs so Unpaywall is rarely needed. Never raise `UNPAYWALL_DAILY_CAP` or run two classify jobs to get around it |
| `openalex ...: OpenAlex without an API key returns at most 10,000 results per query` (or HTTP 401 "API key required for cursor paging") | without a key OpenAlex only pages with page=, up to 10,000 results per query; cursor paging needs a free key | ask the user to add `openalex: <key>` to `~/.paper-acquisition/keys.txt` (README), then re-run search.py: the query resumes. Never split queries just to get around the limit |
| a script dies without a Python error on a huge topic (millions of raw hits) | killed for lack of memory | `build_list.py --batches N` (N ≈ raw hits / 1,000,000); classify_access, screen (keywords / none / prep), status, topics, dedup, download and the exports work in blocks; download per subtopic (SKILL.md "Very large topics") |
| every step on a catalog ends with minutes of "export" | the index CSVs and papers.db of millions of rows are rewritten | chain the steps with `--no-export` and run `export.py --topic <slug>` once at the end |
| merged.csv does not open fully in Excel | Excel stops at 1,048,576 rows | open papers.db in DB Browser for SQLite, or a filtered `export.py` list |
| abstracts start with "Abstract", patents of one invention on several rows, SI deposits listed as papers | index built by an older skill version | once: `repair.py`, `dedup.py --apply`, `build_list.py --topic <slug> --si-links-only`, `topics.py assign --topic <slug>` |
| `s2 ...: 429 — waiting` lines for a long time, or `semantic scholar: not used for N papers without a key` | the anonymous Semantic Scholar pool is shared and often refuses every request | a topic over 20,000 papers is classified without it; its abstracts can come later with `classify_access.py --abstracts-only`; a free `s2: <key>` makes it part of every run |
| `<source>: skipped — needs ...` | a keyed source is selected but its key is missing | expected; tell the user which key enables it (`keys.py`); never ask for the key in chat |
| `keys.py --test`: `rejected — check the key` | wrong or expired key, or (Scopus/WoS) off campus | fix the line in keys.txt; Scopus/WoS need the campus network, VPN or `scopus_insttoken` |
| J-STAGE query returns nothing for a broad word | the API refuses result sets above its limit (WARN_002) | handled: the fetcher walks one publication year at a time |
| `search.py` JSON has `pending_queries` | a source failed mid-way (network, 5xx) | re-run the same command; cursors resume |
| Many `Open copy only on a site that blocks scripted downloads` | Wiley, RSC, ACS, Elsevier, MDPI-www, T&F, AIP ... answer scripts with bot challenges | expected; with verified EZproxy access `download_open.py` queues them for the runner |
| `No downloadable open copy found` | metadata lists no reachable PDF | retry later with `--retry-failed` (repositories add accepted manuscripts after embargoes) |
| `title_match=0.2 ... kept at .scripts/rejected/wrong_paper/` in the attempt log | the URL served a different paper | nothing to do; the next copy is tried; files are kept for review |
| check: `EZproxy asked for a login` | machine is off campus / VPN disconnected | connect the VPN, re-run the check; the scripts never log in |
| runner log: `publisher aip blocked ...; cooling down 60 min` | publisher refused the automated pattern | automatic; do not retry faster |
| runner: `HARD STOP: EZproxy usage-limit / suspension page` | the library proxy flagged the traffic | stop; show the user `_ezlimit.py status` and `.scripts/logs/ezproxy_evidence/`; clear only after the user confirms |
| `another EZproxy process holds the lock` | a runner is already running on this machine | fine — it serves every project's queue; check `pgrep -f download_paywalled.py` |
| `paywalled access not set up` (runner exits 3) | no verified EZproxy config | run `check_paywalled_access.py` first |
| a value typed into an index CSV or papers.db disappeared | both are rebuilt from the ledger by every step | record it through a script: `export.py --set-extracted ...`, `topics.py set ...` |
| papers.db looks out of date | a step ran with `db=False` (progress refresh during downloads) | `export.py` rebuilds it |
| many in-scope papers without an abstract | the sources had none (often Elsevier, older papers) | after download offer `fill_abstracts.py`; data-curation also copies abstracts from the PDFs it reads |
| Titles from old runs show `CO 2`, `Fe 2 O 3` | subscripts flattened to spaces upstream | the cleaner rejoins formulas on import; re-run `build_list.py` |
| `ModuleNotFoundError: fitz` / `pypdf` / `requests` | missing packages | `pip install pymupdf pypdf requests` |
| screen `merge` reports `unparsed_items` | a judge skipped or mangled lines | they stay unscreened; the next `prep` re-batches them |
