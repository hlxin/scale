# Kernel proposals

Schema change proposals that touch the science kernel (`graph/kernel.yaml`), one directory each, named by
its six-digit number. Numbers are global across `core/proposals/` and `domain/proposals/`; `scale proposal
new core --title "…"` allocates the next one and scaffolds `proposal.yaml`. How to write and check one:
[tools/skills/evolve-schema/SKILL.md](../../tools/skills/evolve-schema/SKILL.md).

The schema has one version for the kernel and the catalysis domain together, so a kernel proposal raises the
same version as a catalysis proposal; it is assessed through the catalysis manifest
(`domain/graph/scale-graph.yaml`), the one manifest that uses the kernel.

No proposal has been made yet: the schema is at 0.1.0.
