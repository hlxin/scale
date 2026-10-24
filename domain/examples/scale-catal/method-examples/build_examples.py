"""Build the synthetic example of the methods calculations apply, the failures on the way and the benchmarks of a
method (all values invented).

    python build_examples.py

  computational-methods.json
    the methods            four records the calculations name (USES_METHOD): the PBE, RPBE and BEEF-vdW
                           exchange-correlation functionals and the D3 dispersion correction, with their references and
                           libxc names
    a calculation          O on Pt(111) with RPBE, which USES_METHOD RPBE
    a dispersion method    O on Ni(111) with RPBE and D3: two methods, and level_of_theory names the functional
    failures and reruns    a nudged elastic band that found no saddle point and a self-consistent loop that did not
                           converge, each with its failure_kind and status_reason, and the rerun that succeeded with what
                           it changed (REPLICATES)
    a benchmark            PBE, RPBE and BEEF-vdW against twelve measured chemisorption energies: each benchmark
                           calculation EVALUATES its method (evaluation_kind benchmark), with its mean absolute and mean
                           signed errors; a claim about PBE drawn from it
"""

from __future__ import annotations

import sys
from pathlib import Path


def _repo_root(*starts: Path) -> Path:
    """The SCALE checkout (scale-release.yaml and releases/), searched upward from each start in turn."""
    for p in (q for s in starts for q in (s, *s.parents)):
        if (p / "scale-release.yaml").exists() and (p / "releases").is_dir():
            return p
    raise SystemExit("run inside a SCALE repository checkout: no scale-release.yaml and releases/ above "
                     + ", ".join(map(str, starts)))


HERE = Path(__file__).resolve().parent
REPO = _repo_root(HERE, Path.cwd())
sys.path.insert(0, str(REPO / "tools"))
from scale import layout  # noqa: E402
from scale.pgraph import derive_reported_in  # noqa: E402
from scale.util import write_canonical  # noqa: E402

SYN = "synthetic"
_HEAD = REPO / layout.DOMAIN / layout.DOMAIN_GRAPH_MANIFEST
HEAD_VERSION = __import__("yaml").safe_load(_HEAD.read_text())["version"]


def V(value, unit, **kw) -> dict:
    return {"status": "present", "value": value, "unit": unit, **kw}


def T(text, **kw) -> dict:
    return {"status": "present", "text_value": text, **kw}


def B(flag, **kw) -> dict:
    return {"status": "present", "boolean_value": flag, **kw}


