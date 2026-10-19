"""Product lumps (issue #39): ProductLump and SUBSET_OF in the catalysis schema, and the validator's selectivity-sum check
that reads them. Every document is a public synthetic example, or one built in memory from it.

Each case below states its outcome: nested lumps are not parts of one partition, overlapping carbon windows with no
declared containment are reported, a lump is never judged by its window alone, an ill-formed lump or containment is an
error, and the competency question CQ-12 selects "C5+" across two documents by the lump's properties, never by id."""

import copy

import pytest

from conftest import EXAMPLES, REPO, spec_of
from scale import pgraph
from scale.competency import run_question
from scale.util import load_doc

D = EXAMPLES / "scale-catal/product-measurement-examples"
A, B = "ex:lumps-a", "ex:lumps-b"
TEST = f"{A}/test/cat-12h"


def _doc(name: str = "product-lumps-cheng-like.json") -> dict:
    return load_doc(D / name)


def _rep(doc):
    return pgraph.validate(doc, spec_of(doc))


def _errors(doc) -> list[str]:
    return [e["message"] for e in _rep(doc).errors]


def _sel_warnings(doc) -> tuple[list[str], list[str]]:
    """(the selectivity-sum warnings, the lump-overlap warnings) of the document."""
    msgs = [w["message"] for w in _rep(doc).warnings]
    return ([m for m in msgs if m.startswith("selectivities to")], [m for m in msgs if "product lumps" in m])


def _lump(doc, key):
    return next(n for n in doc["nodes"] if n["id"] == f"{A}/lump/{key}")["props"]


def _results(doc) -> dict:
    return next(n for n in doc["nodes"] if n["id"] == TEST)["props"]["results"]


def _link_subset(doc, inner, outer, name):
    doc["links"].append({"id": f"{A}/link/{name}", "type": "SUBSET_OF", "source": f"{A}/lump/{inner}",
                         "target": f"{A}/lump/{outer}", "props": {"origin": "synthetic"}})


def _only(doc, *keys):
    """The document with only the selectivities of ``keys`` (lump keys; ch4 is a species) left in the results."""
    d = copy.deepcopy(doc)
    r = _results(d)
    keep = {k.replace("-", "_") for k in keys}
    for k in [k for k in r if k.startswith("selectivity_") and k[len("selectivity_"):] not in keep]:
        del r[k]
    return d


def _drop_subset(doc, inner=None):
    d = copy.deepcopy(doc)
    d["links"] = [e for e in d["links"] if not (e["type"] == "SUBSET_OF" and (inner is None or e["source"].endswith(inner)))]
    return d


def test_the_cheng_like_document_is_valid_and_its_nested_lumps_are_not_summed():
    """Expected: valid, no error; no selectivity-sum warning, though CH4, C2-C4, C5+, C5-C11, C10-C20 and C21+ add to
    175 %: the three lumps inside C5+ are left out of the partition by SUBSET_OF, and the rest sum to 95 %."""
    doc = _doc()
    assert _errors(doc) == []
    assert sum(v["value"] for k, v in _results(doc).items() if k.startswith("selectivity_")) == 175.0
    sums, overlaps = _sel_warnings(doc)
    assert sums == []
    # the one thing the document is warned about: C5-C11 and C10-C20 share C10-C11 and neither lies inside the other
    assert len(overlaps) == 1 and "c5-c11" in overlaps[0] and "c10-c20" in overlaps[0], overlaps


def test_without_subset_of_the_same_selectivities_sum_above_100():
    """Expected: warns. With no containment declared the six selectivities are read as one partition (175 % > 100), and
    the windows that intersect (C5+ with each lump inside it, C5-C11 with C10-C20) are reported as overlaps: the
    containment is stated by SUBSET_OF, never inferred from the carbon windows."""
    doc = _drop_subset(_doc())
    sums, overlaps = _sel_warnings(doc)
    assert len(sums) == 1 and "sum to 175" in sums[0]
    assert len(overlaps) == 4        # C5+ with C5-C11, with C10-C20 and with C21+; C5-C11 with C10-C20


