"""Add the pre-1965 methanol-synthesis data table to the methanol-synthesis graph.

The table (``methanol_pre1965_dataset_curated.csv``, 549 rows from the same 60 sources) was
extracted by an agent into the group's general catalysis curation schema v3.0 and normalized:
temperatures in °C, pressures in bar, one row per catalyst × condition set × catalyst state ×
measurement. Its equilibrium screen (``curation/equilibrium_check.csv``) compares each reported
methanol carbon yield with a computed equilibrium yield.

In the graph the table is a ``Dataset``. Each row becomes a run (Experiment, CatalyticSystem,
ConditionSet, feed Environment, catalyst Material/Sample/CatalystState, preparation and
pretreatment) with its performance figures. Every record cites two Evidence records: the dataset
row (``derived_data``) and the source location the row names (``reported_table`` /
``reported_figure`` / ``reported_text``), attached to the same ``Source`` records as the GALAXY
curation. Values keep the table's units. Pressures carry a note because the table converted them
to bar. Fields the table lists as missing become ``not_reported``; fields its curators estimated
are ``approximate`` with the curators' remark.

The table's objective quotes are readings of tables ("Table II, … = 4.5"), not verbatim text. Only
fragments quoted inside them that were found verbatim in the source text become excerpts; these
are listed in ``dataset-excerpts.json`` (``python dataset_to_scale.py verify-excerpts``), so the
conversion is reproducible without the non-redistributable texts.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
from galaxy_to_scale import P, short_hash, slug  # noqa: E402

TABLE = "methanol_pre1965_dataset_curated.csv"
COLUMNS = "methanol_pre1965_dataset_curated_columns.csv"
EQ_CHECK = "curation/equilibrium_check.csv"
EQ_SCRIPT = "curation/check_equilibrium.py"
D = f"{P}/data"

GAS = {"H2": "hydrogen", "CO": "carbon monoxide", "CO2": "carbon dioxide", "N2": "nitrogen", "CH3OH": "methanol",
       "O2": "oxygen", "CH4": "methane", "HCOH": "formaldehyde", "H2O": "water"}
STATE = {"fresh": "as_prepared", "calcined": "as_prepared", "reduced": "activated", "heat_treated": "other",
         "aged": "other", "reactivated": "regenerated", "spent": "post_reaction"}
COMP_BASIS = {"molar_ratio": ("mole", "mol ratio"), "mole_pct": ("mole", "mol%"), "atomic_pct": ("atom", "at%"),
              "wt_pct_oxide": ("mass", "wt% as oxide"), "wt_pct_metal": ("mass", "wt% as metal"),
              "parts_by_weight_oxide": ("mass", "parts by weight as oxide")}
UNITS = {"percent": "%", "C": "°C", "vol_pct": "vol%", "molar_ratio": "1"}
ELEMENTS = {"H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Na", "Mg", "Al", "Si", "P", "S", "Cl", "K", "Ca", "Ti",
            "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge", "As", "Se", "Br", "Rb", "Sr", "Y", "Zr", "Nb",
            "Mo", "Ru", "Rh", "Pd", "Ag", "Cd", "Sn", "Sb", "Te", "I", "Cs", "Ba", "La", "Ce", "Pr", "Nd", "W", "Pt",
            "Au", "Hg", "Tl", "Pb", "Bi", "Th", "U"}
# curated net reactions (standard stoichiometry, not taken from the table)
REACTIONS = {
    "co-hydrogenation": ("CO + 2 H2 -> CH3OH", [("carbon monoxide", -1), ("hydrogen", -2), ("methanol", 1)]),
    "co2-hydrogenation": ("CO2 + 3 H2 -> CH3OH + H2O",
                          [("carbon dioxide", -1), ("hydrogen", -3), ("methanol", 1), ("water", 1)]),
    "methanol-decomposition": ("CH3OH -> CO + 2 H2", [("methanol", -1), ("carbon monoxide", 1), ("hydrogen", 2)]),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def num(s: str):
    if s in ("", None):
        return None
    v = float(s)
    return int(v) if v.is_integer() else v


def jl(s: str):
    return json.loads(s) if s else None


def field_key(f: str) -> str:
    """Normalize a missing/estimated field entry ('reaction_conditions.reaction_pressure_bar (from Fig. 2)')."""
    head = re.split(r"[\s(]", f.strip(), maxsplit=1)[0]
    last = head.split(".")[-1]
    if last == "value" and "." in head:
        last = head.split(".")[-2]
    return {"reaction_temperature_C": "temperature", "reaction_pressure_bar": "pressure",
            "time_on_stream_h": "time_on_stream", "key_feed_ratio": "h2_to_cox_ratio",
            "primary_objective": "yield", "reactant_conversion_percent": "conversion",
            "feed_composition": "feed", "space_velocity": "space_velocity",
            "composition_value": "composition", "active_components": "composition"}.get(last, last)


class DatasetConverter:
    def __init__(self, conv, corpus: Path, excerpts: dict[str, list[str]]):
        self.c, self.corpus, self.excerpts = conv, corpus, excerpts
        self.rows = list(csv.DictReader(open(corpus / TABLE, encoding="utf-8", newline="")))
        self.eq = {r["row_id"]: r for r in csv.DictReader(open(corpus / EQ_CHECK, encoding="utf-8", newline=""))}
        self.source_of = {}
        for e in conv.entities.values():
            if e["type"] == "Source":
                for x in e.get("external_identifiers", []):
                    self.source_of[x["value"].lower()] = e["id"]

    # ---------------------------------------------------------------- shared records
    def datasets(self) -> None:
        c = self.c
        self.table_id = f"{D}/dataset/pre1965-table"
        c.ent(self.table_id, "Dataset", "Pre-1965 methanol-synthesis data table (549 rows, 60 sources)",
              {"data_kind": "table", "media_type": "text/csv", "availability": "restricted",
               "uri": f"ARPA-E-CATALYST/Corpus/{TABLE}", "sha256": sha256(self.corpus / TABLE),
               "data_schema": f"General catalysis curation schema v3.0; column dictionary {COLUMNS} "
                              f"(sha256 {sha256(self.corpus / COLUMNS)})",
               "description": "Agent extraction of the 60 corpus sources, one row per catalyst x condition set x "
                              "catalyst state x measurement. Units normalized by the table: temperatures in °C, "
                              "pressures in bar. Held in the ARPA-E CATALYST project storage; not redistributed."},
              origin="curated")
        self.eq_id = f"{D}/dataset/equilibrium-check"
        c.ent(self.eq_id, "Dataset", "Equilibrium screen of the reported methanol carbon yields",
              {"data_kind": "output", "media_type": "text/csv", "availability": "restricted",
               "uri": f"ARPA-E-CATALYST/Corpus/{EQ_CHECK}", "sha256": sha256(self.corpus / EQ_CHECK),
               "description": "Equilibrium methanol carbon yield per row with a reported temperature, and whether "
                              "the reported yield exceeds it by more than 3 percentage points."}, origin="curated")
        self.model_id = f"{D}/model/equilibrium"
        c.ent(self.model_id, "Model", "Methanol-synthesis equilibrium with Peng-Robinson fugacities",
              {"model_kind": "thermodynamic", "version": "check_equilibrium.py sha256 " + sha256(self.corpus / EQ_SCRIPT)[:12],
               "equations": ["CO + 2 H2 = CH3OH, K1 = 10^(5139/T - 12.621) bar^-2 (Graaf et al. 1986)",
                             "CO2 + H2 = CO + H2O, K3 = 10^(-2073/T + 2.029) (Graaf et al. 1986)"],
               "assumptions": ["Peng-Robinson fugacities with kij = 0", "vapour-liquid flash: methanol and water may "
                               "condense", "inerts lumped as N2", "yield on the same carbon basis as the reported yield"],
               "description": "A row is flagged when its reported yield exceeds the equilibrium yield by more than "
                              "3 percentage points (tolerance for measurement, K and equation-of-state uncertainty)."},
              origin="curated")
        self.software_id = f"{D}/software/check-equilibrium"
        c.ent(self.software_id, "Software", "check_equilibrium.py",
              {"name": "check_equilibrium.py", "version": "sha256 " + sha256(self.corpus / EQ_SCRIPT)[:12]},
              origin="curated", note=f"Script held at ARPA-E-CATALYST/Corpus/{EQ_SCRIPT} in the project storage.")
        self.comp_id = f"{D}/computation/equilibrium-check"
        c.ent(self.comp_id, "Computation", "Equilibrium screen of the data table",
              {"task": "equilibrium methanol carbon yield at each row's temperature, pressure and feed",
               "status": "completed"}, origin="computed")
        c.rel("uses_model", self.comp_id, self.model_id, origin="curated")
        c.rel("uses_software", self.comp_id, self.software_id, origin="curated")
        self.reactions = {}
        for key, (eq, parts) in REACTIONS.items():
            rid = f"{D}/reaction/{key}"
            c.ent(rid, "Reaction", eq, {"equation": eq, "balance_status": "balanced", "direction": "forward",
                                        "participants": [{"species_ref": c.species_ref(s), "coefficient": k}
                                                         for s, k in parts]},
                  origin="curated", note="Standard net reaction assigned from the row's carbon source and feed.")
            self.reactions[key] = rid

    def species(self, gas: str, ev=None) -> str:
        if gas in GAS:
            return self.c.species_ref(GAS[gas], ev)
        if gas == "D2":
            eid = f"{D}/species/d2"
            self.c.ent(eid, "ChemicalSpecies", "deuterium", {"formula": "D2", "isotopic_composition": "2H2",
                                                              "species_kind": "molecule", "charge": 0}, origin="curated",
                       evidence=ev)
            return eid
        return self.c.species_ref({"inerts": "inert gas", "inert": "inert gas"}.get(gas, gas.replace("_", " ")), ev)

    def element(self, sym: str, ev=None) -> str:
        if sym in ELEMENTS:
            eid = f"{P}/species/{slug(sym)}"
            self.c.ent(eid, "ChemicalSpecies", sym, {"formula": sym, "elemental_composition": {sym: 1}},
                       origin="curated", evidence=ev, note="Element named as a catalyst component by the data table.")
            return eid
        return self.c.species_ref(sym, ev)

    # ---------------------------------------------------------------- per row
    def q(self, value, unit, key, row_flags, note=None) -> dict:
        missing, estimated = row_flags
        if value is None:
            if key in missing:
                return {"status": "not_reported", "note": "not reported in the source (data table missing_fields)"}
            return None
        out = {"status": "present", "value": value, "unit": unit}
        notes = [note] if note else []
        if key in estimated:
            out["qualifier"] = "approximate"
            notes.append("estimated by the data-table curators: " + "; ".join(estimated[key]))
        if notes:
            out["note"] = "; ".join(notes)
        return out

    def row_evidence(self, r: dict, src: str) -> list[str]:
        c = self.c
        rid = r["row_id"]
        ev_row = f"{D}/ev/row/{slug(rid)}"
        c.ent(ev_row, "Evidence", f"Data table row {rid}",
              {"source_ref": self.table_id, "locator": f"row {rid}", "evidence_kind": "derived_data",
               "description": r["notes"] or "No curator notes for this row."}, origin="curated")
        loc = r["source_locator"] or "not stated in the data table"
        kind = "reported_figure" if re.search(r"\bfig", loc, re.I) else \
            "reported_table" if re.search(r"\btable|\btab\.", loc, re.I) else "reported_text"
        ids = [ev_row]
        frags = self.excerpts.get(rid, [])
        ev_src = f"{D}/ev/source/{slug(rid)}"
        attrs = {"source_ref": src, "locator": loc, "evidence_kind": kind,
                 "description": ("Data-table curators' reading: " + r["objective_quote"]) if r["objective_quote"]
                 else "Location named by the data table; no quotation recorded."}
        if frags:
            attrs["excerpt"] = frags[0]
        c.ent(ev_src, "Evidence", f"{loc[:70]}", attrs, origin="curated")
        ids.append(ev_src)
        return ids

    def material(self, r: dict, src: str, ev) -> str | None:
        name = r["catalyst_name"].strip()
        if not name or name.lower().startswith(("none", "unspecified", "no catalyst")):
            return None
        c = self.c
        mid = f"{D}/material/{slug(src.split('/')[-1])}/{short_hash(name, n=8)}"
        comp = []
        flags = self.flags(r)
        for x in jl(r["active_components"]) or []:
            x = dict(x, element=x.get("element") or x.get("as_reported"))
            if not x["element"]:
                continue
            basis = x.get("composition_basis")
            fb, unit = COMP_BASIS.get(basis, ("not_reported", None))
            cc = {"component_ref": self.element(x["element"], ev), "role": "active_component"}
            if x.get("composition_value") is not None and unit:
                cc["fraction"] = self.q(num(str(x["composition_value"])), unit, "composition", flags,
                                        note=f"as reported: {x['as_reported']}" if x.get("as_reported") else None)
                cc["fraction_basis"] = fb
            elif x.get("loading_wt_percent") is not None:
                cc["fraction"] = {"status": "present", "value": num(str(x["loading_wt_percent"])), "unit": "wt%"}
                cc["fraction_basis"] = "mass"
            comp.append(cc)
        for x in jl(r["promoters"]) or []:
            if not x.get("element"):
                continue
            cc = {"component_ref": self.element(x["element"], ev), "role": "promoter"}
            if x.get("loading_wt_percent") is not None:
                cc["fraction"] = {"status": "present", "value": num(str(x["loading_wt_percent"])), "unit": "wt%"}
                cc["fraction_basis"] = "mass"
            comp.append(cc)
        if r["support_material"] not in ("", "none"):
            cc = {"component_ref": self.c.species_ref(r["support_material"], ev), "role": "support"}
            if r["support_loading_wt_pct"]:
                cc["fraction"] = {"status": "present", "value": num(r["support_loading_wt_pct"]), "unit": "wt%"}
                cc["fraction_basis"] = "mass"
            comp.append(cc)
        if mid not in c.entities:
            c.ent(mid, "Material", name, {"composition": comp}, evidence=ev,
                  note="Formulation as named by the data table; not merged with the GALAXY catalyst records.")
            c.rel("reported_in", mid, src, origin="curated")
        else:
            c.ent(mid, "Material", "", {}, evidence=ev)
        return mid

    def flags(self, r: dict):
        missing = {field_key(f) for f in jl(r["missing_fields"]) or []}
        estimated: dict[str, list[str]] = {}
        for f in jl(r["estimated_fields"]) or []:
            estimated.setdefault(field_key(f), []).append(f)
        return missing, estimated

    def sample(self, r: dict, mid: str, src: str, ev) -> str:
        c = self.c
        sid = mid.replace("/material/", "/sample/")
        if sid not in c.entities:
            c.ent(sid, "Sample", f"{c.entities[mid]['label']} — specimen in the data table",
                  {"sample_kind": "other", "preparation_status": "not_reported"}, evidence=ev,
                  note="One specimen record per catalyst name and source; batch identity is not asserted.")
            c.rel("has_formulation", sid, mid, origin="curated")
            for x in [x for x in jl(r["precursors"]) or [] if x.get("precursor_name")]:
                c.rel("prepared_from", sid, c.species_ref(x["precursor_name"], ev), origin="reported", evidence=ev,
                      qualifiers={"role": f"precursor of {x['metal']}"})
        else:
            c.ent(sid, "Sample", "", {}, evidence=ev)
        method = r["synthesis_method"]
        if method and method != "unspecified":
            prep = f"{sid}/preparation/{slug(method)}"
            c.ent(prep, "Preparation", f"{method} of {c.entities[mid]['label']}",
                  {"method": method, "status": "not_reported"}, evidence=ev)
            c.rel("prepared_by", sid, prep, evidence=ev)
        flags = self.flags(r)
        for kind, t, atm, dur in (("calcination", r["calcination_temperature_C"], r["calcination_atmosphere"], ""),
                                  ("drying", r["drying_temperature_C"], "", ""),
                                  ("pretreatment", r["pretreatment_temperature_C"], r["pretreatment_atmosphere"],
                                   r["pretreatment_time_h"])):
            if not t:
                continue
            gases = ", ".join(f"{g['gas']} {g['molar_ratio']}" for g in (jl(atm) or {}).get("components", []))
            key = short_hash(kind, t, gases, dur, n=8)
            tid = f"{sid}/treatment/{kind}-{key}"
            tk = {"calcination": "calcination", "drying": "other"}.get(kind) or (
                "reduction" if re.search(r"H2|CO|syngas|methanol", gases) else "activation")
            if tid not in c.entities:
                c.ent(tid, "Treatment", f"{kind} of {c.entities[mid]['label']}",
                      {"treatment_kind": tk, "status": "not_reported",
                       "description": f"{kind}" + (f" in {gases} (molar ratios as tabulated)" if gases else "")},
                      evidence=ev)
                cs = f"{tid}/conditions"
                attrs = {"role": "not_reported", "temperature": self.q(num(t), "°C", f"{kind}_temperature", flags)}
                if dur:
                    attrs["duration"] = self.q(num(dur), "h", "pretreatment_time", flags)
                c.ent(cs, "ConditionSet", f"Conditions of {kind}", attrs, evidence=ev)
                c.rel("operated_under", tid, cs, evidence=ev)
                c.rel("uses_sample", tid, sid, origin="curated")
        return sid

    def state(self, r: dict, sid: str, ev) -> str:
        tok = r["catalyst_state"]
        if tok in ("", "unspecified"):
            return sid
        c = self.c
        stid = f"{sid}/state/{slug(tok)}"
        c.ent(stid, "CatalystState", f"{c.entities[sid]['label']} ({tok.replace('_', ' ')})",
              {"state_label": STATE.get(tok, "other"), "description": f"catalyst state as tabulated: {tok}"},
              evidence=ev)
        c.rel("state_of", stid, sid, origin="curated")
        return stid

    def reactions_for(self, r: dict, feed: list) -> list[str]:
        gases = {g["gas"] for g in feed}
        if gases and gases <= {"CH3OH", "N2", "inerts", "inert"}:
            return [self.reactions["methanol-decomposition"]]
        src = r["reactant_source"]
        return [self.reactions[k] for k in (["co-hydrogenation"] if src == "CO" else ["co2-hydrogenation"] if src == "CO2"
                                            else ["co-hydrogenation", "co2-hydrogenation"])]

    def row(self, r: dict) -> None:
        c = self.c
        rid = r["row_id"]
        key = (r["doi"] or r["patent_number"]).lower()
        src = self.source_of[key]
        ev = self.row_evidence(r, src)
        flags = self.flags(r)
        base = f"{D}/run/{slug(rid)}"
        mid = self.material(r, src, ev)
        feed = jl(r["feed_composition"]) or []
        catalyst = self.state(r, self.sample(r, mid, src, ev), ev) if mid else None
        flag = r["data_quality_flag"]
        run_kind = "catalytic_test" if catalyst else "other"
        c.ent(base, "Experiment", f"{r['catalyst_name'] or 'No catalyst'}: {r['source_locator'][:80]}",
              {"run_kind": run_kind, "status": "completed",
               "description": f"Data table row {rid} (quality flag {flag})"
                              + ("; equilibrium record, not a measurement" if flag == "equilibrium" else "")},
              evidence=ev)
        c.rel("reported_in", base, src, origin="curated")
        c.rel("includes", self.study_id, base, origin="curated")
        system = f"{base}/system"
        c.ent(system, "CatalyticSystem", f"System of data row {rid}",
              {"phase_regime": "heterogeneous" if catalyst else "not_reported",
               "catalyst_forms": ["extended_solid" if catalyst else "not_reported"], "activation_modes": ["thermal"]},
              origin="curated", evidence=ev)
        c.rel("has_system", base, system, origin="curated")
        if catalyst:
            c.rel("has_catalyst", system, catalyst, evidence=ev)
        for rx in self.reactions_for(r, feed):
            c.rel("has_reaction", system, rx, origin="curated",
                  note=f"assigned from the tabulated carbon source ({r['reactant_source']}) and feed")
        # feed
        if feed:
            env = f"{base}/feed"
            comps = [{"component_ref": self.species(g["gas"], ev), "role": "other", "fraction_basis": "mole",
                      "fraction": {"status": "present", "value": num(str(g["molar_ratio"])), "unit": "1",
                                   "note": "relative molar parts as tabulated"}}
                     for g in feed if g.get("molar_ratio") is not None]
            c.ent(env, "Environment", f"Feed of data row {rid}",
                  {"environment_kind": "gas_feed", "components": comps, "spatial_scope": "inlet",
                   "description": f"carbon source: {r['reactant_source']}"}, evidence=ev)
            c.rel("has_environment", system, env, evidence=ev)
        elif "feed" in flags[0]:
            env = f"{base}/feed"
            c.ent(env, "Environment", f"Feed of data row {rid}",
                  {"environment_kind": "gas_feed", "description": "not reported in the source (data table "
                                                                  f"missing_fields); carbon source {r['reactant_source']}"},
                  evidence=ev)
            c.rel("has_environment", system, env, evidence=ev)
        # conditions
        cs = f"{base}/conditions"
        attrs = {"role": "not_reported",
                 "temperature": self.q(num(r["reaction_temperature_C"]), "°C", "temperature", flags),
                 "pressure": self.q(num(r["reaction_pressure_bar"]), "bar", "pressure", flags,
                                    note="bar as tabulated; the table converts source units (see the row notes)"),
                 "duration": self.q(num(r["time_on_stream_h"]), "h", "time_on_stream", flags, note="time on stream")}
        other = {}
        sv = self.q(num(r["space_velocity"]), r["space_velocity_unit"] or "unit not stated", "space_velocity", flags,
                    note=f"as reported: {r['space_velocity_as_reported']}" if r["space_velocity_as_reported"] else None)
        if sv:
            other["space_velocity"] = sv
        ratio = self.q(num(r["H2_to_COx_ratio"]), "1", "h2_to_cox_ratio", flags, note="H2:COx molar ratio")
        if ratio:
            other["h2_to_cox_ratio"] = ratio
        if other:
            attrs["other_conditions"] = other
        c.ent(cs, "ConditionSet", f"Conditions of data row {rid}", {k: v for k, v in attrs.items() if v},
              origin="derived", evidence=ev,
              note="Values as tabulated by the data table (temperatures in °C and pressures in bar, normalized by its curators).")
        c.rel("operated_under", base, cs, evidence=ev)
        # results
        self.results(r, base, ev, flags)

    def metric(self, mid, label, kind, q, definition, norm, xid, ev, target=None, origin="reported", note=None):
        c = self.c
        attrs = {"quantity_kind": kind, "quantity": q, "definition": definition, "normalization": norm}
        if target:
            attrs["target_species_ref"] = target
        c.ent(mid, "PerformanceMetric", label, attrs, origin=origin, evidence=ev, note=note)
        c.rel("metric_of", mid, xid, evidence=ev)

    def results(self, r: dict, xid: str, ev, flags) -> None:
        c = self.c
        rid = r["row_id"]
        y = num(r["methanol_carbon_yield_pct"])
        yid = None
        if y is not None:
            src_c = {"CO": "CO", "CO2": "CO2", "CO_plus_CO2": "CO + CO2"}[r["reactant_source"]]
            yid = f"{xid}/yield"
            deriv = r["yield_derivation"] or "not stated"
            if r["objective_metric"] == "methanol_sty":
                self.metric(yid, f"Methanol space-time yield, data row {rid}", "msyn:space_time_yield",
                            self.q(y, r["objective_unit"] or "unit not stated", "yield", flags),
                            "Methanol space-time yield as tabulated", {"basis": "custom",
                            "description": "per catalyst volume, as the tabulated unit states"}, xid, ev,
                            target=c.species_ref("methanol"))
            else:
                self.metric(yid, f"Methanol carbon yield, data row {rid}", "scale:yield",
                            self.q(y, "%", "yield", flags),
                            f"Per-pass methanol carbon yield = 100 x mol C in CH3OH / mol C in the {src_c} fed",
                            {"basis": "custom", "description": f"carbon basis: {src_c} fed; derivation: {deriv}"},
                            xid, ev, target=c.species_ref("methanol"),
                            origin="derived" if deriv == "from_split" else "reported",
                            note=f"derivation as tabulated: {deriv}")
        conv = num(r["conversion_pct"])
        if conv is not None:
            react = r["conversion_reactant"] or r["reactant_source"]
            self.metric(f"{xid}/conversion", f"{react} conversion, data row {rid}", "scale:conversion",
                        self.q(conv, "%", "conversion", flags),
                        f"Conversion of {react}" + (f" ({r['conversion_basis']})" if r["conversion_basis"] else ""),
                        {"basis": "reactant_fed", "description": r["conversion_basis"] or "basis not stated"},
                        xid, ev, target=self.species(react) if react in GAS else None)
        for i, m in enumerate(jl(r["secondary_metrics"]) or []):
            if m.get("value") is None:
                continue
            oid = f"{xid}/obs/{slug(m['name'])}-{i + 1}"
            unit = UNITS.get(m.get("unit"), m.get("unit")) or "unit not stated"
            c.ent(oid, "Observation", f"{m['name'].replace('_', ' ')}, data row {rid}",
                  {"quantity_kind": f"msyn:{slug(m['name']).replace('-', '_').replace('.', '_')}",
                   "quantity": {"status": "present", "value": num(str(m["value"])), "unit": unit},
                   "description": f"basis: {m['basis']}" if m.get("basis") else None}, evidence=ev)
            c.rel("observation_of", oid, xid, evidence=ev)
            c.rel("generated_by", oid, xid, origin="curated")
        if r["equilibrium_value"]:
            oid = f"{xid}/obs/equilibrium-{slug(r['equilibrium_basis'])}"
            unit = "%" if r["equilibrium_basis"] == "equilibrium_conversion_pct" else "unit not stated"
            c.ent(oid, "Observation", f"Equilibrium value ({r['equilibrium_basis']}), data row {rid}",
                  {"quantity_kind": f"msyn:equilibrium_{slug(r['equilibrium_basis']).replace('-', '_')}",
                   "quantity": {"status": "present", "value": num(r["equilibrium_value"]), "unit": unit},
                   "description": "Equilibrium value reported or computed by the source, as tabulated"}, evidence=ev)
            c.rel("observation_of", oid, xid, evidence=ev)
            c.rel("generated_by", oid, xid, origin="curated")
        self.equilibrium(r, xid, yid, ev)

    def equilibrium(self, r: dict, xid: str, yid: str | None, ev) -> None:
        e = self.eq.get(r["row_id"])
        if not e or e["status"] == "not_checked_no_temperature" or not e["eq_yield_pct"]:
            return
        c = self.c
        eq_ev = f"{D}/ev/eq/{slug(r['row_id'])}"
        c.ent(eq_ev, "Evidence", f"Equilibrium screen row {r['row_id']}",
              {"source_ref": self.eq_id, "locator": f"row {r['row_id']}", "evidence_kind": "computation",
               "description": f"status {e['status']}; condensed phase {e['condensed_phase']}"}, origin="computed")
        oid = f"{xid}/obs/equilibrium-carbon-yield"
        c.ent(oid, "Observation", f"Equilibrium methanol carbon yield at the conditions of data row {r['row_id']}",
              {"quantity_kind": "msyn:equilibrium_carbon_yield",
               "quantity": {"status": "present", "value": num(e["eq_yield_pct"]), "unit": "%"},
               "description": "Computed at the tabulated temperature, pressure, H2:COx ratio and CO2 fraction; "
                              "same carbon basis as the reported yield"},
              origin="computed", evidence=[eq_ev])
        c.rel("observation_of", oid, xid, origin="computed", evidence=[eq_ev])
        c.rel("generated_by", oid, self.comp_id, origin="computed")
        if e["status"] == "violates_equilibrium" and yid:
            cid = f"{D}/claim/exceeds-equilibrium/{slug(r['row_id'])}"
            c.ent(cid, "Claim", f"Reported yield exceeds equilibrium, data row {r['row_id']}",
                  {"statement": f"The tabulated methanol carbon yield ({r['methanol_carbon_yield_pct']} %) exceeds the "
                                f"computed equilibrium yield ({e['eq_yield_pct']} %) by {e['excess_pts']} percentage "
                                "points, more than the 3-point tolerance.",
                   "claim_kind": "other", "epistemic_status": "supported",
                   "scope": f"Data table row {r['row_id']} at its tabulated conditions",
                   "limitations": "Points to a transcription, basis or condition error in the row or the source; "
                                  "it does not show which. The reported value is kept."},
                  origin="computed", evidence=[eq_ev])
            c.rel("about", cid, yid, origin="computed", evidence=[eq_ev])
            c.rel("supports", oid, cid, origin="computed")
            c.rel("supports", eq_ev, cid, origin="computed")

    def run(self) -> None:
        self.datasets()
        self.study_id = f"{D}/study/pre1965-table"
        self.c.ent(self.study_id, "Study", "Pre-1965 methanol-synthesis data table",
                   {"title": "Pre-1965 methanol-synthesis data table",
                    "objective": "Tabulate catalyst, preparation, conditions and methanol carbon yield per run for "
                                 "optimization, from the sources published before the ICI low-pressure catalyst.",
                    "scope": "549 rows from the 60 corpus sources, 1927-1965"}, origin="curated")
        self.c.rel("includes", self.study_id, self.table_id, origin="curated")
        for r in self.rows:
            self.row(r)


def verify_excerpts(corpus: Path, texts: Path, out: Path) -> int:
    """Find the fragments quoted inside each row's objective quote that occur verbatim in the source text."""
    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(next(p for p in (q for s in (here, Path.cwd()) for q in (s, *s.parents))
                                if (p / "scale-release.yaml").exists() and (p / "releases").is_dir()) / "tools"))
    from scale.util import normalize_for_match
    kit = corpus / "methanol-synthesis-curation-kit/work/papers"
    txt = {}
    for d in sorted(kit.iterdir()):
        m = json.loads((d / "source.json").read_text(encoding="utf-8"))
        txt[m["source_id"].lower()] = normalize_for_match((texts / f"{d.name}.txt").read_text(encoding="utf-8"))
    res = {}
    for r in csv.DictReader(open(corpus / TABLE, encoding="utf-8", newline="")):
        key = (r["doi"] or "patent:" + r["patent_number"]).lower()
        frags = [s.strip() for s in re.findall(r"'([^']{25,})'", r["objective_quote"])
                 if normalize_for_match(s) in txt.get(key, "")]
        if frags:
            res[r["row_id"]] = frags
    out.write_text(json.dumps(dict(sorted(res.items())), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(res)} rows with verified excerpts", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "verify-excerpts":
        sys.exit(verify_excerpts(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])))
    print("usage: dataset_to_scale.py verify-excerpts CORPUS_DIR TEXTS_DIR OUT.json", file=sys.stderr)
    sys.exit(2)
