"""Transactional gate-editing state, independent of the desktop toolkit."""

import copy
from pathlib import Path

from .acquisition import instrument_provenance
from .engine import digest, evaluate, prepare, save_recipe, validate
from .overrides import effective_recipe
from .provenance import save_snapshot
from .workflow import add_reporter, mark_unreviewed


class EditorState:
    def __init__(self, prepared, recipe, path):
        self.prepared = prepared
        self.recipe = copy.deepcopy(recipe)
        self.initial = copy.deepcopy(recipe)
        self.path = Path(path)
        self.original_hash = digest(path) if self.path.exists() else None
        self.history, self.future = [], []
        self.saved = False
        self.sample_id = None
        self.sample_scope = False

    @property
    def dirty(self):
        return self.recipe != self.initial

    def apply(self, candidate, reprepare=False):
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
        self.future.clear()
        self.recipe = candidate
        self.saved = False
        if reprepare:
            self.prepared = prepared

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
        else:
            next(g for g in candidate["gates"] if g["name"] == name)[key] = value
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
            candidate = source[-1]
            prepared = prepare(self.prepared.sample, candidate)
            target.append(copy.deepcopy(self.recipe))
            self.recipe = source.pop()
            self.saved = False
            self.prepared = prepared

    def counts(self):
        return {name: int(mask.sum()) for name, mask in evaluate(self.prepared, self.active_recipe).items()}

    def save(self):
        current = digest(self.path) if self.path.exists() else None
        if current != self.original_hash:
            raise ValueError("Recipe changed on disk. Reopen it to avoid overwriting another edit.")
        save_recipe(self.path, self.recipe)
        self.saved = True
        self.initial = copy.deepcopy(self.recipe)
        self.original_hash = digest(self.path)
        save_snapshot(
            self.path.with_suffix(".reproducibility.yaml"),
            self.recipe,
            recipe_sha256=self.original_hash,
            inspected_sample={
                "sample_id": str(self.prepared.sample.id),
                "instrument": instrument_provenance(self.prepared.sample),
            },
        )
