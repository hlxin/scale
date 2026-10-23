"""Move scale-catal documents along the version steps of the schema.

    scale graph migrate IN.json OUT.json

A schema change that raises the version registers its step here: ``STEPS[from] = (to, note)`` (``scale schema
bump`` writes the line). An additive step only raises ``schema_version``; a breaking change also registers a rule
in ``STEP_RULES[from] = (description, function)``, which rewrites the document and reports every change (or
reports that no document needs one). Every record keeps its id, and what cannot be inferred is not invented: a
rule that meets a case it cannot map stops with an error.

The schema starts at 0.1.0, with no steps; ``scale check`` requires the step of every change (schema_change.check).
"""

from __future__ import annotations

import copy
from typing import Callable

from .util import ScaleError

STEPS: dict[str, tuple[str, str]] = {
    # "<from version>": ("<to version>", "<note>"), one line per change that raises the version, oldest first
    # (none before the first change: the schema starts at 0.1.0)
    "0.1.0": ("0.2.0", 'the schema is renamed scale-graph -> scale-catal (kernel scale-graph-kernel -> scale-kernel); documents pin the new name'),
    "0.2.0": ("0.2.1", 'no change in meaning: the description of Preparation.steps names PART_OF with order (#34)'),
    "0.2.1": ("0.3.0", "breaking: quantity contracts (a value's unit by its kind's dimension; the contexts a comparison needs; normalized_by; HAS_COMPONENT.concentration)"),
    "0.3.0": ("0.4.0", 'breaking: result entries (Experiment.result_values with value ids, phase, stream, unresolved_target); conversion, product_yield, selectivity, production_rate, product_amount and balance kinds; in catalysis a species is a ChemicalSpecies (context_targets)'),
    "0.4.0": ("0.5.0", "breaking: the catalysis checklist applies a test's cases by its driving_forces (a test that lists none has unknown applicability, never a complete checklist) and looks for connected evidence; CatalyticTest.interpretations, Analysis.evaluation_basis, power_supply_input and the dark control's control_kind, differs_in, temperature_matched_at and temperature_matched_over are new (provisional)"),
    "0.5.0": ("0.5.1", 'Represent bifunctional (tandem) catalysts: component function, integration mode and scale, site proximity (provisional)'),
    "0.5.1": ("0.5.2", "additive: ProductLump (a product reported as a lump or fraction) and SUBSET_OF; HAS_OUTPUT.to and PRODUCES.to accept a ProductLump; no record changes"),
    "0.5.2": ("0.6.0", "breaking: site populations of a catalyst state (HAS_SITE from CatalystState with population_fraction, site_density, exposed_metal_count and site_inventory); the site_fraction, site_density and site_count kinds; a turnover frequency compared by its species, divided by a site count or a site density, and saying how it was calculated (a warning when it does not); operando defined as characterized while the kinetics are measured; DURING's specimen, timing, kinetics and benchmark; Analysis spectral_fit and limitations; the checklist's operando and spectral-fit cases (provisional)"),
    "0.6.0": ("0.7.0", "breaking: computed energies and kinetic parameters compared under explicit definitions (the kinds electronic_energy, reaction_energy, reaction_enthalpy, reaction_free_energy, activation_energy, activation_free_energy, apparent_activation_energy and degree_of_rate_control; the contexts process, structure, level_of_theory and charge_treatment, the last two read from the value's producer; what a kind shows); ElementaryStep energies and RATE_CONTROL's degree of rate control bound to their kinds; Computation's method fields, Model.stored_in and REPRESENTS aspect and assumptions (provisional)"),
    "0.7.0": ("0.7.1", 'additive change: kinds for enzyme activity, a Michaelis constant, a turnover number, transport criteria, an effectiveness factor, a Thiele modulus and energy consumption; the enzyme unit (U) and the katal; roles ligand, solvent, cocatalyst and cofactor; catalyst families enzyme and whole_cell; species kind macromolecule; CatalyticTest.catalysis_mode'),
}


