# From comments to changes

SCALE is evolving, and every comment helps. This page explains how to comment, how to have a change
drafted, and how changes are decided: by two approving reviews of a pull request.

## Commenting

| you want to… | do this |
|---|---|
| say anything | open a **[Comment or suggestion](https://github.com/hlxin/scale/issues/new?template=comment.yml)**; no schema knowledge needed |
| comment on a specific record | click 💬 next to it in a record catalogue (`scale catalogue <document>` renders one; the link opens a pre-filled form) |
| suggest a paper or dataset | **[Suggest a source](https://github.com/hlxin/scale/issues/new?template=new-source.yml)** |
| ask what the graph should answer | **[A question the graph should answer](https://github.com/hlxin/scale/issues/new?template=competency-question.yml)** |
| discuss an idea | **[Discussions](https://github.com/hlxin/scale/discussions)**, once they are on, or a comment issue |
| comment on a proposed change | comment on the pull request, or on any line of it |
| have a change drafted | ask a collaborator, or (people with write access) start the scale-agent workflow by hand with what you want; the agent opens a draft pull request |
| find schema gaps in open-access sources | open a `gap-report` issue with a sample curated against the schema (the curate-source skill; short capped quotes only) |
| report a wrong value, a missing concept or a source problem | the specific issue forms (optional; the general form works too) |

From the command line, `scale suggest --record <id> --text "…"` prints the same pre-filled link.

## What happens next

```
an issue or a request ──► a pull request (a collaborator, or a draft ──► two approving reviews ──► merge
                          by the agent when a person starts it)          (a schema proposal is then applied
                                                                          and the version moves on)
comments, issues, review comments, discussions
        │  weekly (and on demand): scale triage ingest
        ▼
queue.json — normalized items, references (records, classes, DOIs, gaps, CQs), categories, topics
        │  scale triage propose   (built-in rules, optionally refined by any agent system)
        ▼
proposals.json — per topic: options A/B/C, consequences (validated; no decisions)
        │  scale triage publish
        ▼
feedback digest issue (label feedback-digest) ──► a person opens a pull request on a topic;
                                                   its reviews decide
```

- Each thread you took part in gets a link to the digest, so you can follow the discussion.
- Topics are grouped: replies, "+1"s, near-duplicate issues and anything that mentions the same
  record, gap, proposal or competency question end up together.
- Categories suggest the path. Only a **missing concept** can lead to a schema change; a new concept
  enters as provisional, through a proposal whose pull request needs two approving reviews from
  reviewers other than its author ([GOVERNANCE.md](GOVERNANCE.md)). Wrong values go to re-curation.
  Silent or ambiguous sources are recorded as such. Questions get answers.
- Comment text is treated as data. Neither the triage system nor the agent follows instructions written
  in comments about permissions, workflows, governance or secrets.

## Decisions

Nothing is decided in the digest or in a comment. A change is decided by the reviews of its pull request:
two approvals from reviewers other than its author, and no reviewer asking for changes (until the reviewer
seats are filled, the owner merges under the bootstrap rule, [GOVERNANCE.md](GOVERNANCE.md)). A schema proposal
merged that way is then applied, which writes its decision record.

## For agent systems: proposing

Any agent system can produce the proposals. No particular model or framework is assumed.

- **Input:** `queue.json` from `scale triage ingest` (or the `triage-run` artifact of the weekly
  workflow).
- **Procedure:** [`tools/skills/triage-feedback/SKILL.md`](../tools/skills/triage-feedback/SKILL.md).
- **Output:** `proposals.json` valid against
  [`tools/skills/triage-feedback/proposal.schema.json`](../tools/skills/triage-feedback/proposal.schema.json).
- **Check:** `scale triage propose <dir> --proposals proposals.json --strict`.
- **Automatic use:** set the repository variable `SCALE_TRIAGE_COMMAND` to a program. The weekly
  workflow calls it as `<program> <queue.json> <proposals.json>`. Invalid proposals are rejected
  and replaced by the rule-based ones.

Proposals may recommend an option with a rationale and a confidence. They may never contain a
decision.

## Running triage by hand

```bash
scale triage ingest --out run                      # since the last digest (uses gh; GH_TOKEN in CI)
scale triage propose run [--proposals p.json]      # writes run/digest.md
scale triage publish run                           # dry run; add --publish to open the digest issue
```

`--from-file` accepts exported GitHub JSON for offline runs. Create the labels once from
`.github/labels.yml`. Discussions are optional: enable them in the repository settings to ingest them.
