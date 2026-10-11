# Style: formats and names

`scale lint` checks everything on this page, and CI runs it together with `scale fmt --check`.

## Formats: chosen by who writes the file

| content | written by | format |
|---|---|---|
| specifications (the kernel, the catalysis file, schema manifests), the catalysis and kernel declarations (`DOMAIN.yaml`, `CORE.yaml`), competency questions, skills metadata, project configuration, GitHub templates and workflows | people, reviewed line by line | **YAML**, block style |
| scale-catal documents, curation fragments, gap reports, decision log, tool input and output, query results, triage queues and proposals | tools and agents (sometimes people) | **canonical JSON** |
| exchange with other systems | — | Neo4j JSON lines and kg-bundles (`scale graph export`) |

Tools accept YAML input anywhere a JSON document is expected, and write JSON.

### YAML rules

- **Block style only.** Inline `{a: b}` mappings are not allowed, and neither are inline `[...]`
  lists that contain mappings or lists. An unquoted comma, colon or question mark inside them
  silently changes meaning or breaks parsing. Short lists of plain values
  (`allowed_units: [V, mV]`) and empty `{}` / `[]` are fine.
- **No ambiguous YAML 1.1 scalars.** Quote `yes`, `no`, `on`, `off`, `y` and `n` when they are
  meant as text or keys (for example the GitHub workflow key `"on":` and the slot `'n'`).
- No duplicate keys; no tabs in indentation.
- Archived `releases/` and frozen schema versions are historical records and are not reformatted.
- Directories holding a `.scale-verbatim` marker contain artifacts adopted as-is from an external
  source (e.g. the catalysis schema draft); they are exempt from reformatting so their digests stay valid.

### Canonical JSON

`scale fmt` writes JSON with:
- a fixed key order: identity first (`id`, `type`, `predicate`, `subject`, `object`, `label`, …),
  then alphabetical;
- two-space indentation, UTF-8 without escaping, and a trailing newline.

The same content always produces the same bytes, so diffs show only real changes and digests are
stable, whichever tool or agent wrote the file.

## Names

| thing | style | examples |
|---|---|---|
| labels | PascalCase | `CatalyticTest`, `CatalystSample`, `LightSource` |
| edge types | UPPER_SNAKE_CASE | `USES_CATALYST`, `REPORTED_IN`, `CONTROL_FOR` |
| properties, enum values | snake_case | `faradaic_efficiency`, `driving_forces`, `potentiostatic` |
| record ids | `prefix:` + path (CURIE-like), unique across nodes and links | `ex:df-electro/test/m03` |
| units | as the source printed them, in a value object's `unit` | `mA/cm2`, `umol/(g*h)` |

- **Exception:** established scientific symbols keep their usual form. At present that is `pH`.
- **External terms** keep their own spelling through mappings. `generated_by` maps to
  `prov:wasGeneratedBy`; nothing in SCALE is renamed to follow another vocabulary's case.
- **Graph databases:** an export may render predicates as `UPPER_SNAKE` (e.g. `GENERATED_BY`)
  without changing stored names.
- **scale-catal** (`core/graph/`, `domain/graph/`) follows the labeled-property-graph convention:
  | thing | style | examples |
  |---|---|---|
  | node labels | PascalCase, one word, no spaces or slashes | `CatalyticTest`, `ChemicalSpecies`, `Institution` |
  | edge types | `UPPER_SNAKE_CASE`, stored as such | `USES_CATALYST`, `HAS_COMPONENT` |
  | node and edge properties, enum values | snake_case | `test_kind`, `fraction_basis`, `equilibrium_estimate` |
  | files keyed `domain:` | the domain's name (`domain:` in `domain/DOMAIN.yaml`): lowercase letters, digits and `-` | `catalysis` |
  | checklist references in documents (`follows_domains`) | the name of the checklist that applies | `catalysis` |
  | `when` case conditions in a checklist | a property of the label, then `any_of` or `all_of` of its enum values | `driving_forces: {all_of: [electro, photo]}` |
  | extension keys (outside the schema) | `_<prefix>_<name>`, prefix registered in `governance/registry/extension-prefixes.yaml` | `_exmpl_reactor_serial` |

  Diagrams and documents use these exact names; they do not merge labels ("A / B") or split them
  into words.
- **The domain folder** is `domain/`, one folder beside `core/` while catalysis is the only domain
  ([decision record 0001](decisions/0001-scale-0.1.0.md)); the domain's name is `domain:` in its
  `DOMAIN.yaml` (`catalysis`): lowercase letters, digits and `-`. Its issue label is `domain:catalysis`.
  A driving force (`thermo`, `electro`, `photo`, …) is a case of the catalysis checklist, not a domain.
- **Numbers:** the schema has one version, `MAJOR.MINOR.PATCH`, for the kernel and the catalysis domain
  together (0.1.0 today); a breaking change raises MINOR, an additive change PATCH. Decision records are numbered
  globally from 0001 and named by their subject (`0001-scale-0.1.0.md`).
  Release ids are `vX.Y.Z`.
- Identifiers are stable. A name that breaks these rules after release is fixed by deprecation
  with `superseded_by`, never by renaming in place.