def computational_methods() -> dict:
    p = "ex:cm"
    doc = {"directed": True, "multigraph": True,
           "graph": {"schema": "scale-catal", "schema_version": HEAD_VERSION, "graph_id": f"{p}/graph",
                     "title": "The methods calculations apply, where they failed, and how well a method does against "
                              "measurements (synthetic)",
                     "data_status": "synthetic_example", "follows_domains": ["catalysis"],
                     "stewardship": {"access": "public"}},
           "nodes": [], "links": []}
    n = [0]

    def node(rid, label, name, **props):
        nid = f"{p}/{rid}"
        doc["nodes"].append({"id": nid, "label": label, "props": {"name": name, "origin": SYN, **props}})
        return nid

    def link(typ, s, t, **props):
        n[0] += 1
        lid = f"{p}/link/{n[0]}"
        doc["links"].append({"id": lid, "source": s, "target": t, "type": typ, "props": {"origin": SYN, **props}})
        return lid

    def source(key, title):
        return node(f"source/{key}", "Source", f"Invented paper ({key})", kind="article", year=2026, title=title)

    dft = source("dft-paper", "Oxygen on Pt(111) and Ni(111) (invented)")
    bench = source("benchmark-paper", "Three functionals against measured chemisorption energies (invented)")

    def ev(src, locator, kind="text", **kw):
        return {"source": src, "locator": locator, "kind": kind, **kw}

    # ---- the methods: one record each, named by every calculation that applies it
    def method(key, name, kind, reference, **props):
        return node(f"method/{key}", "Method", name, method_kind=kind, reference=reference, **props)

    pbe = method("pbe", "PBE", "exchange_correlation_functional",
                 "Perdew, Burke and Ernzerhof, Phys. Rev. Lett. 1996, 77, 3865, doi:10.1103/PhysRevLett.77.3865",
                 functional_class="gga", identifiers={"libxc": "GGA_X_PBE+GGA_C_PBE"})
    rpbe = method("rpbe", "RPBE", "exchange_correlation_functional",
                  "Hammer, Hansen and Nørskov, Phys. Rev. B 1999, 59, 7413, doi:10.1103/PhysRevB.59.7413",
                  functional_class="gga", aliases=["revised PBE of Hammer, Hansen and Nørskov"],
                  identifiers={"libxc": "GGA_X_RPBE+GGA_C_PBE"})
    beef = method("beef-vdw", "BEEF-vdW", "exchange_correlation_functional",
                  "Wellendorff et al., Phys. Rev. B 2012, 85, 235149, doi:10.1103/PhysRevB.85.235149",
                  functional_class="gga", aliases=["BEEF"], identifiers={"libxc": "GGA_XC_BEEFVDW"},
                  note="its nonlocal (vdW-DF2) correlation is not a libxc functional")
    d3 = method("d3", "D3", "dispersion_correction",
                "Grimme, Antony, Ehrlich and Krieg, J. Chem. Phys. 2010, 132, 154104, doi:10.1063/1.3382344",
                version="zero damping")
    code = node("software/plane-wave-code", "Software", "plane-wave DFT code (invented release)",
                software_kind="application", version="7.1.0")
    inputs = node("dataset/inputs", "Dataset", "input files of every calculation (invented)", data_kind="configuration",
                  availability="available", version="1", sha256="0" * 64,
                  uri="https://example.org/invented/inputs.tar.gz")

    # ---- species, reactions, variables
    def species(key, formula, composition, name=None):
        return node(f"species/{key}", "ChemicalSpecies", name or formula, formula=formula,
                    elemental_composition=composition, charge=0)

    h2o, h2, o_ads = species("h2o", "H2O", {"H": 2, "O": 1}), species("h2", "H2", {"H": 2}), \
        species("o", "O", {"O": 1}, name="O (adsorbed)")

    def reaction(key, equation, parts, src):
        rid = node(f"reaction/{key}", "Reaction", equation, equation=equation, balance_status="balanced",
                   direction="forward", evidence=[ev(src, "Methods, reference energies")])
        for sp, role, coef, phase in parts:
            link("HAS_PARTICIPANT", rid, sp, role=role, coefficient=coef, phase=phase)
        return rid

    o_ads_rxn = reaction("o-adsorption", "H2O(g) + * -> O* + H2(g)",
                         [(h2o, "reactant", 1, "gas"), (o_ads, "product", 1, "adsorbed"), (h2, "product", 1, "gas")], dft)

    def variable(key, name, kind, unit):
        return node(f"variable/{key}", "Variable", name, scale="quantitative", quantity_kind=kind, unit=unit)

    v_eads = variable("o-adsorption-energy", "O adsorption energy", "reaction_energy", "eV")
    v_mae = variable("chemisorption-mae", "mean absolute error of chemisorption energies", "mean_absolute_error", "eV")
    v_mse = variable("chemisorption-mse", "mean signed error of chemisorption energies", "mean_signed_error", "eV")

    # ---- structure models
    def slab(key, name, metal, lattice_constant):
        return node(f"model/{key}", "StructureModel", name, composition=metal, facet="111",
                    representation="periodic_slab",
                    parameters={"supercell": T("p(3×3)"), "layers": V(4, "1"), "fixed_layers": V(2, "1"),
                                "vacuum": V(15, "Å"),
                                "lattice_constant": V(lattice_constant, "Å",
                                                      definition="optimized for the bulk metal at this level of theory")},
                    stored_in=node(f"dataset/{key}-structure", "Dataset", f"{name}, coordinates", data_kind="structure",
                                   availability="available", version="1", sha256="1" * 64,
                                   uri=f"https://example.org/invented/{key}.cif"))

    pt111 = slab("pt-111", "Pt(111) slab, p(3×3), 4 layers", "Pt", 3.99)
    ni111 = slab("ni-111", "Ni(111) slab, p(3×3), 4 layers", "Ni", 3.55)

    base_settings = {
        "cutoff_energy": V(450, "eV"), "kpoints": T("4×4×1", definition="Monkhorst-Pack"),
        "smearing": V(0.1, "eV", definition="Methfessel-Paxton, first order"),
        "scf_convergence": V(1e-6, "eV"), "force_convergence": V(0.02, "eV/Å"),
        "pseudopotentials": T("projector augmented-wave set of the code (invented release)"),
        "dipole_correction": B(True, definition="along the surface normal")}

    def computation(key, name, src, locator, *, model=None, methods=(rpbe,), level="RPBE", settings=None, **props):
        method_fields = {"dispersion": props.pop("dispersion", T("none")),
                         "spin_treatment": props.pop("spin_treatment", "non_spin_polarized"), "solvation": "none",
                         "charge_treatment": "constant_charge"}
        cid = node(f"computation/{key}", "Computation", name, computation_kind="electronic_structure",
                   level_of_theory=T(level),
                   settings=settings if settings is not None else dict(base_settings), configuration=inputs,
                   experiment_status=props.pop("experiment_status", "completed"),
                   evidence=props.pop("evidence", [ev(src, locator, "table" if locator.startswith(("Table", "Supporting"))
                                                       else "text")]), **method_fields, **props)
        for m in methods:
            link("USES_METHOD", cid, m)
        link("USES_SOFTWARE", cid, code, version="7.1.0")
        if model:
            link("USES_MODEL", cid, model)
        return cid

    # ---- 1. O on Pt(111)
    o_pt = computation("o-pt111", "O on Pt(111), RPBE", dft, "Table 1", model=pt111,
                       evidence=[ev(dft, "Table 1", "table", id="t1")],
                       result_values=[{"id": "o_adsorption", "status": "present", "value": 1.42, "unit": "eV",
                                       "variable": v_eads, "target": o_ads_rxn, "evidence_ids": ["t1"]}])

    # ---- 2. O on Ni(111): a self-consistent loop that did not converge at first
    ni_settings = {**base_settings, "initial_magnetic_moments": T("0.6 μB per Ni atom"),
                   "density_mixing": T("linear, 0.05")}
    o_ni = computation("o-ni111", "O on Ni(111), RPBE-D3, spin-polarized", dft, "Table 1", model=ni111,
                       methods=(rpbe, d3), dispersion=T("D3"), spin_treatment="spin_polarized", settings=ni_settings,
                       evidence=[ev(dft, "Table 1", "table", id="t1")],
                       result_values=[{"id": "o_adsorption", "status": "present", "value": 1.05, "unit": "eV",
                                       "variable": v_eads, "target": o_ads_rxn, "evidence_ids": ["t1"]}])
    ni_first = computation("o-ni111-first-attempt", "O on Ni(111), first attempt, started without magnetic moments", dft,
                           "Supporting information, section S3", model=ni111, spin_treatment="spin_polarized",
                           settings={**base_settings, "initial_magnetic_moments": T("zero on every atom"),
                                     "density_mixing": T("Pulay, the code's default")},
                           experiment_status="failed", failure_kind="electronic_not_converged",
                           status_reason="the self-consistent loop oscillated and had not converged after 200 electronic "
                                         "steps when started from zero magnetic moments")
    link("REPLICATES", o_ni, ni_first, level="repeat", changed=["method"],
         note="started from 0.6 μB per Ni atom, with linear density mixing of 0.05",
         evidence=[ev(dft, "Supporting information, section S3")])

    # ---- 3. O diffusion on Pt(111): a band that found no saddle point, and the rerun that did
    neb_settings = {**base_settings, "transition_state_method": T("CI-NEB", note="one imaginary frequency confirmed"),
                    "neb_images": V(9, "1")}
    neb_first = computation("o-diffusion-first-attempt", "O diffusion fcc to hcp on Pt(111), first band", dft,
                            "Supporting information, section S4", model=pt111,
                            settings={**base_settings, "transition_state_method": T("CI-NEB"),
                                      "neb_images": V(5, "1")}, experiment_status="failed",
                            failure_kind="saddle_point_not_found",
                            status_reason="the climbing image had not converged after 400 steps, and two images slid into "
                                          "the fcc minimum")
    neb = computation("o-diffusion", "O diffusion fcc to hcp on Pt(111), CI-NEB", dft, "Supporting information, section S4",
                      model=pt111, settings=neb_settings)
    link("REPLICATES", neb, neb_first, level="repeat", changed=["method"],
         note="nine images instead of five, the initial path from an interpolation of the end states' distances, and the "
              "climbing image switched on after the band's forces fell below 0.1 eV/Å",
         evidence=[ev(dft, "Supporting information, section S4")])

    # ---- 4. the benchmark: each functional against twelve measured chemisorption energies
    reference = node("dataset/measured-chemisorption", "Dataset",
                     "twelve chemisorption energies of small adsorbates on late transition-metal surfaces, measured by "
                     "single-crystal calorimetry or desorption (an invented set)", data_kind="table",
                     availability="available", version="1", sha256="2" * 64,
                     uri="https://example.org/invented/chemisorption.csv", evidence=[ev(bench, "Table 1", "table")])
    claimed = {}
    for key, m, level, mae, mse in (("pbe", pbe, "PBE", 0.52, -0.48), ("rpbe", rpbe, "RPBE", 0.24, 0.1),
                                    ("beef-vdw", beef, "BEEF-vdW", 0.2, 0.05)):
        bid = computation(f"benchmark-{key}", f"Chemisorption energies of the reference set, {level}", bench, "Table 2",
                          methods=(m,), level=level, goal="benchmark",
                          evidence=[ev(bench, "Table 2", "table", id="t2")],
                          result_values=[{"id": "mae", "status": "present", "value": mae, "unit": "eV", "variable": v_mae,
                                          "evidence_ids": ["t2"]},
                                         {"id": "mse", "status": "present", "value": mse, "unit": "eV", "variable": v_mse,
                                          "definition": "computed minus measured, as a binding energy; negative = binds "
                                                        "too strongly", "evidence_ids": ["t2"]}])
        link("HAS_INPUT", bid, reference, role="reference_standard")
        link("EVALUATES", bid, m, evaluation_kind="benchmark",
             scope="twelve chemisorption energies of small adsorbates on late transition-metal surfaces",
             criterion="the errors of the computed energies against the measured ones",
             result_refs=[{"record": bid, "path": "/result_values/mae"}, {"record": bid, "path": "/result_values/mse"}],
             evidence=[ev(bench, "Table 2", "table")])
        claimed[key] = bid
    overbinds = node("claim/pbe-overbinds", "Claim", "PBE binds too strongly",
                     statement="PBE binds the adsorbates of the reference set more strongly than measured, by about 0.5 eV "
                               "on average", claim_kind="comparison", claim_status="supported",
                     inference_type="computational",
                     scope="chemisorption of small adsorbates on late transition-metal surfaces",
                     evidence=[ev(bench, "Section 3")])
    link("ABOUT", overbinds, pbe, role="the method it is about")
    link("SUPPORTS", claimed["pbe"], overbinds,
         premise_refs=[{"record": claimed["pbe"], "path": "/result_values/mse"}],
         evidence=[ev(bench, "Table 2", "table")])

    for e in derive_reported_in(doc):
        e["props"]["origin"] = SYN
        doc["links"].append(e)
    return doc


if __name__ == "__main__":
    write_canonical(HERE / "computational-methods.json", computational_methods())
    print("wrote computational-methods.json")
