# The SCALE web service

One publication into a graph from a web page: a user uploads a PDF or gives a DOI or a link. The service fetches it,
curates it into a scale-catal graph, and returns the graph for the page in [`site/`](../site/) to show and to answer
questions from.

## What it does

- **Fetch.** A DOI goes through `scale source start`. It resolves the record with Crossref and, when a contact address
  is set, asks Unpaywall for an open-access copy, which it downloads only under an open licence. A link is fetched only
  from public addresses, every redirect checked again, up to the upload limit. Many publishers refuse such downloads,
  so uploading the PDF always works.
- **Curate.** A model (the Claude Messages API, `SCALE_WEB_MODEL`) follows the
  [curate-source skill](../skills/curate-source/SKILL.md), which is its system prompt, through tools that call the
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
- **Keeps nothing.** A job's folder, holding the PDF, the page texts and the working graph, is deleted when the job ends.
  The capped graph is held in memory until the page reads it, once, or until the job expires (an hour). Questions are
  answered from the graph the page sends, written to a temporary folder that is removed after the answer.

## Who may use it

- **Sign-in.** Only GitHub accounts on the allowlist (`SCALE_WEB_ALLOWLIST`) may start a job or ask a question, since
  both spend the service's model budget. Anyone may open a graph, view it, query it and search it.
- **How it works.** GitHub's OAuth returns the user to the page with a signed session token, an HMAC with
  `SCALE_WEB_SECRET`. The GitHub token is read once for the login and dropped.
- **Daily budgets** (UTC days, counted in memory, so run one instance):
  - jobs per user, and questions per user;
  - tokens per job;
  - tokens a day over everyone. When those are spent, jobs and questions are refused until the next day.

## Settings (environment)

| variable | meaning | default |
|---|---|---|
| `ANTHROPIC_API_KEY` | the Claude API key the service spends (read by the `anthropic` client) | required |
| `SCALE_WEB_SECRET` | signs session tokens; a random string of at least 32 characters | required |
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | the GitHub OAuth app (callback `<public url>/auth/callback`) | required for sign-in |
| `SCALE_WEB_PUBLIC_URL` | the service's own URL | required for sign-in |
| `SCALE_WEB_SITE_ORIGINS` | the page's origin(s), e.g. `https://hlxin.github.io`; only these may call the service or receive a sign-in | required |
| `SCALE_WEB_ALLOWLIST` | GitHub logins, comma-separated | empty: nobody may curate |
| `SCALE_WEB_MODEL` | the model | `claude-opus-5-5` |
| `SCALE_CONTACT_EMAIL` | the address Unpaywall asks for; without it no open-access copy is looked up | empty |
| `SCALE_WEB_JOBS_PER_USER` | jobs per user a day | 5 |
| `SCALE_WEB_QUESTIONS_PER_USER` | questions per user a day | 50 |
| `SCALE_WEB_TOKENS_PER_JOB` | tokens one job may spend | 600000 |
| `SCALE_WEB_TOKENS_PER_DAY` | tokens over everyone a day | 4000000 |
| `SCALE_WEB_MAX_TURNS` | turns of the curation loop | 60 |
| `SCALE_WEB_CONCURRENT_JOBS` | jobs run at once | 2 |
| `SCALE_WEB_MAX_UPLOAD_MB` | the largest PDF | 40 |
| `SCALE_WEB_WORKDIR` | where job folders live while they run | a temporary directory |

## Running it

```bash
docker build -f service/Dockerfile -t scale-web .          # from the repository root
docker run -p 8080:8080 --env-file scale-web.env scale-web
```

The image runs on any container host. Curating one paper takes minutes, but the page polls `GET /jobs/{id}`, so no
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
3. **The page.** Set `window.SCALE_SERVICE_URL` in `site/config.js` to the service's URL, by a pull request.
4. **GitHub Pages.** Publish `site/` with Pages: Settings → Pages → Source: GitHub Actions, and a workflow that
   uploads `site/` (`actions/upload-pages-artifact` with `path: site`, then `actions/deploy-pages`). A workflow is a
   change a person makes.

The endpoints are listed in the docstring of [`scaleweb/app.py`](scaleweb/app.py). The tests,
`service/tests/test_service.py`, use a scripted model and never call GitHub or the API.
