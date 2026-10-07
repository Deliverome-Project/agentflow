"""Validate editable workspace additions without importing GUI code."""


def validate_workspace(recipe, seen):
    if (recipe.get("draft_gates") or any(g["kind"] == "quadrant" for g in recipe["gates"])) and recipe[
        "version"
    ] != 2:
        raise ValueError("Unfinished populations and linked quadrants require recipe version 2")
    pending = {g["name"] for g in recipe.get("pending_gates", [])}
    names = set(seen) | pending
    for gate in recipe.get("draft_gates", []):
        if (
            not gate["name"].strip()
            or gate["name"] in names
            or gate["parent"] not in seen
            or gate["kind"] not in {"rectangle", "polygon", "range"}
            or len(gate["channels"]) not in ({1, 2} if gate["kind"] == "range" else {2})
            or len(set(gate["channels"])) != len(gate["channels"])
            or not set(gate["channels"]) <= recipe["transforms"].keys()
            or "bounds" in gate
            or "vertices" in gate
        ):
            raise ValueError(
                "Unfinished populations need a unique name, existing parent and two distinct detectors"
            )
        names.add(gate["name"])
    groups = {}
    for gate in recipe["gates"]:
        if gate["kind"] == "quadrant":
            groups.setdefault(gate["quadrant_group"], []).append(gate)
    for members in groups.values():
        parents = {g["parent"] for g in members}
        channels = {tuple(g["channels"]) for g in members}
        patterns = {tuple(v is None for v in g["bounds"]) for g in members}
        x = {v for g in members for v in g["bounds"][:2] if v is not None}
        y = {v for g in members for v in g["bounds"][2:] if v is not None}
        if (
            len(members) != 4
            or len(parents) != 1
            or len(channels) != 1
            or len(patterns) != 4
            or len(x) != 1
            or len(y) != 1
        ):
            raise ValueError("Keep all four quadrants linked with common thresholds, detectors and parent")
