# Science-kernel examples (synthetic)

Worked cases of the science kernel ([`core/graph/kernel.yaml`](../graph/kernel.yaml)) on its own,
without the catalysis domain. Every value is invented; each document says so
(`data_status: synthetic_example`, `origin: synthetic`).

| file | what it shows |
|---|---|
| `science-kernel-only.yaml` | A manifest naming only the kernel: documents that use only kernel labels and edges validate against it. |
| `science-examples/*.json` | Five cases (a designed series, a computation validated by experiment, an inconsistent reference, a meta-analysis, an autonomous campaign), each pinning the schema version it was written under and valid against the kernel alone at that version. Built by `science-examples/build_examples.py`. |

```bash
scale graph validate core/examples/science-examples/*.json   # each under the version it pins (the head, or its frozen copy)
scale domains check                                         # among its checks: each case against the kernel alone, at the version it pins
python core/examples/science-examples/build_examples.py     # rebuilds them (core/tests/test_science_kernel.py checks they are unchanged)
```

`scale graph validate … --spec core/examples/science-kernel-only.yaml` validates against the kernel alone at the
head version, so it applies only to documents that pin the head version: once a schema change has raised the version, the
cases (which keep pinning the version they were written under) are read under that version's frozen kernel, as
`scale domains check` does.
