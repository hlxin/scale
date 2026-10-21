# TRACE-AI on scale-catal records

TRACE-AI (Xin et al., *Transparent reporting for agentic catalysis enabled by artificial intelligence: community
guidelines and a publication checklist*, Chem Catal. 2026, [doi:10.1016/j.checat.2026.101755](https://doi.org/10.1016/j.checat.2026.101755);
the checklist, version 2.2.0, at [trace-ai-org/trace-ai-checklist](https://github.com/trace-ai-org/trace-ai-checklist))
asks a paper on catalysis enabled by AI to report its data (A1-A5), its models (B1-B5), its workflow (C1-C5) and its
executable artifacts (D1-D3). SCALE records what a source reports; `scale trace-ai` reads the checklist on those
records.

```bash
scale trace-ai G.json                     # the whole graph, as markdown
scale trace-ai G.json --source ex:src/1   # one source's records
scale trace-ai G.json --format json       # with the records, rows and evidence of every need
scale call trace_ai '{"path": "G.json"}'  # the same for an agent (scale_trace_ai)
```

## What it says, and what it does not

For each item, the crosswalk ([domain/reporting/trace-ai.yaml](../domain/reporting/trace-ai.yaml)) gives the condition
under which it applies and what it needs, each need a set of query plans ([querying.md](querying.md)) or a named check
(the metrics' uncertainty). The report gives each item one status:

| status | meaning |
|---|---|
| supported | every need is found (any one, for A5) |
| partial | some are |
| gap | none is |
| not applicable | the item's condition finds no record (the reason names the condition, e.g. no adaptive or autonomous campaign) |
| check by hand | the records cannot show it; the report says what a person reads in the source |
| not assessed | the document's schema version cannot express what the item needs (migrate it: `scale graph migrate`) |

It also lists what deserves a second look (a random split, a metric stated as one number, a model said to give point
predictions only), the records a person reads for an item checked by hand, and how the records were curated.

The report says what the **curated records** show. A need not found may be missing from the source (a value
`not_reported` with `not_stated_in_source`) or only from the curation (`not_curated`). It never decides that a source
satisfies TRACE-AI: its authors fill the checklist, and a reviewer reads it.

## The items and the records they read

| item | what TRACE-AI asks (in SCALE's words) | what the report reads |
|---|---|---|
| A1 | how data of several origins were harmonized | by hand (SCALE keeps values as reported and converts nothing) |
| A2 | code that regenerates the model-ready dataset | the training data with its location; the software of the experiment that produced it |
| A3 | the input features and how they were generated | a Descriptor the model or its calculation uses, with its definition |
| A4 | dataset identifiers, access and metadata | a Dataset with a uri or identifier, and a licence or availability |
| A5 | the policy on failed and negative experiments | a Design's negative_results_policy, failed or aborted experiments, or exclusions (any one) |
| B1 | the model's specification | a machine-learned model's version, architecture, hyperparameters and training objective |
| B2 | how the data were split against leakage | a validation's split_strategy (flagged when random) |
| B3 | metrics with their uncertainty | every metric of a validation or benchmark with an uncertainty or interval |
| B4 | why these metrics; trade-offs | by hand (the campaign's objectives are listed to read) |
| B5 | uncertainty method, calibration and use | the model's uncertainty_method, uncertainty_calibration and uncertainty_use |
| C1 | the agent's policy, objectives and configuration | the Design's agent_policy and objectives; the agent (Software) with its version |
| C2 | autonomy level, oversight and interventions | the Design's autonomy_level and human_oversight; interventions, their count, or human_decision on proposals |
| C3 | stopping, failures, exclusions and later corrections | stopping_criterion, stop_reason, and exclusions, post_hoc_changes or failed runs |
| C4 | safety bounds and interlocks | safety_bounds and safety_measures (applies when the campaign ran physical experiments) |
| C5 | a traceable trajectory | the runs' iteration or run_order, and who proposed each (PROPOSED_BY) |
| D1 | executable notebooks | a Dataset of data_kind notebook |
| D2 | notebooks linked to sections and items | by hand (the notebooks are listed to read) |
| D3 | the execution environment | an experiment's execution_environment, or a Dataset of data_kind environment |

B items apply when a machine-learned model is recorded; C items when an adaptive or autonomous campaign is (a Design of
kind adaptive, or one that states an autonomy_level); D items when either is.

## Recording an agentic campaign

A campaign in which an agent chooses the next experiments is a `Design` of kind `adaptive`. It states, as the source
does, its `autonomy_level` on TRACE-AI's scale (A0 manual; A1 decision support; A2 supervised autonomy, a person
approves each execution; A3 conditional autonomy, review by exception; A4 continuous autonomy; A5 distributed autonomy
across sites; `not_reported` when the source names no level, with its description in `human_oversight`), its
`interventions`, `agent_policy`, `objectives`, `safety_bounds` and `safety_measures`, `stopping_criterion` and
`stop_reason`, `negative_results_policy`, `exclusion_criteria` and `excluded_count`, and `post_hoc_changes`. Each run
is `PART_OF_DESIGN` with its `iteration` and `PROPOSED_BY` the agent (a `Software` of kind `agent`, with its version),
with the `human_decision` about the proposal; a proposal a person rejected is a record too (an `Experiment` that stays
`proposed`). A machine-learned model states its `architecture`, `hyperparameters`, `training_objective`, `pretraining`
and `uncertainty_method`; each validation (`EVALUATES`) states its `split_strategy` and, for a grouped split,
`grouped_by`. The example [agentic-examples/self-driving-campaign.json](../domain/examples/scale-catal/agentic-examples/self-driving-campaign.json)
records one, with CQ-29 and CQ-30.

## How the records were curated

TRACE-AI asks a paper whose data were extracted by AI agents to say what the agents did, how people intervened and how
the extraction's quality was measured. SCALE asks the same of its own graphs:

- `stewardship.autonomy_level` (the graph's, or a record's) says how much of the curation an agent did, on TRACE-AI's
  scale read for extraction: A0 people curated the records; A1 an agent proposed records and a person chose; A2 an
  agent extracted them and a person approved each; A3 an agent extracted them and people checked a sample and the
  flagged ones (governance/review-policy.yaml); A4 nobody checked them.
- `graph.checks` records each check a person made (a `record_check`): `checked_by` (a Person), `checked_on`, the
  `records`, how they were chosen (`selection`, with the sample's `fraction` and `seed`), `scope` (what against what),
  `fields_checked`, `fields_wrong` and `fields_missed` (precision 1 - wrong/checked; recall right/(right + missed)),
  `tolerance`, `outcome` (passed, corrected, failed) and the warnings `acknowledged`, each with the record, the warning's
  text and the reason it stays. Validation lists an acknowledged warning apart from the open ones, and reports an
  acknowledgement that no longer matches a warning, and a check of a record that a newer record revises.

```bash
scale review sample G.json --include-flagged     # the records to check, and the check to fill in afterwards
```

After the check, the agent that curated the graph adds the filled check to `graph.checks` (who checked, when, the
counts and the outcome, as the person reports them), in the same pull request as any correction. A check approves
nothing; a person's review of the pull request does.
