# The SCALE web service

One source (a source, patent or report) into a graph from a web page: a user uploads a PDF or gives a DOI or a link. The service fetches it,
curates it into a scale-catal graph, and returns the graph for the page [`site/publication.html`](../site/publication.html) to show and to answer
questions from.

## What it does

- **Fetch.** A DOI goes through `scale source start`. It resolves the record with Crossref and, when a contact address
  is set, asks Unpaywall for an open-access copy, which it downloads only under an open licence. A link is fetched only
  from public addresses, every redirect checked again, up to the upload limit. Many publishers refuse such downloads,
  so uploading the PDF always works. A DOI that catal-commons already holds, or that an open contribution adds, is
  answered with a link to it before anything is spent (`?again=1` curates it all the same).
- **Curate.** A model (the Claude Messages API, `SCALE_WEB_MODEL`) follows the
  [curate-corpus skill](../skills/curate-corpus/SKILL.md), which is its system prompt, through tools that call the
  scale-catal code:
  - `read_pages`: the page texts;
  - `describe`: the schema and the catalysis checklist;
  - `upsert`, `remove`: records in the working graph;
  - `check`: `scale source check --derive-links`, with every quote checked against the page texts.

  It works until the check passes, or until its turn limit or token budget runs out. Then `scale source finish
  --public` caps every quote by the source's rights.
- **Answer.** A question about a graph runs the [query-graph skill](../skills/query-graph/SKILL.md) over `describe`,
  `stats`, `search` and `query`. These are the same functions as `scale graph query` and `scale graph search`, so a
  plan the model runs gives exactly the rows the CLI gives. The answer cites those rows, and the page lists the plans
  it ran. `/query` and `/search` run a plan or a search directly, without the model.
- **Keeps a source only when it may.** A job's folder, holding the PDF, the page texts and the working graph, is
  deleted when the job ends (the source is first copied to the kept sources when its licence or the user allows). The capped graph is held in memory until the page says it has it (`POST
  /jobs/{id}/done`), or an hour after the job ends, so a reply lost on the way can be asked for again. Questions are answered from the graph the page sends, written to a temporary folder that is
  removed after the answer.
- **The kept sources** (`SCALE_WEB_ARCHIVE`, [`scaleweb/archive.py`](scaleweb/archive.py)). So that a source can be
  curated again after a schema change without anyone uploading it again, the copy the user gave (the PDF they
  uploaded, or the open-access copy fetched for a DOI, and its page texts) is kept in a private folder of the
  service: always for a source under an open licence, and for any other source only when the user ticks the box that
  agrees to it (`?keep=1`, unticked by default), recorded with their login and the time. An embedding cannot be read
  back into the numbers and quotes a curation needs, so the source itself is what is kept. Nothing kept is published, committed or sent to a
  page. `GET /kept` lists a user's agreements and `POST /kept/forget` withdraws one; the source goes when none is left.
- **Curating again.** `python -m scaleweb --recurate` curates every kept source whose latest curation is under another
  schema version than catal-commons', from its PDF (else its texts), within the day's budget (`--dry-run` lists them,
  `--only SHA256` takes one), and keeps each new graph beside it. Updating catal-commons with it is a pull request a person opens and reviews.
- **Before keeping sources in copyright,** the person who runs the service checks that the law where it runs
  allows it (text-and-data-mining exceptions differ between countries) and says so in the page's sharing note. A
  contributor's agreement does not cover the publisher's rights: a source read through a library subscription is
  governed by that library's licence, and some licences limit sending text to a third party's generative AI tool.
- **A statement of access for every PDF.** An uploaded PDF is curated only when the user ticks that they have lawful
  access to it (for example through their library) and that, as far as they know, its licence allows text mining with
  an AI tool (`?attest=1`; without it the upload is refused). A DOI alone is curated only from an openly licensed copy.