def test_a_lump_that_contains_any_other_lump_of_the_group_is_left_out_of_the_sum():
    """Expected: no sum warning, one overlap warning. Only C5-C11 is declared inside C5+, yet C5+ (80) is left out of the
    sum as a container (8.7 + 11.3 + 40 + 30 + 5 = 95); the overlap of C5-C11 with C10-C20 is reported. C5+ is not reported
    as overlapping C10-C20 and C21+, which are not declared inside it: a container is left out before the overlap check
    (a known limit of the rule: an undeclared containment under a declared one goes unseen)."""
    doc = _drop_subset(_doc())
    _link_subset(doc, "c5-c11", "c5-plus", "only")
    sums, overlaps = _sel_warnings(doc)
    assert sums == []
    assert len(overlaps) == 1 and "c5-c11" in overlaps[0] and "c10-c20" in overlaps[0]


def test_subset_of_is_followed_transitively():
    """Expected: no sum warning. C5-C11 inside C5-C20 inside C5+ (declared as two links): only the innermost lump of the
    chain is summed, so 40 + 80 + 90 never add up to 210 %."""
    doc = _only(_doc(), "c5-plus", "c5-c11", "c10-c20")
    doc = _drop_subset(doc)
    mid = copy.deepcopy(_lump(doc, "c5-c11"))
    mid.update(carbon_max=20, definition="C5-C20")
    doc["nodes"].append({"id": f"{A}/lump/c5-c20", "label": "ProductLump", "props": dict(mid, name="C5-C20")})
    rep_in = next(e for e in doc["links"] if e["type"] == "REPORTED_IN" and e["source"].endswith("lump/c5-c11"))
    doc["links"].append(dict(copy.deepcopy(rep_in), id=f"{A}/link/rep-c5-c20", source=f"{A}/lump/c5-c20"))
    _results(doc)["selectivity_c5_c20"] = dict(_results(doc)["selectivity_c5_c11"], value=70.0,
                                               target=f"{A}/lump/c5-c20")
    _link_subset(doc, "c5-c11", "c5-c20", "a")
    _link_subset(doc, "c10-c20", "c5-c20", "b")
    _link_subset(doc, "c5-c20", "c5-plus", "c")
    assert _errors(doc) == []
    sums, overlaps = _sel_warnings(doc)
    assert sums == []                                  # innermost C5-C11 (40) + C10-C20 (30) = 70; the rest are outer
    assert len(overlaps) == 1 and "c5-c11" in overlaps[0] and "c10-c20" in overlaps[0]


def test_an_innermost_partition_above_100_still_warns():
    """Expected: warns. Containment excludes outer lumps only: C2-C4 (11.3), C5-C11 (60) and C21+ (50), disjoint windows,
    sum to 121.3 % and are reported as one partition."""
    doc = _only(_doc(), "c2-c4", "c5-c11", "c21-plus", "c5-plus")
    r = _results(doc)
    r["selectivity_c5_c11"]["value"], r["selectivity_c21_plus"]["value"] = 60.0, 50.0
    sums, overlaps = _sel_warnings(doc)
    assert len(sums) == 1 and "sum to 121.3" in sums[0] and overlaps == []


