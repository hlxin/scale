# Repository settings

The GitHub settings that make the rules in [GOVERNANCE.md](GOVERNANCE.md) hold for `hlxin/scale`, a personal
repository of its owner, Hongliang Xin. **Every step on this page is a human action** by the owner. Agents do
not apply them. Run the commands in bash, from a checkout of this repository with an authenticated `gh` and
`jq`. In zsh, the macOS default shell, start `bash` first: pasted into zsh, every `#` comment line is run as a
command.

```bash
OWNER=hlxin
REPO=scale
```

What GitHub does and does not enforce:

- CODEOWNERS routes review: it requests reviews from the owners of the changed paths. It does not restrict
  who may write, and the `main` ruleset does not require a code owner's review: one approval from anyone with
  Write access is enough on GitHub; the review policy says who the reviewers are.
- GitHub never lets the author of a pull request approve it.
- Events caused by the workflow token (`GITHUB_TOKEN`) do not start other workflows.
- Anyone with Write access can push a branch with a changed workflow and run it. Such a run can read every
  repository secret. Hence the secrets section below.
- Some protections depend on the plan: on a free personal account, rulesets and environment protection rules
  apply to public repositories only; a private repository needs GitHub Pro for them. Until then the rules of
  GOVERNANCE.md are kept by practice.

## 0. The address and its earlier contents

This repository replaced the earlier contents of github.com/hlxin/scale (its own scale-graph numbering 0.1.0-0.8.0,
package scale-catalysis); versions here restart at 0.1.0 and are a separate line. The address already holds that
earlier repository, with its own branches and its tags `v0.2.0` and `v0.3.0`. Do not push this repository into it,
and never force-push over it: its tags would collide with this release line (`v0.1.0` onward), and the update
check (`scale status`) reads the newest `v*` tag of `github.com/hlxin/scale`, so it would report the earlier tags
as newer releases; its branches, tags and pull-request refs would also keep its history reachable. Instead, before
the first push:

```bash
git clone --mirror https://github.com/$OWNER/$REPO.git scale-earlier.git     # a full backup, kept offline
gh repo rename scale-prepublic --repo $OWNER/$REPO --yes                    # or archive it: gh repo archive
gh repo view $OWNER/$REPO 2>/dev/null && echo "the address is still taken"  # must print nothing
```

Keep the renamed repository private (or delete it, only once the backup is checked). Then create a fresh
`hlxin/scale` (section 1) and push this repository's `main` to it:
`git remote add origin git@github.com:$OWNER/$REPO.git && git push -u origin main`.

## 1. The repository

```bash
gh repo create $OWNER/$REPO --private --description "SCALE: Shared Concepts, Attributes, and Links with Evidence. One shared framework for evidence-backed scientific knowledge graphs across domains."
gh api -X PATCH repos/$OWNER/$REPO -F delete_branch_on_merge=true -F has_wiki=false -F allow_update_branch=true
```

Head branches are deleted on merge; the wiki is off (it would be an unreviewed second home for text); authors
can update their branch from the web page. Discussions are optional (`-F has_discussions=true`); the discussion
forms in `.github/DISCUSSION_TEMPLATE/` are used once they are on. Create the labels once from
`.github/labels.yml` (the command is at the top of that file).

## 2. Collaborators and reviewers