- **Removal.** A rights holder asks for a source's records or kept copy to be removed at `SCALE_CONTACT_EMAIL` (the
  page shows it), or by an issue on the repository; the person who runs the service removes the kept copy
  (`POST /kept/forget` for the contributor's agreement, or by deleting its folder) and opens the pull request that
  removes its records.

## Contributing to catal-commons

When a job is done, the page offers **Contribute to the commons**:

- **Only the service's own graphs.** The service signs a receipt for the graph it curated for the user, covering its
  digest and the source's rights entry. Only that graph, unchanged and sent by that user, can be contributed, so a
  contribution cannot raise a source's rights class or carry text the service did not check.
- **The check** (`POST /contribute/check`). The service reads `graphs/catal-commons` from main and the open pull
  requests from `contrib/` branches. It answers that the source is already in the commons, or already proposed, or
  else what adding it would change. The matching is `scale graph contribute`'s (`tools/commons.py`): the same DOI,
  identifier, text digest, or title and year.
- **Repeats are discarded.** A shared record the commons holds already, by id or by identity (an identifier, else
  the same name with no other formula), a value it holds or a link it holds (the same ends and type) is not merged
  again: the contribution points to the held record, which gains its evidence. Repeats are listed in the check and
  the pull request and never count on the leaderboard; a value that differs from the held one is left out for the
  reviewer.
- **The pull request** (`POST /contribute`). One commit on `contrib/<slug>`, from main, adds
  `parts/sources/<slug>.json`, updates `parts/shared.json` and adds the source's entry in `rights.yaml`. Quotes are
  capped under the commons limits: none of a source in copyright. The pull request is opened with the service's
  GitHub token (`SCALE_WEB_GITHUB_TOKEN`), a bot's and never the user's. It credits the contributor by GitHub login
  and asks the reviewers in `SCALE_WEB_REVIEWERS`. It also adds the contribution to `contributors.yaml` (the login,
  the source, the day, its evidence-backed triples and its checklist completeness), from which the leaderboard
  ranks contributors once it is merged. CI and a reviewer check it, and a person approves and merges it.

## The leaderboard

`commons.boards` (`tools/commons.py`, `SCORING`) scores each contributor; the site publishes it without use counts
(`data/leaderboard.json`), and `GET /leaderboard` adds them:

- **Score** = the sum over a contributor's merged sources of triples x (1 + log2(1 + reach)). A **triple** is one
  evidence-backed statement: a link between two records, or a value a record or link states, when it cites evidence
  (evidence, notes, provenance, values not reported and bibliographic details do not count). **Reach** is how many
  distinct (person, day) pairs had a question, query or search answered with one of the source's records, counted by
  the service for signed-in people other than the source's contributor ([`scaleweb/usage.py`](scaleweb/usage.py)): the
  same question a hundred times a day counts once, and nobody raises their own score. Only a keyed digest of the login
  and the day are kept, never the question (`SCALE_WEB_USAGE`).
- **Completeness** (the checklist's should items and evidence patterns found) is shown beside the score, never mixed
  into it. **Levels** by score: Contributor, Curator (1,000), Senior curator (10,000), Fellow (100,000). Boards: all
  time and the last 90 days; each contributor's row opens their sources.
- The rules are published with the board ("How scoring works") and change by pull request.

## Who may use it

- **Sign-in.** Only GitHub accounts on the allowlist (`SCALE_WEB_ALLOWLIST`) may start a job or ask a question, since
  both spend the service's model budget; an allowlist of `*` admits any GitHub account, each within its daily budget.
  Anyone may open a graph, view it, query it and search it. No reader ever gives a model key. Signing in itself
  admits only those accounts: with an empty allowlist every GitHub sign-in ends in "not admitted", so set it (or `*`)
  before the page links to the service.
- **How it works.** GitHub's OAuth returns the user to the page with a signed session token, an HMAC with
  `SCALE_WEB_SECRET`. The GitHub token is read once for the login and dropped. Each token the service signs names its
  use: a session (a day) signs a reader in, and a contribution receipt (a week) never does.
- **One sign-in, one tab.** The page starts each sign-in with a random nonce that it keeps in that tab
  (`/auth/login?return=…&nonce=…`). The service returns the nonce with its answer, and the page takes a token only with
  the nonce it is waiting for. So a link carrying someone else's token, or someone else's unfinished sign-in, never
  signs a reader in. The OAuth state is used once. The return address must be a page of the site in plain ASCII, and the
  answer is merged into its fragment, so the explorer's open graph (`#g=…`) comes back with the reader.
- **Daily budgets** (UTC days, counted in memory, so run one instance):
  - jobs per user, and questions per user;
  - tokens per job;
  - tokens a day over everyone. When those are spent, jobs and questions are refused until the next day.

## What it costs, and who pays

The service spends its own API key, so a reader needs no key and pays nothing. A source costs about $1 to $3 with
Claude Opus 5.5 ($4 and $20 per million input and output tokens, $0.20 per million cached input tokens): the skill and
the schema are a cached system prompt, and `SCALE_WEB_TOKENS_PER_JOB` caps a job. `SCALE_WEB_TOKENS_PER_DAY`, the jobs
per user and a spending limit on the key in the Claude Console bound a day. A source already in catal-commons costs
nothing. Whoever runs the service pays for it: the project's API account, or a lab that runs its own instance for its
members.

## Settings (environment)

| variable | meaning | default |
|---|---|---|
| `ANTHROPIC_API_KEY` | the Claude API key the service spends (read by the `anthropic` client) | required |
| `ANTHROPIC_BASE_URL` | another address for the Messages API, such as a gateway that routes and meters requests; it must accept Anthropic's Messages API with tool use, pass prompt caching through and return token usage (read by the `anthropic` client; `ANTHROPIC_AUTH_TOKEN` for a bearer token) | Anthropic's API |
| `SCALE_WEB_SECRET` | signs session tokens; a random string of at least 32 characters | required |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | the GitHub OAuth app (callback `<public url>/auth/callback`) | required for sign-in |
| `SCALE_WEB_PUBLIC_URL` | the service's own URL | required for sign-in |
| `SCALE_WEB_SITE_ORIGINS` | the page's origin(s), e.g. `https://hlxin.github.io`; only these may call the service or receive a sign-in | required |
| `SCALE_WEB_ALLOWLIST` | GitHub logins, comma-separated; `*` admits any GitHub account | empty: nobody may curate |
| `SCALE_WEB_MODEL` | the model | `claude-opus-5-5` |
| `SCALE_CONTACT_EMAIL` | the address Unpaywall asks for, and the page's contact for a rights holder; without it no open-access copy is looked up | empty |
| `SCALE_WEB_JOBS_PER_USER` | jobs per user a day | 5 |
| `SCALE_WEB_QUESTIONS_PER_USER` | questions per user a day | 50 |
| `SCALE_WEB_TOKENS_PER_JOB` | tokens one job may spend | 600000 |
| `SCALE_WEB_TOKENS_PER_DAY` | tokens over everyone a day | 4000000 |
| `SCALE_WEB_MAX_TURNS` | turns of the curation loop | 60 |
| `SCALE_WEB_CONCURRENT_JOBS` | jobs run at once | 2 |
| `SCALE_WEB_MAX_UPLOAD_MB` | the largest PDF | 40 |
| `SCALE_WEB_WORKDIR` | where job folders live while they run | a temporary directory |
| `SCALE_WEB_GITHUB_TOKEN` | the bot's token for contributions: a bot account's fine-grained token (or a GitHub App's installation token) that may write contents and pull requests of the repository | empty: contributions off |
| `SCALE_WEB_REPO`, `SCALE_WEB_COMMONS` | the repository and the commons folder | `hlxin/scale`, `graphs/catal-commons` |
| `SCALE_WEB_REVIEWERS` | GitHub logins asked to review each contribution, comma-separated | empty |
| `SCALE_WEB_CONTRIBUTIONS_PER_USER` | contributions per user a day | 5 |
| `SCALE_WEB_ARCHIVE` | a persistent, private folder for kept sources (a mounted volume) | empty: nothing is kept |
| `SCALE_WEB_USAGE` | a persistent file for the leaderboard's use counts (scaleweb/usage.py) | empty: in memory |
| `SCALE_WEB_INBOX` | a folder on the service's computer: each source waits there for Claude Code, which curates it ([The inbox](#the-inbox-claude-code-on-a-computer-of-your-own)) | empty: the service's model curates |
| `SCALE_WEB_INBOX_LOGIN` | the GitHub login a PDF dropped into the inbox's queue by hand is credited to | empty: such a PDF is set aside |
| `SCALE_WEB_CLAUDE` | the Claude Code command the inbox runner starts (its full path when launchd starts the runner; a release recent enough for `SCALE_WEB_MODEL`, since an older one refuses a newer model) | `claude` |
| `SCALE_WEB_INBOX_TURNS`, `SCALE_WEB_INBOX_MINUTES` | Claude Code's turns and minutes for one source | 200, 90 |
| `SCALE_WEB_INBOX_WORKERS` | sources Claude Code curates at once in the inbox, each in its own folder | 1 |
| `SCALE_WEB_ASK` | `claude-code`: questions in words are answered on the service's computer by Claude Code, confined as the inbox's curation is, two at a time ([The inbox](#the-inbox-claude-code-on-a-computer-of-your-own)) | empty: the service's model (the API key) |
| `SCALE_WEB_PYTHON`, `SCALE_WEB_PORT` | for `service/launchd/scale-web.sh`: the Python with scale-catal's dependencies, and the service's port | `python3`, 8080 |

## The inbox: Claude Code on a computer of your own

A lab can run the service on a computer of its own and have Claude Code curate there, in place of the service's
model loop (`SCALE_WEB_INBOX`, [`scaleweb/inbox.py`](scaleweb/inbox.py), [`scaleweb/runner.py`](scaleweb/runner.py)).
Everything the Curate dialog says holds as it does for the model loop:

- **Upload.** `POST /jobs` checks the sign-in, the statement of access and the commons as before, then puts the
  source in the inbox's queue and answers at once. The page follows the job (`GET /jobs/{id}`, readable until the
  inbox forgets it, after 14 days) and lists the reader's sources (`GET /inbox`).
- **Curate.** launchd starts the runner whenever the queue holds something ([`launchd/`](launchd/); elsewhere
  `python -m scaleweb.runner --watch 30`). For each source: `scale source start`; Claude Code
  (`claude -p`, the curate-corpus skill appended to its system prompt) fills the graph; `scale source check
  --derive-links` must pass, its problems going back to Claude Code twice at most; `scale source finish --public`. A
  run that records nothing fails.
- **Confined.** Claude Code runs in restricted mode in the source's folder: the file tools there and, of the
  shell, only `scale source check` and `scale graph describe`, in its sandbox (which runs no other command on its
  own), with no network, no git and no token in its environment. The source's text is data to it.
- **The graph comes back to its owner only.** `GET /jobs/{id}` gives it to the reader who sent the source, signed for
  them as a job's graph is, and nothing is published unless they contribute it: Contribute, a separate click, opens
  the bot's pull request. The runner opens none.
- **Kept as the page says.** When the job ends, the PDF and its page texts go to the archive (`SCALE_WEB_ARCHIVE`,
  [`scaleweb/archive.py`](scaleweb/archive.py)) always for a source under an open licence and for any other only when
  its owner ticked the box, and leave the inbox, done or failed. `GET /kept` and `POST /kept/forget` work as before.
  `python -m scaleweb.runner --recurate` (`--dry-run` lists them) sends the kept sources curated under another schema
  version than catal-commons' through the inbox again, and keeps each new graph beside its source; updating catal-commons
  with it is a person's pull request.
- **By hand.** A PDF dropped into `queue/` is curated the same way for `SCALE_WEB_INBOX_LOGIN`, who opens its graph from
  the page; without that login it is set aside in `rejected/`.
- **Several at once.** Each upload is a job of its own, told its place in the queue. One runner works the queue
  (launchd starts one, and a lock keeps it one), the oldest first, and takes what arrives while it works: up to
  `SCALE_WEB_INBOX_WORKERS` sources at once, each in its own folder with its own Claude Code, and the
  workers ask Crossref for a DOI's record one at a time, waiting out its "too many requests". More at once spends a
  Claude plan's usage sooner, not more of it. A reader queues at most `SCALE_WEB_JOBS_PER_USER` a day.
- **The same source twice.** Before Claude Code starts, the runner looks for the source by its DOI or its PDF's
  digest (and by title and year when the DOI gives them) in catal-commons, in the open contributions and among the
  same reader's curated jobs; another reader's job never counts, since their graph is theirs. A repeat ends there and
  points to the other one; "Curate it anyway" sends it again.
- **One Source.** catal-commons takes one Source per contribution, so a Source record Claude Code adds for a work the
  source cites goes back to it as a problem, with the check's errors.
- **Questions here too.** With `SCALE_WEB_ASK=claude-code`, a question in words (`/ask`) is answered on the
  service's computer by Claude Code, by the query-graph skill, in a folder that holds the graph alone and with only
  `scale graph query`, `search`, `describe` and `stats`. The plans it wrote run again through `scale query` for the
  page, and the records they return credit the commons sources the answer used (usage.py). Two questions are answered
  at a time; without the setting, questions use the service's model and its API key.
- **Claude Code's sign-in.** The runner's Claude Code signs in on its own: with a Claude plan (`claude setup-token`,
  its token set as `CLAUDE_CODE_OAUTH_TOKEN`) or with an API key (`ANTHROPIC_API_KEY`).

Setting it up on a Mac (a person does it, since the steps hold secrets):

1. Put a checkout, the settings file and the inbox outside Desktop, Documents and Downloads, which macOS keeps
   launchd's agents out of: for example `~/scale-web/`.
2. Write the settings file (shell syntax, `chmod 600`): `SCALE_WEB_SECRET`, `SCALE_WEB_INBOX`,
   `SCALE_WEB_SITE_ORIGINS`, the OAuth app's `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`, `SCALE_WEB_PUBLIC_URL`,
   `SCALE_WEB_ALLOWLIST`, `SCALE_WEB_CLAUDE` (the full path of `claude`), Claude Code's sign-in and `SCALE_WEB_ARCHIVE`
   (after the legal check above); for contributions, `SCALE_WEB_GITHUB_TOKEN` and `SCALE_WEB_REVIEWERS`.
3. Run `service/launchd/install.sh ~/scale-web/scale-web.env`, which loads both agents (`--uninstall` removes them):
   the service on `127.0.0.1:8080`, always on, and the runner.
4. Give the service its public HTTPS name with a tunnel (Tailscale Funnel, or Cloudflare Tunnel with a domain), and
   set that name as `SCALE_WEB_PUBLIC_URL`, in the OAuth app's callback and in `site/config.js`.

## Running it

```bash
docker build -f service/Dockerfile -t scale-web .          # from the repository root
docker run -p 8080:8080 --env-file scale-web.env scale-web
```

The image runs on any container host. Curating one source takes minutes, but the page polls `GET /jobs/{id}`, so no
request is long. Locally without Docker:

```bash
uv run --extra pdf --extra search --with anthropic env PYTHONPATH=service python -m scaleweb --port 8080
```

## Deploying (done by a person)

These steps create accounts and hold secrets, so agents never do them:

1. **Host.** Choose a host and deploy the image with the settings above. Set a spending limit on the API key in the
   Claude Console as well as `SCALE_WEB_TOKENS_PER_DAY`.
2. **GitHub OAuth app.** Create one (GitHub → Settings → Developer settings → OAuth Apps) with the callback
   `<public url>/auth/callback`.
3. **The bot (for contributions).** Create a bot account, or a GitHub App. Give it write access to the
   repository's contents and pull requests (pushes to main stay blocked by the ruleset), and set its token as
   `SCALE_WEB_GITHUB_TOKEN`.
4. **The page.** Set `window.SCALE_SERVICE_URL` in `site/config.js` to the service's URL, by a pull request.
5. **GitHub Pages.** Settings → Pages → Source: GitHub Actions. The workflow `.github/workflows/pages.yml` builds the
   site (`scale site build`) and publishes it on every push to main: the graph explorer at the root, this page at
   `publication.html`.

The endpoints are listed in the docstring of [`scaleweb/app.py`](scaleweb/app.py). The tests,
`service/tests/test_service.py`, use a scripted model and never call GitHub or the API.