@pytest.mark.parametrize("a, b, cls_a, cls_b, warns, why", [
    ((5, 11), (10, 20), "hydrocarbon", "hydrocarbon", True, "the windows share C10-C11"),
    ((5, 9), (10, 20), "hydrocarbon", "hydrocarbon", False, "adjacent windows do not intersect"),
    ((5, 11), (11, 20), "hydrocarbon", "hydrocarbon", True, "one shared carbon number is an overlap"),
    ((5, None), (21, None), "hydrocarbon", "hydrocarbon", True, "two open ends meet at infinity"),
    ((5, None), (2, 4), "hydrocarbon", "hydrocarbon", False, "an open end above a closed window does not reach it"),
    ((2, 4), (2, 4), "olefin", "paraffin", False, "the same window of two compound classes is no overlap"),
    ((2, 4), (2, 4), "olefin", "olefin", True, "the same window and class is an overlap"),
    ((2, 4), (3, 6), "olefin", "not_reported", True, "an unstated class may be either"),
    ((2, 4), (3, 6), "olefin", "other", True, "other names no class to compare"),
    ((2, 4), (3, 6), "olefin", "hydrocarbon", False, "two stated classes are compared as stated (containment is SUBSET_OF)"),
])
def test_overlapping_carbon_windows_without_containment_are_reported(a, b, cls_a, cls_b, warns, why):
    """Expected: an overlap warning exactly when the windows intersect and the compound classes agree or one is unstated."""
    doc = _only(_doc(), "c2-c4", "c5-plus")
    doc = _drop_subset(doc)
    for key, (lo, hi), cls in (("c2-c4", a, cls_a), ("c5-plus", b, cls_b)):
        p = _lump(doc, key)
        p.pop("carbon_max", None)
        p.update(carbon_min=lo, compound_class=cls, open_ended=hi is None)
        if hi is not None:
            p["carbon_max"] = hi
    sums, overlaps = _sel_warnings(doc)
    assert bool(overlaps) is warns, (why, overlaps)
    assert sums == []                                                  # 11.3 + 80 = 91.3


def test_declared_containment_silences_the_overlap_and_the_sum():
    """Expected: no warning. C5-C11 and C10-C20 overlap, but declaring one inside the other (as a source's definitions can,
    e.g. a gasoline cut stated to include the diesel's lower end) removes them from one partition."""
    doc = _only(_doc(), "c5-c11", "c10-c20")
    assert _sel_warnings(doc)[1], "the overlap is reported first"
    _link_subset(doc, "c10-c20", "c5-c11", "declared")
    assert _sel_warnings(doc) == ([], [])


def test_a_lump_without_a_window_is_never_judged_by_it():
    """Expected: no overlap warning. A lump the source defines by a boiling range alone (no carbon_min) has no window to
    compare, so nothing is inferred about its overlap with a lump that has one."""
    doc = _only(_doc(), "c5-c11", "c10-c20")
    for key in ("c5-c11", "c10-c20"):
        _lump(doc, key).pop("carbon_min")
    assert _errors(doc) == [] and _sel_warnings(doc) == ([], [])
    p = _lump(doc, "c5-c11")                                           # an open end without open_ended true is no window
    p.update(carbon_min=5)
    p.pop("carbon_max", None)
    p["open_ended"] = False
    _lump(doc, "c10-c20").update(carbon_min=10, carbon_max=20)
    assert _sel_warnings(doc) == ([], [])


def test_a_repeated_lump_is_a_series_not_a_partition():
    """Expected: no warning. Two selectivities on one lump (two times on stream, say) are a series; the sum check does not
    add them, as it never adds a repeated species."""
    doc = _only(_doc(), "c5-plus", "c2-c4")
    r = _results(doc)
    r["selectivity_c5_plus_late"] = dict(r["selectivity_c5_plus"], value=75.0)
    assert _sel_warnings(doc) == ([], [])


def test_a_lump_is_a_target_of_a_result_and_a_species_never_stands_in():
    """Expected: valid. A selectivity's target is a ChemicalSpecies or a ProductLump (context_targets); a Source still
    never is one."""
    doc = _doc()
    assert _errors(doc) == []
    _results(doc)["selectivity_c5_plus"]["target"] = f"{A}/source/paper"
    errs = _errors(doc)
    assert len(errs) == 1 and "is a Source" in errs[0], errs


