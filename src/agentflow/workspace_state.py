"""Headless workspace transactions: unfinished drawings, linked quadrants and recovery."""

import copy
import json
import tempfile
from pathlib import Path

from .recipes import digest, load_recipe, save_recipe


def atomic_json(path, value):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, allow_nan=False, indent=2)
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


class WorkspaceState:
    def draft(self, name):
        return next((g for g in self.recipe.get("draft_gates", []) if g["name"] == name), None)

    def add_draft(self, name, parent, channels, kind="rectangle"):
        if self.sample_scope:
            raise ValueError("Population structure is shared. Select All samples to create a population.")
        candidate = copy.deepcopy(self.recipe)
        candidate["version"] = 2
        candidate.setdefault("draft_gates", []).append(
            {"name": name.strip(), "parent": parent, "channels": channels, "kind": kind}
        )
        self.apply(candidate, label="create unfinished population")

    def draft_type(self, name, kind, channels=None):
        if self.sample_scope:
            raise ValueError("Gate types are shared. Select All samples.")
        candidate = copy.deepcopy(self.recipe)
        draft = next(g for g in candidate["draft_gates"] if g["name"] == name)
        draft["kind"] = kind
        if channels is not None:
            draft["channels"] = channels
        self.apply(candidate, label="choose drawing tool")

    def complete_draft(self, name, geometry):
        candidate = copy.deepcopy(self.recipe)
        draft = next(g for g in candidate["draft_gates"] if g["name"] == name)
        candidate["draft_gates"].remove(draft)
        gate = dict(draft, **geometry, reviewed=False)
        if gate["kind"] == "range":
            gate["channels"] = gate["channels"][:1]
        candidate["gates"].append(gate)
        self.apply(candidate, label="draw gate")

    def quadrants(self, prefix, parent, channels, x, y):
        """Four linked native rectangles; FlowKit owns half-open boundary membership."""
        if self.sample_scope:
            raise ValueError("Select All samples to create linked quadrants.")
        if not prefix.strip():
            raise ValueError("Give the quadrant populations a name.")
        candidate = copy.deepcopy(self.recipe)
        candidate["version"] = 2
        for suffix, bounds in zip(
            ("--", "+-", "-+", "++"),
            ([None, x, None, y], [x, None, None, y], [None, x, y, None], [x, None, y, None]),
        ):
            candidate["gates"].append(
                {
                    "name": prefix.strip() + " " + suffix,
                    "parent": parent,
                    "channels": channels,
                    "kind": "quadrant",
                    "bounds": bounds,
                    "quadrant_group": prefix.strip(),
                    "reviewed": False,
                }
            )
        self.apply(candidate, label="create four quadrants")

    def move_quadrants(self, name, x, y):
        gate = self.gate(name)
        candidate = copy.deepcopy(self.recipe)
        for member in candidate["gates"]:
            if member.get("quadrant_group") != gate["quadrant_group"]:
                continue
            bounds = [None if v is None else (x if i < 2 else y) for i, v in enumerate(member["bounds"])]
            if self.sample_scope and self.sample_id:
                changes = candidate.setdefault("sample_overrides", {}).setdefault(self.sample_id, {})
                changes.setdefault(member["name"], {})["bounds"] = bounds
                from .workflow import mark_unreviewed

                affected = mark_unreviewed(self.active_recipe, member["name"])
                for affected_name in affected:
                    changes.setdefault(affected_name, {})["reviewed"] = False
            else:
                member["bounds"] = bounds
                self.invalidate(candidate, member["name"])
        self.apply(candidate, label="move quadrant thresholds")

    @property
    def recovery_path(self):
        return self.path.with_name(self.path.name + ".recovery.json")

    def write_recovery(self):
        if self.recovery_pending:
            return
        if not self.dirty:
            self.recovery_path.unlink(missing_ok=True)
            return
        atomic_json(
            self.recovery_path,
            {
                "source": str(self.path.resolve()),
                "source_sha256": self.original_hash,
                "recipe": self.recipe,
            },
        )

    def recover(self):
        data = json.loads(self.recovery_path.read_text())
        current = digest(self.path) if self.path.exists() else None
        if data["source"] != str(self.path.resolve()) or data["source_sha256"] != current:
            raise ValueError("Recovery belongs to a different saved revision. Keep it for manual comparison.")
        pending = self.recovery_pending
        self.recovery_pending = False
        try:
            self.apply(data["recipe"], reprepare=True, label="recover unsaved changes")
        except Exception:
            self.recovery_pending = pending
            raise

    @property
    def checkpoint_dir(self):
        return self.path.with_name(self.path.name + ".checkpoints")

    def checkpoint(self, name):
        import re

        if not re.fullmatch(r"[\w][\w .-]{0,79}", name) or name.endswith((".", " ")):
            raise ValueError("Use 1–80 letters, numbers, spaces, dots or hyphens for a checkpoint name.")
        self.checkpoint_dir.mkdir(exist_ok=True)
        path = self.checkpoint_dir / (name + ".json")
        if path.exists():
            raise ValueError("That checkpoint already exists. Choose a new name.")
        save_recipe(path, self.recipe)
        return path

    def restore_checkpoint(self, name):
        # Only a name from the directory listing is accepted, never a relative path.
        choices = {p.stem: p for p in self.checkpoint_dir.glob("*.json")}
        if name not in choices:
            raise ValueError("Checkpoint not found.")
        self.apply(load_recipe(choices[name]), reprepare=True, label="restore checkpoint")
