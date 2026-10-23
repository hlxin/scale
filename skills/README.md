# Skills

Each skill is a versioned procedure a person or an agent follows (`SKILL.md`, with the files it points to). SCALE's
tools do the checking; the skill says what to read, record or decide. The skills serve one chain, from a topic to
answers:

> **index-sources** → a frozen corpus → **fetch-corpus** → its files → **curate-corpus** → scale-catal documents →
> **query-graph**, **map-coverage**, **scan-conflicts** → **export-graph**; **evolve-schema** for what the schema cannot
> express yet

| Skill | What it does |
|---|---|
| [index-sources](index-sources/SKILL.md) | find and index the sources of a topic (papers, preprints, patents, theses, reports, and the datasets found with them) into an index that keeps their access, licence and supporting information, and freeze the corpus a question needs |
| [fetch-corpus](fetch-corpus/SKILL.md) | fetch a frozen corpus's files (PDFs and supporting information; paywalled ones only through the library's proxy) and record in the corpus what was fetched and what was not |
| [curate-corpus](curate-corpus/SKILL.md) | curate one publication, one data file or a frozen corpus into scale-catal documents, with evidence on every statement and typed absences |
| [query-graph](query-graph/SKILL.md) | answer a question with a graph query plan, rows as reported with their evidence |
| [map-coverage](map-coverage/SKILL.md) | map what the documents cover (materials by properties by conditions) and each kind of absence |
| [scan-conflicts](scan-conflicts/SKILL.md) | find values that seem to disagree and classify each pair as genuine, apparent or not comparable |
| [export-graph](export-graph/SKILL.md) | hand a document to another system, validated, capped and filtered for its audience |
| [evolve-schema](evolve-schema/SKILL.md) | turn missing-concept gaps or a request into one reviewable schema change |
| [triage-feedback](triage-feedback/SKILL.md) | sort community feedback into topics and options for the reviewers (maintainers) |

## Which skill for a request

| The request | Skill |
|---|---|
| a topic: "find / index / list sources", "newer sources" | index-sources |
| "download the PDFs", "get the papers of …" | index-sources freezes a corpus (or take a frozen one), then fetch-corpus |
| a topic: "build the graph / curate / extract the data" | index-sources, freeze a corpus, fetch-corpus, then curate-corpus |
| one source, a DOI, a PDF, or a data file to record | curate-corpus |
| an unfinished curation run, or "continue" | curate-corpus (references/runs.md) |
| "what do the sources report about …" | query-graph |
| "what is covered / where are the gaps" | map-coverage |
| "do the sources disagree about …" | scan-conflicts |
| "export / share the graph" | export-graph; a contribution to a graph in `graphs/` only when a person asks |
| a concept the schema lacks | evolve-schema (a person decides) |

What catalysis brings to the literature skills (the topic vocabulary index-sources uses, the catalysis index's
tools) is kept with the commons, in [graphs/catal-commons/literature/](../graphs/catal-commons/literature/README.md).
The curation rules follow SCALE's schema, whose one domain is catalysis (`domain/`).

`curate-source` and `curate-dataset` were merged into curate-corpus; `scale call skills` still finds it by those names.
`index-sources` was named paper-acquisition; its download mode is now fetch-corpus.
