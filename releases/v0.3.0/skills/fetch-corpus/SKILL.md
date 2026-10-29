---
name: fetch-corpus
description: Fetches the files of a frozen corpus - each included source's PDF and supplementary information (SI) - into the index-sources project, open routes first and paywalled sources only through the library's EZproxy at safe rates, checks each PDF against its title and licence, and records in the corpus manifest which files it got and why the others are missing. Use whenever the user wants the PDFs or SI of sources, a corpus downloaded, or a fetch resumed; the corpus comes from index-sources (freeze_corpus.py), and curate-corpus curates what is fetched.
allowed-tools:
  - Bash(python3 -I ${CLAUDE_SKILL_DIR}/scripts/*)
  - Bash(nohup python3 -I ${CLAUDE_SKILL_DIR}/scripts/*)
  - Bash(nohup zsh ${CLAUDE_SKILL_DIR}/scripts/run_paywalled.sh *)
  - "scale corpus check <manifest>"     # SCALE checks the settled corpus
version: 1.0.0
scale_release: ">v0.2.0"
inputs:
  - A frozen corpus (sources/<topic>/corpora/<name>/sources.json, from index-sources' freeze_corpus.py), or a whole topic
  - The access types to fetch (OA, OA+ND, Free-to-read, Paywalled)
  - For paywalled sources, the library's EZproxy host, from the campus network or VPN
outputs:
  - The included sources' PDFs and SI in sources/<topic>/files/<access>/ (SI in files/SI/<access>/), each with its licence decision in the index
  - The corpus manifest settled - each included source with its pdf and si paths, or not_retrieved with the reason - and fetched_at
validation:
  - Every fetched PDF passed the same-source title check and carries the licence printed in it
  - "`settle_corpus.py` accounts for every included source: a file, or the reason there is none"
  - "`scale corpus check <manifest>` reports ok after the settle"
  - No paywalled source was fetched except through the library EZproxy within the limiter's caps; no login, CAPTCHA or pirate site was used
human-review:
  - Before anything is fetched (the numbers per access type, hours and GB), and before paywalled fetching starts
  - Whenever the EZproxy limiter records a hard stop (a person clears it after looking)
---

# Fetch corpus

The middle of the chain:

> [index-sources](../index-sources/SKILL.md) (index a topic, freeze a corpus) → **fetch-corpus** (the corpus's files) →
> [curate-corpus](../curate-corpus/SKILL.md) (scale-catal documents)

A corpus is frozen by index-sources: `freeze_corpus.py` picks its sources by a rule and writes the manifest
`sources/<topic>/corpora/<name>/sources.json`. This skill fetches the files of the sources it includes and settles the
manifest. It works in index-sources' project (the same `sources/index.db` and working ledger) and uses its scripts as
a library: keep the two skills side by side (`skills/index-sources` and `skills/fetch-corpus`, or as `scale skills
install` copies them). No corpus yet → index-sources first (its "Freeze a corpus" section).

## Standing rules

- **English only** with the user, in every message.
- **Only what the corpus includes.** Every step takes `--corpus <manifest>`; nothing outside it is fetched. A whole
  topic (`--topic <slug>`) only when the user asks for one.
- **Ask before fetching.** Show the numbers first (gate below); the user chooses the access types.
- **Scripts do the exact work.** Downloads, PDF checks, licence decisions and folder routing are the scripts'. Never
  move or rename PDFs by hand, never write replacement code — read a script's error, fix the input, re-run. Scripts
  print one JSON line on stdout and progress on stderr, and resume where they stopped.
- **Paywalled access is sanctioned access only:** campus network / VPN through the library's EZproxy. Never log in
  or type credentials, never solve or bypass a CAPTCHA, never use pirate sites (Sci-Hub, LibGen …). Never start a
  second EZproxy process, never change the limits in `scripts/_ezlimit.py`, never clear a hard stop without the
  user — the institution's rate limits must never be exceeded ([references/paywalled.md](references/paywalled.md)).
- **Nothing is deleted.** Wrong or duplicate files move under `.scripts/`.
- Run every command from the **project root** (the folder that holds `sources/` and `.scripts/`). A bare script name
  means `python3 -I ${CLAUDE_SKILL_DIR}/scripts/<name>`.

## Fetch — copy this checklist and tick it off

```
- [ ] GATE: the corpus's numbers; ask what to fetch
- [ ] open routes                  download_open.py --corpus <manifest> [--access ...] [--max N]
- [ ] paywalled (if chosen)        check_paywalled_access.py -> run_paywalled.sh --corpus <manifest>
- [ ] supplementary information    fetch_si.py --corpus <manifest>   (the SI the index lists, then the source page's)
- [ ] settle                       settle_corpus.py --corpus <manifest> ; scale corpus check <manifest>
- [ ] abstracts from PDFs (if chosen)   index-sources' fill_abstracts.py
- [ ] report
```

**Gate.** From the manifest and `status.py --topic <topic>` (index-sources): the included sources by access type,
those already on disk, and the estimate (open: hours and GB; paywalled: days at the limits, about 120 sources per
publisher per day). `AskUserQuestion` (`multiSelect`): which access types to fetch — OA (CC BY / BY-SA / BY-NC /
BY-NC-SA / CC0) · OA+ND (CC BY-ND / BY-NC-ND) · Free-to-read (readable, no reuse licence) · Paywalled (library EZproxy;
campus/VPN; slow). "Open access" = OA + OA+ND. Then: Everything chosen (Recommended) · Only the N most relevant (they
type N); and "Fill missing abstracts from the fetched PDFs?" (Yes · No) when sources lack abstracts. Paywalled chosen
→ "Are you on the campus network or connected to the VPN?" (Yes · No, skip paywalled · Not sure, test it).

**Open routes** (background for more than a few hundred sources):

```bash
nohup python3 -I ${CLAUDE_SKILL_DIR}/scripts/download_open.py --corpus <manifest> --access OA,OA+ND [--max N] \
  > .scripts/<topic>/download_open.log 2>&1 &
```

Every known open copy is tried, most open first (repositories, the PMC open-data mirror, arXiv, publisher CDNs, the
landing page's PDF link), never hosts that block scripted clients. Each PDF is validated, checked against the
source's title, and filed by the licence printed in it. Datasets and software are never downloaded; US patents come
from the USPTO image server. A source in two topics is fetched once (the copy in the other topic's folder is a
clone).

**Paywalled** (only if chosen; details [references/paywalled.md](references/paywalled.md)):
`check_paywalled_access.py --topic <topic> [--host <ezproxy host>]`. `"access": true` → re-run `download_open.py
--corpus <manifest>` once (it queues the corpus's paywalled sources and open ones that only sit on bot-protected
sites), check `_ezlimit.py status` (a hard stop needs the user's review — show it and stop), then start the single
machine-wide runner if it is not running:

```bash
nohup zsh ${CLAUDE_SKILL_DIR}/scripts/run_paywalled.sh "$PWD" --corpus <manifest> > /dev/null 2>&1 &
```

`"access": false` → tell the user the `reason` and `next` from the JSON and follow it. The runner works for days. A
publisher that keeps answering with a login page or a block while the others download is left out with
`--skip-publishers <keys>` (its sources stay queued; tell the user which and why).

**SI.** `fetch_si.py --corpus <manifest>` after the open downloads: it fetches the SI the index lists (index-sources'
find_si) first, then looks for more on the source's own page.

**Settle.** `settle_corpus.py --corpus <manifest>` writes into the manifest, for each included source, the paths of
its PDF and SI and the version of the copy, or `not_retrieved` with the reason (queued for the library EZproxy, no
copy found, access type not fetched, not fetched yet); the other entries and the rule stay as frozen, the counts are
recounted and `fetched_at` set. Run it again after a later fetch (the EZproxy runner finishing, a retry): a source
fetched since is included again. Then `scale corpus check <manifest>`.

**Abstracts.** Only if the user said yes: index-sources' `fill_abstracts.py --topic <topic>` (it reads the
"Abstract" section of each PDF; `--heuristic` is unreliable — never without showing the user a dry-run sample).

**Report.** Fetched per access type, queued for EZproxy (days), not retrieved by reason (`settle_corpus.py`), where
the files are (`sources/<topic>/files/<access>/<ID>.pdf`); the index `Notes` column says why a source was not
fetched. Then offer curate-corpus on the manifest.

Retry later: `download_open.py --corpus <manifest> --retry-failed`, `fetch_si.py --corpus <manifest> --retry`, then
settle again.

## Scripts (`${CLAUDE_SKILL_DIR}/scripts/`, run with `python3 -I`; `--help` for details)

| Script | What it does |
|---|---|
| `download_open.py` | open-route downloads, PDF title and licence check, folder routing; `--corpus` or `--topic`, `--access`, `--max`, `--retry-failed`, `--added-since` |
| `check_paywalled_access.py` | checks the library's EZproxy with one of the topic's paywalled sources and saves the verdict (machine-wide) |
| `run_paywalled.sh` / `download_paywalled.py` | the single rate-limited EZproxy runner (keep-alive wrapper / the runner); `--corpus` or `--topic`, else every queue |
| `fetch_si.py` | fetches the SI the index lists (then the source page's) into `files/SI/<access>/`; `--corpus` or `--topic`, `--retry` |
| `settle_corpus.py` | records the fetched files, and why the others are missing, in the corpus manifest |
| `_ezlimit.py status` | EZproxy counters, cooldowns, hard stop (`clear-hard-stop` only after the user's review) |

Requires Python 3.10+ with `requests`, `pymupdf`, `pypdf`, and index-sources beside this skill (its scripts are the
shared core: `_common`, `_ledger`, `_download`, `_pdf`, `_vectors`; `INDEX_SOURCES_SCRIPTS` points elsewhere). Every
fetch keeps the project's vector store (index-sources' vectors.py) in step. Errors and fixes:
[index-sources' troubleshooting](../index-sources/references/troubleshooting.md).

## Orchestrated mode (invoked by another skill)

Inline arguments, e.g. `corpus=sources/co2rr/corpora/c1/sources.json access=OA,OA+ND max_sources=200
auto_fetch=true`. No intake questions: the arguments, then the topic's saved config (`download.access_types`), then
OA,OA+ND,Free-to-read. Paywalled is never started here. The gate still stops unless `auto_fetch=true` — the real
numbers are a new decision. Always settle; return the settle summary.
