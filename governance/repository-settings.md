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
  Write access is enough on GitHub, and `scale proposal apply-merged` counts only the reviewers of the review policy.
- GitHub never lets the author of a pull request approve it.
- Events caused by the workflow token (`GITHUB_TOKEN`) do not start other workflows.
- Anyone with Write access can push a branch with a changed workflow and run it. Such a run can read every
  repository secret. Hence the secrets section below.
- Some protections depend on the plan: on a free personal account, rulesets and environment protection rules
  apply to public repositories only; a private repository needs GitHub Pro for them. Until then the rules of
  GOVERNANCE.md are kept by practice, and `scale proposal apply-merged` still checks the approval.

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

A personal repository has its owner and collaborators; every collaborator has Write access. Today the owner,
`@hlxin`, owns every path in [`.github/CODEOWNERS`](../.github/CODEOWNERS), and the review policy has two
reviewer seats that are placeholders (`TODO-reviewer-2`, `TODO-reviewer-3`).

**Filling a reviewer seat.** When a reviewer joins, a pull request replaces one placeholder with the person's
name and GitHub handle in `governance/review-policy.yaml`, `core/CORE.yaml` and `domain/DOMAIN.yaml` (remove
`placeholder: true`, add `since`) and adds the handle next to `@hlxin` on the lines of `.github/CODEOWNERS`; the
owner invites them as a collaborator:

```bash
gh api -X PUT repos/$OWNER/$REPO/collaborators/<handle>     # they accept the invitation
gh api repos/$OWNER/$REPO/codeowners/errors                 # must report no errors
```

Never write a name or handle that is not a real person who agreed to review. `scale check` warns while
placeholders remain. A code owner counts only with Write access, so a reviewer is invited before the
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
| `proposal-check` | every pull request | nothing |
| `triage` | weekly, or started by hand | nothing (it opens a digest issue with the workflow token, `issues: write`) |
| `apply-proposals` | **by hand**, from `main`, after a proposal's pull request merged | the secret `APPLY_TOKEN` (below) |
| `scale-agent` | **by hand**, from `main` (off otherwise) | the secret `ANTHROPIC_API_KEY` and the Claude GitHub App (below) |
| `publish` | a published GitHub release | the `pypi` environment and the trusted publisher (section 6); inert until configured |

## 4. Secrets

No secret is needed for the checks of a pull request. Two are optional, each for a workflow a person starts by
hand. A repository secret can be read by any workflow run from a branch, so add a secret only when its workflow
is used, and only while every collaborator is trusted with it; once the repository is public or on a plan with
environment protection rules, move each into an environment whose deployment policy is `main` only (`apply`,
`agent`) and name it in its job (`environment: apply`), so that only the reviewed workflow file on `main` can
read it.

### The apply token

The apply-proposals workflow pushes the application of a merged proposal (decision record, frozen version,
version bump) to `main`. The workflow token stays read-only; the push uses `APPLY_TOKEN`, a fine-grained personal
access token of the owner (or a GitHub App installation token) with **Contents: read and write** on `hlxin/scale`
only, and a short expiry:

```bash
gh secret set APPLY_TOKEN --repo $OWNER/$REPO        # prompts for the value
```

Without it the workflow stops at its first step and says so; the owner can always apply a proposal locally
instead, in a pull request (`scale proposal apply <id> --confirm`). The token can push to `main` because the
owner, a repository admin, may bypass the `main` ruleset (section 5): anyone who can read the secret can push
to `main`, which is why it is optional and kept to trusted collaborators.

### The agent

`@scale-agent` (Claude on GitHub, `anthropics/claude-code-action`) is off: its workflow starts only when a
person with write access runs it by hand (Actions → scale-agent → Run workflow). To use it, install the
**Claude GitHub App** (https://github.com/apps/claude) on `hlxin/scale` (contents, issues and pull requests,
read and write) and set the API key:

```bash
gh secret set ANTHROPIC_API_KEY --repo $OWNER/$REPO
```

