# Relevance screening (curation)

## Contents
- What screening decides; the 0-5 scale
- criteria.md (Claude and API methods)
- Claude method: batches and subagents
- API method: any OpenAI-compatible endpoint
- Keyword method: keywords.json and how it scores
- No screening
- Full-text check after download

## What screening decides

Screening runs on the index BEFORE downloading, so nothing is fetched (or spent against EZproxy limits) for papers
outside the topic. Every method writes, per topic, `Relevance` 0-5, a short note, and in/out of scope: in scope when
Relevance ≥ threshold (default 3, `config.screening.threshold`). Out-of-scope papers move to the topic's
`index/excluded.csv` with `Notes: Out of scope: <reason>` and are never downloaded. Errata/correction notices are
skipped. Claude and API screening also choose each paper's Topic A/B/C in the same pass ([topics.md](topics.md));
keyword screening and no screening use the deterministic vocabulary match.

Scale (shared by all methods): 5 core topic with substantive results or a review of it · 4 main theme · 3 one of
several themes, or undecidable (kept) · 2 tangential / related-but-distinct system · 1 incidental mention ·
0 not a research paper. Bias: when unsure keep it (3) — a wrong exclusion loses a paper, a wrong inclusion costs
one download.

## criteria.md

`.scripts/<slug>/criteria.md`, written by you from the user's topic and shown in the plan for approval. It is
inserted into the instructions every judge reads (`templates/screen_instructions.md`). Keep it to ~10-20 lines:

```markdown
**Topic:** MXene-based electrocatalysts for nitrogen-cycle reactions that make ammonia.

**In scope:** MXene (Ti3C2Tx, V2C, Nb2C, Mo2C, composites) electrocatalysts or supports for nitrate, nitrite or N2
electroreduction to ammonia; DFT/mechanism studies of these reactions on MXenes; reviews covering them.

**Out of scope:** MXene supercapacitors or batteries; photocatalysis without an electrode; nitrate adsorption or
removal; sensors; catalysts without an MXene component.
```

Name the near-misses explicitly in the out-of-scope list — that is where judges disagree.

## Claude method

```bash
python3 -I ${CLAUDE_SKILL_DIR}/scripts/screen.py --topic <slug> prep            # batches of 100 title+abstract items
python3 -I ${CLAUDE_SKILL_DIR}/scripts/screen.py --topic <slug> next 5          # name  batch_path  output_path (x5)
```

Launch one `Agent` per printed line, all in ONE message (`subagent_type: "general-purpose"`, `model: "sonnet"`;
`haiku` for very large, clear-cut fields), prompt:
*"Read <the instructions.md path printed by prep> and follow it exactly. Batch file: <batch_path>. Write your output
to: <output_path>."* Each subagent replies with one line (`batch_00007: 100 scored`). Then:

```bash
python3 -I ${CLAUDE_SKILL_DIR}/scripts/screen.py --topic <slug> merge           # folds outputs into the ledger + CSV
python3 -I ${CLAUDE_SKILL_DIR}/scripts/screen.py --topic <slug> status          # pending / waiting / merged
```

Repeat `next` → subagents → `merge` until `next` prints nothing. Items a judge skipped or mangled stay unscreened
and are re-batched by the next `prep`. If a subagent never wrote its output, `prep` again re-queues those papers.
Cost guide: one subagent per 100 papers (~40-60k input tokens each).

## API method

Any OpenAI-compatible chat-completions endpoint (vLLM, Ollama with OpenAI API, institutional gateways, OpenAI):
`config.screening` = `{"method": "api", "base_url": "https://host/api/v1", "model": "<model name>",
"concurrency": 4, "threshold": 3}`; optional `"extra_body": {"reasoning_effort": "medium"}` for reasoning models,
`"key_env": "MY_ENV_VAR"` to read the key from an environment variable. Default key source: `llm_api_key = ...` in
`.claude/keys.txt` (also accepted: `LLM_API_KEY=` / `ARC_API_KEY=` in `.scripts/.env`).

```bash
python3 -I ${CLAUDE_SKILL_DIR}/scripts/screen.py --topic <slug> prep     # batches of 25 for APIs
python3 -I ${CLAUDE_SKILL_DIR}/scripts/screen.py --topic <slug> api      # calls the endpoint, writes outputs
python3 -I ${CLAUDE_SKILL_DIR}/scripts/screen.py --topic <slug> merge
```

An HTTP 401/403/404 stops with the server's message (wrong key, model or URL); 429/5xx are retried with backoff.

## Keyword method

`.scripts/<slug>/keywords.json` — drafted by you from the topic, approved by the user, reused by update runs:

```json
{
  "include_groups": [["MXene", "Ti3C2", "re:\\bTi3C2T"],
                     ["nitrate", "nitrite", "re:NO3-?RR"],
                     ["ammonia", "NH3", "electroreduction", "electrocatalytic"]],
  "exclude": ["supercapacitor", "photocatalytic", "adsorption of nitrate", "sensor"],
  "threshold": 3
}
```

Score: 5 = every include group matches in the title · 4 = every group matches in title + abstract · 2 = only some
groups · 0 = none. An exclude term in the title caps the score at 1; in the abstract (when the title does not carry
every group) at 2. The note says which concept was missing or which exclude term hit, e.g.
`no mention of (ammonia, NH3, electroreduction)`. Terms: phrases (a space also matches a hyphen) or `re:` regexes.

## No screening

`screen.py --topic <slug> none` keeps every gate-passing paper in scope with an empty Relevance. Use when the user
wants the whole field and will filter later.

## Full-text check (optional, Claude/API)

After downloading: `screen.py --topic <slug> prep --stage fulltext` (batches of 10 papers with the text of pages
1-3; judges read the PDF itself when the text is poor), then `next 5 --stage fulltext` + subagents (or
`api --stage fulltext`), then `merge --stage fulltext`. The full-text score replaces the abstract score; papers that drop below the threshold are
moved (with their SI) to `.scripts/<slug>/out_of_scope/` and the CSV notes it.
