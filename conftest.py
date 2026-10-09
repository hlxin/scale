"""The one shared pytest conftest: repository root, import path, fixtures and path constants.

Test modules in tools/tests, core/tests and domain/tests import from it (``from conftest import
REPO``); pytest puts the rootdir on sys.path, so no other conftest.py exists.
"""

import os
import sys
from pathlib import Path

import pytest


def _find_repo(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "scale-release.yaml").exists() and (p / "releases").is_dir():
            return p
    raise RuntimeError(f"no SCALE repository (scale-release.yaml and releases/) at or above {start}")


REPO = _find_repo(Path(__file__).resolve().parent)
# the domain template is a test fixture (new_domain() copies it into temporary repositories); its starter tests
# are templates with placeholders, not tests of this repository
collect_ignore_glob = ["tools/tests/fixtures/domain-template/*"]
os.environ.setdefault("SCALE_NO_UPDATE_CHECK", "1")   # tests never contact the remote
sys.path.insert(0, str(REPO / "tools"))

from scale import layout  # noqa: E402
from scale.util import load_yaml  # noqa: E402

CORE = REPO / layout.CORE
KERNEL = REPO / layout.KERNEL
KERNEL_FROZEN = REPO / layout.KERNEL_FROZEN                    # the kernels of frozen versions (kernel-<v>.yaml)
CATALYSIS = REPO / layout.DOMAIN
# two layers: the science kernel (core/) and the catalysis domain (domain/), whose graph schema manifest
# assembles the kernel with the catalysis file (catalysis.yaml), which carries the one checklist
GRAPH_MANIFEST = CATALYSIS / layout.DOMAIN_GRAPH_MANIFEST
GRAPH_FROZEN = layout.frozen_graph_dir(GRAPH_MANIFEST)       # its frozen versions (scale-graph-<v>.yaml, v<v>/), once any
EXAMPLES = CATALYSIS / layout.DOMAIN_EXAMPLES
DRIVING_FORCE_EXAMPLES = EXAMPLES / "scale-graph/driving-force-examples"   # public synthetic examples
COMPETENCY = CATALYSIS / layout.DOMAIN_COMPETENCY
FIXTURES = CATALYSIS / "tests/fixtures"
PROPOSALS = CATALYSIS / layout.DOMAIN_PROPOSALS                 # the catalysis domain's schema change proposals


@pytest.fixture(scope="session")
def repo():
    return REPO


# The schema's one version (kernel and catalysis together), read from the manifest: every applied proposal raises it
# (the automatic version bump), so a test never spells the head version. A test about what a document pins reads it
# from the document and loads that version with schema_at(), which finds the head while the head is at it and the
# frozen copy after a later proposal moved the head on.
HEAD_VERSION = load_yaml(GRAPH_MANIFEST)["version"]          # the schema's one version (scale-graph)


def schema_at(version: str) -> Path:
    """The catalysis schema manifest at ``version``: the head manifest while the head is at that version, else its
    frozen copy (an error when neither exists)."""
    from scale import pgraph
    return pgraph.pinned(GRAPH_MANIFEST, version)


def spec_at(version: str) -> dict:
    """The assembled catalysis schema at ``version`` (see :func:`schema_at`)."""
    from scale import pgraph
    return pgraph.load_spec(schema_at(version))


def kernel_of(manifest: Path) -> Path:
    """The kernel file a catalysis schema manifest assembles (the head kernel, or a frozen one for a frozen version)."""
    return layout.manifest_kernel(Path(manifest)).resolve()


def spec_of(doc: dict) -> dict:
    """The assembled schema a document pins (checked by :func:`pinned_schema`): a document stays valid under the
    version it pins, whatever the head is now; moving it is ``scale graph migrate``'s job, never a test's assumption."""
    from scale import pgraph
    return pgraph.load_spec(pinned_schema(doc))


def pinned_schema(doc: dict) -> Path:
    """The catalysis schema manifest a document pins, checked: the head version or a frozen one, whose kernel is the
    core's (the head kernel for the head, the frozen kernel of that version for a frozen version; never a copy in
    the domain)."""
    from scale import pgraph
    v, head = doc["graph"]["schema_version"], HEAD_VERSION
    frozen = sorted(p.name.removeprefix("scale-graph-").removesuffix(".yaml") for p in GRAPH_FROZEN.glob("scale-graph-*.yaml"))
    assert v == head or v in frozen, f"pins scale-graph {v}: neither the head {head} nor a frozen version {frozen}"
    path = pgraph.spec_for(REPO, v, doc=doc)
    assert path == (GRAPH_MANIFEST if v == head else GRAPH_FROZEN / f"scale-graph-{v}.yaml"), path
    kernel = layout.manifest_kernel(path).resolve()
    assert kernel == (KERNEL.resolve() if v == head else (KERNEL_FROZEN / f"kernel-{v}.yaml").resolve()), kernel
    return path


def as_project_data(doc: dict, project: str | None = None, contributed_by: list[str] | None = None) -> dict:
    """A synthetic example dressed, in memory, as a project's research data: ``data_status: research_data``, access
    ``project`` and the origins a curator records (``reported`` for a record that carries evidence, ``curated``
    otherwise). Every committed document is synthetic and public; the tests of research-data and stewardship rules
    need this form."""
    import copy
    d = copy.deepcopy(doc)
    st = (d["graph"].get("stewardship") or {})
    d["graph"].update(data_status="research_data", stewardship={
        "access": "project", "contributed_by": contributed_by or st.get("contributed_by") or ["ex:exmpl/org/example-lab"],
        "project": project or st.get("project") or "ex:exmpl/project/examples"})
    for r in d["nodes"] + d["links"]:
        p = r.setdefault("props", {})
        if p.get("origin") == "synthetic":
            p["origin"] = "reported" if p.get("evidence") else "curated"
    return d
