# Catalysis proposals

Schema change proposals of the catalysis domain, one directory each, named by its six-digit number (global across
the core and every domain: `core/proposals/` holds the kernel's). `scale proposal new catalysis --title "…"`
allocates the next number and scaffolds `proposal.yaml`; `scale proposal check <id>` builds and checks it. How to
write one: [tools/skills/evolve-schema/SKILL.md](../../tools/skills/evolve-schema/SKILL.md).

The schema has one version for the kernel and the catalysis domain together: every proposal raises it
(`target_version`), whichever file it changes. Once applied, the version it replaces is frozen in
`domain/graph/frozen/` (and its kernel in `core/graph/frozen/`), and the proposal's folder is kept as its record.

No proposal has been made yet: the schema is at 0.1.0. The synthetic proposal the tests use is in
[`tools/tests/fixtures/proposals/009001/`](../../tools/tests/fixtures/proposals/009001/).