The agent works on an `agent/…` branch and opens a draft pull request; it never approves, merges or applies.
Its commands run with the action's subprocess secret scrub (`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB: "1"`), and the
job's workflow token only reads the contents. Starting it from mentions in issues and comments needs an issue
and comment trigger in `.github/workflows/scale-agent.yml` and a check of who may start it (only the owner and
collaborators); that is a decision for the owner, made by pull request.

## 5. Branch ruleset for `main`

[`github/ruleset-main.json`](github/ruleset-main.json):

| rule | setting |
|---|---|
| changes only by pull request | required |
| approving reviews | **1** (any reviewer) |
| review from a code owner | not required (CODEOWNERS requests reviews from the owner and the reviewers) |
| dismiss approvals when new commits are pushed | yes |
| the last push must be approved by someone other than its author | yes |
| required status checks | `test (3.10)`, `test (3.11)`, `test (3.12)`, `test (3.13)`, `package`, `specification-changes`, `proposal-check`, from GitHub Actions (`integration_id` 15368) |
| branch must be up to date before merging | no (below) |
| force pushes, deletion | blocked |
| bypass | the repository admin role (the owner), always: the bootstrap rule and the apply token; never the GitHub Actions app |

```bash
gh api -X POST repos/$OWNER/$REPO/rulesets --input governance/github/ruleset-main.json
```

To change it later, edit the JSON by pull request, then
`ID=$(gh api repos/$OWNER/$REPO/rulesets --jq '.[] | select(.name == "main") | .id')` and
`gh api -X PUT repos/$OWNER/$REPO/rulesets/$ID --input governance/github/ruleset-main.json`.

**The GitHub Actions app is not a bypass actor.** Anyone with Write can push a branch whose workflow asks for
`contents: write` and runs `git push origin HEAD:main`; that run's workflow token must not get past the
approval.

**Up-to-date branches are not required.** `strict_required_status_checks_policy` is `false`: with it on, every
merge would force each open pull request to merge `main` again and, because approvals are dismissed on push, to
be approved again. Two pull requests that each pass alone can conflict once both are merged; CI
on `main` shows it at once. Two proposals built on the same schema version cannot both apply: the second is
refused, and its author rebuilds it on the new version.

### Bootstrap bypass

Until a reviewer besides the owner has Write access, the owner's pull requests cannot be approved by anyone
other than their author. The ruleset therefore lets the **repository admin role** (the owner, the only admin)
bypass it:

- the owner uses it only to merge pull requests whose checks pass, noting each use in the pull request
  ("Bootstrap bypass: reviewers not yet added"); GitHub does not enforce either, and the ruleset's bypass log
  shows each use (Settings → Rules → Insights). He does not push to `main` directly;
- `scale proposal apply-merged` does not count a bypass as approval: a proposal merged this way is applied by
  hand (`scale proposal decide <id> --pr <n> --bootstrap-bypass "<reason>" --by hlxin`, then
  `scale proposal apply <id> --confirm`, in a pull request), and the decision record says so;
- once a reviewer has joined, the bypass is narrowed to pull requests (`"bypass_mode": "pull_request"`)
  or removed, by a pull request that changes `ruleset-main.json`; the apply token then needs its own bypass
  (a GitHub App as an `Integration` actor) or proposals are applied in pull requests.

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
for the project `scale-schema`: owner `hlxin`, repository `scale`, workflow `publish.yml`, environment `pypi`.
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

## Checklist

- [ ] earlier contents of the address backed up and renamed or archived; nothing of them pushed into this
      repository
- [ ] repository created; wiki off; labels created
- [ ] `codeowners/errors` returns no errors
- [ ] workflow token read-only; Actions may not approve pull requests
- [ ] `APPLY_TOKEN` set only when the apply-proposals workflow is used (Contents read and write on this
      repository only); `ANTHROPIC_API_KEY` and the Claude GitHub App only when the agent is used
- [ ] `main` ruleset applied (one approval, no code-owner requirement, required checks, the admin role as the only bypass);
      the GitHub Actions app is not a bypass actor
- [ ] `v*` tag ruleset; `pypi` environment (`v*` tags); PyPI trusted publisher
- [ ] reviewer seats filled (a pull request each), then the bootstrap bypass narrowed or removed
