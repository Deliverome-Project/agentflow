"""Explicit sample-specific geometry; shared hierarchy and signal space remain canonical."""

import copy


def effective_recipe(recipe, sample_id=None):
    result = copy.deepcopy(recipe)
    overrides = result.pop("sample_overrides", {})
    for gate in result["gates"]:
        gate.update(copy.deepcopy(overrides.get(sample_id, {}).get(gate["name"], {})))
    return result


def validate_overrides(recipe):
    from .recipes import validate

    overrides = recipe.get("sample_overrides", {})
    if not isinstance(overrides, dict):
        raise TypeError("sample_overrides must map sample IDs to gate overrides")
    gates = {g["name"]: g for g in recipe["gates"]}
    for sample_id, changes in overrides.items():
        if not isinstance(sample_id, str) or not sample_id.strip() or not isinstance(changes, dict):
            raise ValueError("Overrides require a nonempty sample ID and gate mapping")
        for name, change in changes.items():
            if name not in gates or not isinstance(change, dict):
                raise ValueError("Override names must identify existing gates")
            key = "vertices" if gates[name]["kind"] == "polygon" else "bounds"
            allowed = {"reviewed"} if gates[name]["kind"] == "boolean" else {key, "reviewed"}
            if not change or not set(change) <= allowed:
                raise ValueError("Overrides may change only geometry and review status")
            if "reviewed" in change and not isinstance(change["reviewed"], bool):
                raise ValueError("Override reviewed must be boolean")
        validate(effective_recipe(recipe, sample_id))