def _rename_schema(doc: dict, spec: dict | None) -> list:
    """0.1.0 -> 0.2.0: the schema is renamed scale-graph -> scale-catal (the kernel scale-graph-kernel -> scale-kernel,
    which a document never names). The pin ``graph.schema`` is rewritten; no record changes."""
    g = doc["graph"]
    if g.get("schema") == "scale-graph":
        g["schema"] = "scale-catal"
        return ["graph.schema: scale-graph -> scale-catal"]
    return []                                   # already names the new schema: nothing to rewrite


def _quantity_contracts(doc: dict, spec: dict | None) -> list:
    """0.2.1 -> 0.3.0: the quantity contracts. A HAS_COMPONENT ``fraction`` whose unit is an amount (g, mol, L) moves to
    ``amount`` and one whose unit is a concentration (mol/L, g/m3) to the new ``concentration``, the value object whole
    (number, unit, uncertainty, evidence_ids, as_reported), with its ``fraction_basis`` dropped (the unit says what it
    counts); every other value whose unit is of another dimension than its
    property's quantity stops the step, which cannot map it (``quantities.move_component_quantities``). ``spec`` is the
    target schema, whose contracts read the units."""
    from .quantities import move_component_quantities
    return move_component_quantities(doc, spec)


def _result_entries(doc: dict, spec: dict | None) -> list:
    """0.3.0 -> 0.4.0: result entries and the kinds of share. Nothing a 0.3.0 document holds is rewritten: the scalar
    results (conversion, yield, selectivity, now of their own kinds), the results map and the per-product lists keep
    their meaning where they are, and no value moves into result_values (a move would need an id and a variable the
    document does not state, and would make a positional reference name another value). What the step cannot map stops
    it: a value of a kind counted for a species whose target is not a ChemicalSpecies (in catalysis a species is one,
    context_targets), which names no species at all; curate it by hand (its species as target, or the source's words as
    unresolved_target), then migrate. ``spec`` is the target schema."""
    from .quantities import narrowed_targets
    bad = narrowed_targets(doc, spec)
    if bad:
        raise ScaleError("the step to the result entries cannot map values whose product or reactant is not a chemical "
                         f"species (curate them by hand, then migrate): {'; '.join(bad[:20])}"
                         + (f" (and {len(bad) - 20} more)" if len(bad) > 20 else ""))
    return []


def _reporting_applicability(doc: dict, spec: dict | None) -> list:
    """0.4.0 -> 0.5.0: reporting applicability and connected evidence. Nothing a 0.4.0 document holds is rewritten, and
    nothing stops the step: every record stays valid, and only what its checklist reports changes. A test that lists
    no driving force is no longer read as meeting every driving-force item: its applicability is unknown and its
    checklist is not complete (record its driving forces to make it so). No interpretation is inferred (a kinetics or
    stability test is not thereby read as intrinsic kinetics or material stability), and a CONTROL_FOR is not turned
    into a DARK_CONTROL_FOR. ``spec`` is the target schema."""
    return []


def _site_populations(doc: dict, spec: dict | None) -> list:
    """0.5.2 -> 0.6.0: site populations of a catalyst state and site-normalized rates. Nothing a 0.5.2 document holds is
    rewritten: no population moves onto a state (a count recorded elsewhere stays there, and none is carried from a
    sample to its states), no operando label is changed, and no DURING link is given a specimen, a timing or kinetics
    it does not state. A turnover frequency is now compared by its species, so one that names none is left out of a
    scientific comparison as missing_context, and one that does not say how it was calculated is reported (a warning);
    those change what the validator and the comparison report, not the document. What the step cannot map stops it:
    a turnover frequency whose target is not a chemical species, or one divided by a value of another kind than a site
    count or a site density (a share, a composition fraction), which would be invalid under 0.6.0; curate it by hand,
    then migrate. ``spec`` is the target schema."""
    from .quantities import misnamed_denominators, narrowed_targets
    bad = narrowed_targets(doc, spec) + misnamed_denominators(doc, spec)
    if bad:
        raise ScaleError("the step to site populations cannot map these values (curate them by hand, then migrate): "
                         f"{'; '.join(bad[:20])}" + (f" (and {len(bad) - 20} more)" if len(bad) > 20 else ""))
    return []


