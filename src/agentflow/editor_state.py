"""Transactional gate-editing state, independent of the desktop toolkit."""

import copy
from pathlib import Path

from .engine import digest, evaluate, prepare, save_recipe, validate
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
        if reprepare:
            self.prepared = prepared

    def gate(self, name):
        return next((g for g in self.recipe["gates"] if g["name"] == name), None)

    def geometry(self, name, key, value):
        candidate = copy.deepcopy(self.recipe)
        gate = next(g for g in candidate["gates"] if g["name"] == name)
        if gate[key] == value:
            return
        gate[key] = value
        mark_unreviewed(candidate, name)
        self.apply(candidate)

    def review(self, name):
        candidate = copy.deepcopy(self.recipe)
        next(g for g in candidate["gates"] if g["name"] == name)["reviewed"] = True
        self.apply(candidate)

    def assign(self, name, channel):
        self.apply(add_reporter(self.recipe, self.prepared.sample, name, channel, confirmed=True), True)

    def compensate(self, spec):
        candidate = copy.deepcopy(self.recipe)
        candidate["compensation"] = spec
        mark_unreviewed(candidate)
        self.apply(candidate, True)

    def travel(self, redo=False):
        source, target = (self.future, self.history) if redo else (self.history, self.future)
        if source:
            candidate = source[-1]
            prepared = prepare(self.prepared.sample, candidate)
            target.append(copy.deepcopy(self.recipe))
            self.recipe = source.pop()
            self.prepared = prepared

    def counts(self):
        return {name: int(mask.sum()) for name, mask in evaluate(self.prepared, self.recipe).items()}

    def save(self):
        current = digest(self.path) if self.path.exists() else None
        if current != self.original_hash:
            raise ValueError("Recipe changed on disk. Reopen it to avoid overwriting another edit.")
        save_recipe(self.path, self.recipe)
        self.saved = True
        self.initial = copy.deepcopy(self.recipe)
        self.original_hash = digest(self.path)