A personal repository has its owner and collaborators; every collaborator has Write access. The reviewers, the
owner `@hlxin` and the people listed in [`review-policy.yaml`](review-policy.yaml), are named on every line of
[`.github/CODEOWNERS`](../.github/CODEOWNERS). The list is open: more reviewers are invited as people join. GitHub asks every reviewer; the `reviewers` workflow withdraws the other requests when one
approves ([GOVERNANCE.md](GOVERNANCE.md#every-reviewer-is-asked-one-approval-is-enough)).

**Adding a reviewer.** When a reviewer joins, a pull request adds the person's name, GitHub handle and `since` to
`governance/review-policy.yaml`, `core/CORE.yaml` and `domain/DOMAIN.yaml` (with `roles: [maintainer]`) and adds the handle to every line of `.github/CODEOWNERS` (and its copy in
`tools/tests/fixtures/codeowners/`; `scale domains check` fails until every line names every reviewer); the
owner invites them as a collaborator:

```bash
gh api -X PUT repos/$OWNER/$REPO/collaborators/<handle>     # they accept the invitation
gh api repos/$OWNER/$REPO/codeowners/errors                 # must report no errors
```

Never write a name or handle that is not a real person who agreed to review (an entry marked `placeholder: true`
is nobody, and `scale check` warns while one is listed). A code owner counts only with Write access, so a reviewer is invited before the
CODEOWNERS pull request merges.

Moving the repository to an organization later (to give teams their own lines in CODEOWNERS, or Triage access
to people who only sort feedback) is a decision record of its own; the tools accept a team (`@org/team`) as a
code owner wherever they accept `@hlxin`.

## 3. Actions permissions

```bash
gh api -X PUT repos/$OWNER/$REPO/actions/permissions/workflow -f default_workflow_permissions=read \
  -F can_approve_pull_request_reviews=false
```

The workflow token is read-only unless a workflow asks for more in its `permissions:`; no workflow asks for
`contents: write`, and none opens or approves pull requests. No workflow uses `pull_request_target`.

| workflow | runs | needs |
|---|---|---|
| `ci` | every pull request and push to `main` | nothing |
| `triage` | weekly, or started by hand | nothing (it opens a digest issue with the workflow token, `issues: write`) |
| `scale-agents` | every new issue, comment and pull-request review by a collaborator (`author_association` OWNER, MEMBER or COLLABORATOR; not a bot's, and not an approval with no text), or by hand from `main` | the secret `CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY`) and the Claude GitHub App (below) |
| `reviewers` | every submitted review and every push to a pull request from this repository | nothing (the workflow token, `pull-requests: write`: withdraws or renews review requests, comments) |
| `publish` | a published GitHub release | the `pypi` environment and the trusted publisher (section 6); configured, first used for v0.2.0 |

## 4. Secrets

No secret is needed for the checks of a pull request. One is optional, for the agent. A repository secret can be
read by any workflow run from a branch, so add it only when the agent is used, and only while every collaborator is
trusted with it; once the repository is public or on a plan with environment protection rules, move it into an
environment whose deployment policy is `main` only (`agents`) and name it in the job (`environment: agents`), so that
only the reviewed workflow file on `main` can read it.

### The agents

`@scale-agents` (a team of Claude agents on GitHub, `anthropics/claude-code-action`) start on their own on every new
issue, comment and pull-request review, and when a person with write access runs the workflow by hand (Actions →
scale-agents → Run workflow); events from bots, the agents' own comments included, are skipped. No label or tag is
needed. Every run draws on the subscription (or the API key), so once the repository is public and anyone can open issues, decide whether to
keep this for everyone or limit it to collaborators (a condition on `author_association` in the job). To use it,
install the
**Claude GitHub App** (https://github.com/apps/claude) on `hlxin/scale` (contents, issues and pull requests,
read and write) and set one secret. With a Claude subscription (Pro, Max, Team or Enterprise), run
`claude setup-token` in a terminal, sign in, copy the token it prints (`sk-ant-oat…`, valid for a year, tied to the
person who made it, whose usage limits the runs draw on) and save it:

```bash
gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo $OWNER/$REPO
```

Or, for API billing, `gh secret set ANTHROPIC_API_KEY --repo $OWNER/$REPO`. Renew the subscription token before it
expires.

The agent works on an `agent/…` branch and opens a pull request, ready for review, with the App's token, so the
pull request's author is the App and any reviewer, the person who asked included, can approve it; asked on its
own pull request, it pushes fixes to the same branch. It never approves or merges. The App's token cannot change
workflow files, so the agent cannot edit `.github/workflows/`. Its commits are credited to `claude[bot]`: the
workflow sets `bot_id: "209825114"`, because GitHub credits a commit by the id in its noreply email and the action's
default id (41898282) is `github-actions[bot]`'s.

An agent working elsewhere (for example on a person's computer) opens pull requests under a **bot account** of its
own, never under the person's account: GitHub does not let an author approve their own pull request. To set one
up, create a GitHub account for the bot, invite it as a collaborator with Write access, and give the agent a
fine-grained token of that account (this repository only; contents and pull requests, read and write). The bot is
not a reviewer: it is never listed in the review policy, and its approvals would not count.
Its commands run with the action's subprocess secret scrub off (`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB: "0"`), as in the
action's own examples: the scrub would strip the GitHub token from the agents' `gh` commands (reading the event,
commenting, opening the pull request), and they stopped without a reply. The guards are the allowed tools, issue and
comment text read as data, and minimal permissions; the job's workflow token only reads the contents. Each run's
summary shows what the agents did (`display_report`). For a public repository, consider the action's own GitHub tools
in place of `gh`, so that the scrub can stay on.

## 5. Branch ruleset for `main`

[`github/ruleset-main.json`](github/ruleset-main.json):

| rule | setting |
|---|---|
| changes only by pull request | required |
| approving reviews | **1** (any reviewer) |
| review from a code owner | not required (CODEOWNERS requests reviews from the owner and the reviewers) |
| dismiss approvals when new commits are pushed | yes |
| the last push must be approved by someone other than its author | yes |
| required status checks | `test (3.10)`, `test (3.11)`, `test (3.12)`, `test (3.13)`, `package`, `specification-changes`, from GitHub Actions (`integration_id` 15368) |
| branch must be up to date before merging | no (below) |
| force pushes, deletion | blocked |
| bypass | nobody: the owner, the GitHub Actions app and every other actor go through a pull request |

```bash
gh api -X POST repos/$OWNER/$REPO/rulesets --input governance/github/ruleset-main.json
```

To change it later, edit the JSON by pull request, then
`ID=$(gh api repos/$OWNER/$REPO/rulesets --jq '.[] | select(.name == "main") | .id')` and
`gh api -X PUT repos/$OWNER/$REPO/rulesets/$ID --input governance/github/ruleset-main.json` (the `main` ruleset's
id is 24803060: `gh api -X PUT repos/hlxin/scale/rulesets/24803060 --input governance/github/ruleset-main.json`).
Re-apply it after a pull request that changes the JSON merges, for example the one that dropped the
`proposal-check` required check.

**No workflow gets past the approval.** Anyone with Write can push a branch whose workflow asks for
`contents: write` and runs `git push origin HEAD:main`; that run's workflow token must not get past the
approval.

**Up-to-date branches are not required.** `strict_required_status_checks_policy` is `false`: with it on, every
merge would force each open pull request to merge `main` again and, because approvals are dismissed on push, to
be approved again. Two pull requests that each pass alone can conflict once both are merged; CI
on `main` shows it at once. Two schema changes built on the same version cannot both merge as they are: once the
first merges, `scale schema check` fails the second, which rebases and runs `scale schema bump` again.

### No bypass

Nobody bypasses the `main` ruleset, the owner included: every change to `main`, a documentation change or a new
reviewer included, is a pull request approved by a reviewer other than its author. (While the owner was the only
reviewer, the repository admin could bypass it; that ended once other reviewers joined.)

## 6. Tag ruleset and the `pypi` environment

[`github/ruleset-tags.json`](github/ruleset-tags.json) blocks creating, moving and deleting `v*` tags for
everyone except the repository admin (the owner):

```bash
gh api -X POST repos/$OWNER/$REPO/rulesets --input governance/github/ruleset-tags.json
gh api -X PUT repos/$OWNER/$REPO/environments/pypi --input - <<'EOF'
{"deployment_branch_policy": {"custom_branch_policies": true, "protected_branches": false}}
EOF
gh api -X POST repos/$OWNER/$REPO/environments/pypi/deployment-branch-policies -f name='v*' -f type=tag
```

The environment deploys only from `v*` tags, which only the owner may create. Once the plan allows it, add the
owner (and later the reviewers) as the environment's required reviewers. On pypi.org, add a trusted publisher
for the project `scale-catal`: owner `hlxin`, repository `scale`, workflow `publish.yml`, environment `pypi`.
No PyPI token is stored anywhere. Until the publisher is registered, `publish` fails at its upload step and
publishes nothing.

## 7. Sharing the repository

Before collaborators are invited, and again before the repository is made public:

- check the history of every branch and tag: no project data, no third-party text beyond the copyright cap,
  no invented names (`scale check` covers the committed tree: `scale evidence access`, `scale evidence report
  --all`, `reuse lint`);
- give the code of conduct a private contact address: replace `TODO-contact` in
  [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) with an address of the owner's choice;
- add `SECURITY.md` before the repository is public;
- once public: `gh api -X PATCH repos/$OWNER/$REPO -f visibility=public`; set pull-request workflows from forks
  to "Require approval for all external contributors" (Settings → Actions → General); apply the rulesets
  (sections 5 and 6) if the plan did not allow them before; move the secrets into environments (section 4).

Publish to PyPI only with the first release ([release-process.md](release-process.md)).

**GitHub Pages** (the graph explorer, [site/](../site/)): Settings → Pages → Build and deployment → Source: GitHub
Actions. `.github/workflows/pages.yml` then builds and publishes the site on every push to main, with a token that
writes only to Pages; no secret is needed.

## Checklist

- [ ] earlier contents of the address backed up and renamed or archived; nothing of them pushed into this
      repository
- [ ] repository created; wiki off; labels created
- [ ] `codeowners/errors` returns no errors
- [ ] workflow token read-only; Actions may not approve pull requests
- [ ] `CLAUDE_CODE_OAUTH_TOKEN` (or `ANTHROPIC_API_KEY`) and the Claude GitHub App only when the agents are used
- [x] `main` ruleset applied (one approval, no code-owner requirement, required checks, no bypass actor)
- [x] `v*` tag ruleset; `pypi` environment; PyPI trusted publisher (the environment's required reviewers and
      `v*` tag policy once the repository is public: GitHub offers them free only on public repositories)
- [x] reviewers beyond the owner added (more join as they are invited)
- [ ] GitHub Pages source set to GitHub Actions (the graph explorer)