def _computed_energies(doc: dict, spec: dict | None) -> list:
    """0.6.0 -> 0.7.0: computed energies and kinetic parameters compared under explicit definitions. Nothing a 0.6.0
    document holds is rewritten: no method text is read into a level of theory, no energy is given a reaction it does
    not name, no charge treatment, spin or dispersion is filled in, and a reaction's balance_status stays what it says.
    An elementary step's activation and reaction energies and a degree of rate control are now bound to their kinds,
    and a Variable may name one of the new kinds; the validator checks their units and reports balances, validations on
    the data a model was fitted to and predicted values that name no producer, and a scientific comparison groups by
    kind: that changes what is reported, not the document. What the step cannot map stops it: a value whose unit is of
    another dimension than its kind's (an activation energy in volts), or whose target is not a record its kind's
    context names (an adsorption energy whose target is the adsorbate, not the reaction); curate it by hand, then
    migrate. ``spec`` is the target schema."""
    from .quantities import misread_units, narrowed_targets
    bad = misread_units(doc, spec) + narrowed_targets(doc, spec)
    if bad:
        raise ScaleError("the step to computed-energy contracts cannot map these values (curate them by hand, then "
                         f"migrate): {'; '.join(bad[:20])}" + (f" (and {len(bad) - 20} more)" if len(bad) > 20 else ""))
    return []


STEP_RULES: dict[str, tuple[str, Callable[[dict, dict | None], list]]] = {
    "0.1.0": ("graph.schema renamed scale-graph -> scale-catal; every record, id and value kept", _rename_schema),
    "0.2.1": ("quantity contracts: a HAS_COMPONENT fraction in an amount unit moves to amount, one in a concentration unit "
              "to concentration (the value object whole, its fraction_basis dropped); a value of another dimension than its "
              "quantity stops the step; every record, id and other value kept", _quantity_contracts),
    "0.3.0": ("result entries: nothing is rewritten (no value moves into result_values; the scalar results, the results map "
              "and the per-product lists keep their meaning); a value counted for a species whose target is not a "
              "ChemicalSpecies stops the step; every record, id and value kept", _result_entries),
    "0.4.0": ("reporting applicability and connected evidence: nothing is rewritten and nothing stops the step (a test "
              "that lists no driving force has unknown applicability; no interpretation is inferred); every record, id "
              "and value kept", _reporting_applicability),
    "0.5.2": ("site populations and site-normalized rates: nothing is rewritten (no population moves onto a state, no "
              "operando label or DURING link changes); a turnover frequency whose target is no chemical species, or "
              "whose denominator is not a site count or a site density, stops the step; every record, id and value "
              "kept", _site_populations),
    "0.6.0": ("computed energies and kinetic parameters: nothing is rewritten (no method text read into a level of theory, "
              "no reaction, charge treatment or setting filled in, balance_status kept); a value whose unit is of another "
              "dimension than its kind's, or whose target is not a record its kind's context names, stops the step; every "
              "record, id and value kept", _computed_energies),
}


def route(have: str | None, to: str) -> list[tuple[str, str, str]] | None:
    """The steps (from, to, note) from version ``have`` to ``to``; None when the steps do not reach it."""
    out, seen = [], set()
    while have != to:
        if have not in STEPS or have in seen:
            return None
        seen.add(have)
        nxt, cs = STEPS[have]
        out.append((have, nxt, cs))
        have = nxt
    return out


def raise_version(doc: dict, to: str, spec: dict | None = None) -> tuple[dict, dict]:
    """Move a document step by step to version ``to``. ``spec`` is the target schema, which a step
    with a rule may need."""
    new = copy.deepcopy(doc)
    have = new["graph"].get("schema_version")
    steps = []
    while have != to:
        if have not in STEPS:
            raise ScaleError(f"no step from scale-catal {have} towards {to}")
        nxt, cs = STEPS[have]
        rule, fn = STEP_RULES.get(have, ("schema_version raised; meaning_preserving", None))
        step = {"from": have, "to": nxt, "note": cs, "rule": rule}
        if fn is not None:
            step["changes"] = fn(new, spec)
        steps.append(step)
        have = nxt
    new["graph"]["schema_version"] = to
    return new, {"steps": steps}
