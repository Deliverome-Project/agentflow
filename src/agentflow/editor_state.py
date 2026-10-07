"""Transactional gate-editing state, independent of the desktop toolkit."""

import copy
from pathlib import Path

from .acquisition import instrument_provenance
from .engine import digest, evaluate, prepare, save_recipe, validate
from .overrides import effective_recipe
from .provenance import save_snapshot
from .workflow import add_reporter, mark_unreviewed
from .workspace_state import WorkspaceState


class EditorState(WorkspaceState):
    def __init__(self, prepared, recipe, path):
        self.prepared = prepared
        self.recipe = copy.deepcopy(recipe)
        self.initial = copy.deepcopy(recipe)
        self.path = Path(path)
        self.original_hash = digest(path) if self.path.exists() else None
        self.history, self.future = [], []
        self.history_labels, self.future_labels = [], []
        self.recovery_error = None
        self.recovery_pending = self.recovery_path.exists()
        self.saved = False
        self.sample_id = None
        self.sample_scope = False
        self._mask_cache = None

    @property
    def dirty(self):
        return self.recipe != self.initial

    def apply(self, candidate, reprepare=False, label="gate edit"):
        validate(candidate)
        if candidate == self.recipe:
            return
        if reprepare:
            try:
                prepared = prepare(self.prepared.sample, candidate)
            except Exception:
                self.prepared = prepare(self.prepared.sample, self.recipe)
                raise
        self.history.append(copy.deepcopy(self.recipe))
        self.history_labels.append(label)
        self.future_labels.clear()
        self.future.clear()
        self.recipe = candidate
        self.saved = False
        if reprepare:
            self.prepared = prepared
        try:
            self.write_recovery()
            self.recovery_error = None
        except OSError as error:
            self.recovery_error = str(error)

    @property
    def active_recipe(self):
        return effective_recipe(self.recipe, self.sample_id)

    def gate(self, name):
        return next((g for g in self.active_recipe["gates"] if g["name"] == name), None)

    def invalidate(self, candidate, name=None):
        affected = mark_unreviewed(candidate, name)
        for changes in candidate.get("sample_overrides", {}).values():
            for gate_name in affected:
                if gate_name in changes:
                    changes[gate_name]["reviewed"] = False

    def reset_override(self, name):
        candidate = copy.deepcopy(self.recipe)
        changes = candidate.get("sample_overrides", {}).get(self.sample_id, {})
        if name not in changes:
            return
        changes.pop(name)
        effective = effective_recipe(candidate, self.sample_id)
        affected = mark_unreviewed(effective, name)
        for gate_name in affected:
            changes.setdefault(gate_name, {})["reviewed"] = False
        self.apply(candidate)

    def geometry(self, name, key, value):
        candidate = copy.deepcopy(self.recipe)
        exception = self.recipe.get("sample_overrides", {}).get(self.sample_id, {}).get(name, {})
        if not self.sample_scope and key in exception and self.gate(name)[key] != value:
            raise ValueError(
                "This gate has a sample exception. Choose This sample only, or reset its exception."
            )
        if self.gate(name)[key] == value:
            return
        if self.sample_scope and self.sample_id:
            effective = self.active_recipe
            next(g for g in effective["gates"] if g["name"] == name)[key] = value
            affected = mark_unreviewed(effective, name)
            changes = candidate.setdefault("sample_overrides", {}).setdefault(self.sample_id, {})
            changes.setdefault(name, {})[key] = value
            for gate_name in affected:
                changes.setdefault(gate_name, {})["reviewed"] = False
            changes[name]["reviewed"] = True
        else:
            next(g for g in candidate["gates"] if g["name"] == name)[key] = value
            self.invalidate(candidate, name)
            next(g for g in candidate["gates"] if g["name"] == name)["reviewed"] = True
        label = "reshape gate"
        if key == "vertices":
            old_size = len(self.gate(name)[key])
            label = "added point" if len(value) > old_size else "removed point" if len(value) < old_size else label
        self.apply(candidate, label=label)

    def change_gate_type(self, name, kind, y_channel=None, y_bounds=None, x_bounds=None):
        """Convert saved geometry, retaining identifiers, dependents and sample exceptions.

        Polygon to rectangle uses its bounding box; projecting onto X removes the
        Y restriction. Open ranges require explicit finite X/Y limits to become 2D.
        All conversions require review, including rectangle/polygon boundary cases.
        """
        if self.sample_scope:
            raise ValueError("Gate types are shared. Select All samples to change gate type.")
        gate = self.gate(name)
        supported = {"rectangle", "polygon", "range"}
        if gate is None or gate["kind"] not in supported or kind not in supported:
            raise ValueError("Only rectangle, polygon and range gates can change type here.")
        old_kind = gate["kind"]
        if old_kind == kind:
            return
        if old_kind == "range" and (
            not y_channel or y_channel == gate["channels"][0] or y_bounds is None
        ):
            raise ValueError("Choose a second detector and finite Y bounds for a two-dimensional gate.")

        def convert(geometry):
            if old_kind == "polygon":
                xs, ys = zip(*geometry["vertices"])
                bounds = [min(xs), max(xs), min(ys), max(ys)]
            else:
                bounds = list(geometry["bounds"])
            if old_kind == "range":
                bounds = [
                    value if value is not None else (x_bounds or [None, None])[i]
                    for i, value in enumerate(bounds)
                ] + list(y_bounds)
            if kind == "polygon":
                a, b, c, d = bounds
                return {"vertices": [[a, c], [b, c], [b, d], [a, d]]}
            return {"bounds": bounds[:2] if kind == "range" else bounds}

        candidate = copy.deepcopy(self.recipe)
        shared = next(g for g in candidate["gates"] if g["name"] == name)
        old_key = "vertices" if old_kind == "polygon" else "bounds"
        converted = convert(shared)
        shared.pop(old_key)
        shared.update(converted)
        shared["kind"] = kind
        if kind == "range":
            shared["channels"] = shared["channels"][:1]
        elif old_kind == "range":
            shared["channels"].append(y_channel)
        for changes in candidate.get("sample_overrides", {}).values():
            change = changes.get(name, {})
            if old_key in change:
                converted = convert(change)
                change.pop(old_key)
                change.update(converted)
        self.invalidate(candidate, name)
        self.apply(candidate)

    def review(self, name):
        candidate = copy.deepcopy(self.recipe)
        if self.sample_scope and self.sample_id:
            candidate.setdefault("sample_overrides", {}).setdefault(self.sample_id, {}).setdefault(name, {})[
                "reviewed"
            ] = True
        else:
            if name in candidate.get("sample_overrides", {}).get(self.sample_id, {}):
                raise ValueError("Choose This sample only to review this sample exception.")
            next(g for g in candidate["gates"] if g["name"] == name)["reviewed"] = True
        self.apply(candidate)

    def rename_population(self, name, new_name):
        """Rename a shared identifier without changing membership or review status."""
        if self.sample_scope:
            raise ValueError("Population names are shared. Select All samples to rename a population.")
        new_name = new_name.strip()
        if self.gate(name) is None and self.draft(name) is None:
            raise ValueError("Select an existing population to rename.")
        if new_name == name:
            return
        reserved = {"root"} | {g["name"] for g in self.recipe["gates"] + self.recipe.get("pending_gates", []) + self.recipe.get("draft_gates", [])}
        if not new_name or new_name in reserved or any(ord(c) < 32 for c in new_name):
            raise ValueError("Choose a nonempty, unique population name (not root or a pending population).")
        candidate = copy.deepcopy(self.recipe)
        for gate in candidate["gates"]:
            if gate["name"] == name:
                gate["name"] = new_name
                gate["label"] = new_name
            if gate["parent"] == name:
                gate["parent"] = new_name
            if "references" in gate:
                gate["references"] = [new_name if ref == name else ref for ref in gate["references"]]
        for draft in candidate.get("draft_gates", []):
            if draft["name"] == name:
                draft["name"] = new_name
            if draft["parent"] == name:
                draft["parent"] = new_name
        for changes in candidate.get("sample_overrides", {}).values():
            if name in changes:
                changes[new_name] = changes.pop(name)
        roles = candidate.get("channel_roles", {})
        if name in roles:
            roles[new_name] = roles.pop(name)
        display = candidate.get("display", {})
        if display.get("summary_population") == name:
            display["summary_population"] = new_name
        self.apply(candidate)

    def deletion_set(self, name):
        """Include descendants and Boolean dependents in recipe order."""
        if self.sample_scope:
            raise ValueError("Population structure is shared. Select All samples to delete a population.")
        if not any(g["name"] == name for g in self.recipe["gates"]):
            raise ValueError("Select an existing population to delete.")
        selected = self.gate(name)
        affected = {g["name"] for g in self.recipe["gates"]
                    if selected.get("quadrant_group") and g.get("quadrant_group") == selected["quadrant_group"]} or {name}
        for gate in self.recipe["gates"]:
            if gate["parent"] in affected or affected.intersection(gate.get("references", [])):
                affected.add(gate["name"])
        if len(affected) == len(self.recipe["gates"]):
            raise ValueError("Keep at least one population in the editor; delete a subpopulation instead.")
        return ([g["name"] for g in self.recipe["gates"] if g["name"] in affected]
                + [g["name"] for g in self.recipe.get("draft_gates", []) if g["parent"] in affected])

    def delete_population(self, name):
        if self.draft(name):
            if self.sample_scope:
                raise ValueError("Select All samples to delete a population.")
            candidate = copy.deepcopy(self.recipe)
            candidate["draft_gates"] = [g for g in candidate["draft_gates"] if g["name"] != name]
            self.apply(candidate, label="delete unfinished population")
            return
        affected = set(self.deletion_set(name))
        candidate = copy.deepcopy(self.recipe)
        candidate["gates"] = [g for g in candidate["gates"] if g["name"] not in affected]
        candidate["draft_gates"] = [g for g in candidate.get("draft_gates", []) if g["parent"] not in affected]
        for changes in candidate.get("sample_overrides", {}).values():
            for removed in affected:
                changes.pop(removed, None)
        self.apply(candidate)

    def assign(self, name, channel):
        self.apply(add_reporter(self.recipe, self.prepared.sample, name, channel, confirmed=True), True)

    def compensate(self, spec):
        candidate = copy.deepcopy(self.recipe)
        candidate["compensation"] = spec
        self.invalidate(candidate)
        self.apply(candidate, True)

    def travel(self, redo=False):
        source, target = (self.future, self.history) if redo else (self.history, self.future)
        if source:
            labels, target_labels = (self.future_labels, self.history_labels) if redo else (self.history_labels, self.future_labels)
            candidate = source[-1]
            prepared = prepare(self.prepared.sample, candidate)
            target_labels.append(labels.pop())
            target.append(copy.deepcopy(self.recipe))
            self.recipe = source.pop()
            self.saved = False
            self.prepared = prepared
            self.write_recovery()

    def masks(self):
        recipe = self.active_recipe
        cached = self._mask_cache
        if cached is None or cached[0] is not self.prepared or cached[1] != recipe:
            self._mask_cache = (self.prepared, copy.deepcopy(recipe), evaluate(self.prepared, recipe, allow_unfinished=True))
        return self._mask_cache[2]

    def counts(self):
        return {name: int(mask.sum()) for name, mask in self.masks().items()}

    def save(self):
        if self.recovery_pending:
            raise ValueError("Recover or discard the previous unsaved recovery copy before saving.")
        current = digest(self.path) if self.path.exists() else None
        if current != self.original_hash:
            raise ValueError("Recipe changed on disk. Reopen it to avoid overwriting another edit.")
        save_recipe(self.path, self.recipe)
        self.saved = True
        self.initial = copy.deepcopy(self.recipe)
        self.original_hash = digest(self.path)
        self.recovery_path.unlink(missing_ok=True)
        save_snapshot(
            self.path.with_suffix(".reproducibility.yaml"),
            self.recipe,
            recipe_sha256=self.original_hash,
            inspected_sample={
                "sample_id": str(self.prepared.sample.id),
                "instrument": instrument_provenance(self.prepared.sample),
            },
        )