def test_the_second_paper_is_valid_without_warning():
    """Expected: valid, no warning: C2-C4 and C5+ with their own ids, and no containment between them (C5+ starts at 5)."""
    rep = _rep(_doc("product-lumps-second-paper.json"))
    assert rep.errors == [] and rep.warnings == []


# ill-formed lumps and containment: the errors the counterexamples (domain/tests/fixtures/invalid) pin one by one

def test_subset_of_must_be_acyclic_and_join_lumps():
    """Expected: errors. A cycle of three lumps, a lump inside itself and a lump inside a species are each rejected."""
    doc = _doc()
    _link_subset(doc, "c10-c20", "c2-c4", "x")
    _link_subset(doc, "c2-c4", "c5-c11", "y")
    assert _errors(doc) == []                      # c10-c20 -> c2-c4 -> c5-c11 -> c5-plus: a chain, no cycle
    _link_subset(doc, "c5-plus", "c10-c20", "z")                               # c10-c20 -> c2-c4 -> c5-c11 -> c5-plus -> c10-c20
    errs = _errors(doc)
    assert errs and all("SUBSET_OF forms a cycle" in e for e in errs), errs
    own = _doc()
    _link_subset(own, "c5-c11", "c5-c11", "self")
    assert [e for e in _errors(own)] == ["a SUBSET_OF link joins a lump to itself"], _errors(own)
    species = _doc()
    species["links"].append({"id": f"{A}/link/sp", "type": "SUBSET_OF", "source": f"{A}/lump/c5-c11",
                             "target": f"{A}/species/ch4", "props": {"origin": "synthetic"}})
    assert len(_errors(species)) == 1 and "SUBSET_OF target must be" in _errors(species)[0]


def test_a_carbon_window_runs_upward_and_an_open_end_has_no_maximum():
    """Expected: errors. carbon_min above carbon_max, and an open-ended lump that names a carbon_max, are each rejected;
    carbon_min equal to carbon_max (a single carbon number, C1) and an open end without a maximum are valid."""
    doc = _doc()
    _lump(doc, "c5-c11").update(carbon_min=12)
    errs = _errors(doc)
    assert len(errs) == 1 and "carbon_min 12 is above carbon_max 11" in errs[0], errs
    doc = _doc()
    _lump(doc, "c5-c11").update(open_ended=True)
    errs = _errors(doc)
    assert len(errs) == 1 and "open-ended product lump has no carbon_max" in errs[0], errs
    doc = _doc()
    _lump(doc, "c5-c11").update(carbon_min=11)
    assert _errors(doc) == []


def test_a_lump_property_the_schema_does_not_declare_is_an_error():
    """Expected: error. A lump holds only the properties the schema declares (never an invented carbon_range)."""
    doc = _doc()
    _lump(doc, "c5-c11")["carbon_range"] = "5-11"
    errs = _errors(doc)
    assert len(errs) == 1 and "is not declared for this type" in errs[0], errs
    doc = _doc()
    _lump(doc, "c5-c11")["compound_class"] = "wax"
    errs = _errors(doc)
    assert len(errs) == 1 and "is not one of" in errs[0], errs


def test_cq_12_selects_c5_plus_across_two_documents_by_the_lumps_properties():
    """Expected: answered, two rows (80 % of the first document, 65 % of the second); the 55 % test and the C5-C11 lump
    are left out; the lumps have different ids in the two documents (nothing is shared but their properties)."""
    q = REPO / "domain/competency/cq-12-product-lumps.yaml"
    res = run_question(REPO, "catalysis", q)
    assert res["ok"] and not res["problems"], res
    assert res["answer"]["status"] == "answered" and res["answer"]["rows"] == 2
    a, b = _doc(), _doc("product-lumps-second-paper.json")
    ids = lambda d: {n["id"] for n in d["nodes"] if n["label"] == "ProductLump" and n["props"]["name"] == "C5+"}  # noqa: E731
    assert ids(a) and ids(b) and not ids(a) & ids(b)
