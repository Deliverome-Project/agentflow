"""Sample-sheet metadata, explicit compensation assignments and bounded preview caches."""

import colorsys
import io
import json
from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.colors import is_color_like, to_hex

from .compensation import load_matrix
from .engine import digest, evaluate, prepare, validate
from .overrides import effective_recipe

PALETTE = ["#922038", "#3d6b60", "#5848a8", "#c07830", "#2375a0", "#bc3c4c"]


def read_samples(path):
    path = Path(path).resolve()
    data = pd.read_csv(io.BytesIO(path.read_bytes()), dtype=str, keep_default_na=False)
    if not {"sample_id", "fcs_path"} <= set(data):
        raise ValueError("Sample CSV requires sample_id and fcs_path")
    if data.empty or data.sample_id.duplicated().any() or data.sample_id.str.strip().eq("").any():
        raise ValueError("Provide nonempty, unique sample IDs")
    if data.fcs_path.str.strip().eq("").any():
        raise ValueError("Every sample needs an FCS path")
    records = data.to_dict("records")
    colors = {}
    for record in records:
        record["group"] = record.get("group") or record.get("condition") or "All samples"
        for field in ["fcs_path", "compensation_path"]:
            if record.get(field):
                record[field] = str((path.parent / record[field]).resolve())
        group, color = record["group"], record.get("color", "")
        if color:
            if not is_color_like(color):
                raise ValueError(f"Invalid group color: {color}")
            if group in colors and colors[group] != color:
                raise ValueError(f"Conflicting colors for group {group}")
            colors[group] = color
    for group in sorted({r["group"] for r in records}):
        index = len(colors)
        colors.setdefault(
            group,
            PALETTE[index]
            if index < len(PALETTE)
            else to_hex(colorsys.hls_to_rgb((index * 0.6180339) % 1, 0.43, 0.65)),
        )
    for record in records:
        record["color"] = colors[record["group"]]
    return records


def sample_recipe(recipe, record):
    result = effective_recipe(recipe, record["sample_id"])
    if record.get("compensation_path"):
        result["compensation"] = load_matrix(record["compensation_path"])
    return result


class SampleSession:
    """Lazy LRU preparation and gating cache. Neither cache changes analytical counts."""

    def __init__(self, records, limit=8, metric_limit=4096):
        if limit < 1 or metric_limit < 1:
            raise ValueError("Cache limits must be positive")
        self.records = records
        self.limit = limit
        self.metric_limit = metric_limit
        self.prepared = OrderedDict()
        self.gated = OrderedDict()
        self.summaries = OrderedDict()

    def _context(self, record, recipe):
        recipe = sample_recipe(recipe, record)
        validate(recipe)
        path = Path(record["fcs_path"])
        stat = path.stat()
        key = (
            str(path),
            stat.st_mtime_ns,
            stat.st_ctime_ns,
            stat.st_ino,
            stat.st_size,
            record.get("input_sha256"),
            json.dumps([recipe["compensation"], recipe["transforms"]], sort_keys=True),
        )
        # Review badges, labels and display choices do not affect membership.
        gates = [
            {k: v for k, v in gate.items() if k not in {"reviewed", "label", "note"}}
            for gate in recipe["gates"]
        ]
        return recipe, path, key, (key, json.dumps(gates, sort_keys=True))

    def get(self, record, recipe):
        recipe, path, key, gate_key = self._context(record, recipe)
        if key not in self.prepared:
            fingerprint = digest(path)
            if record.get("input_sha256") and record["input_sha256"] != fingerprint:
                raise ValueError(f"{path}: content differs from sample-sheet fingerprint")
            prepared = prepare(path, recipe)
            if digest(path) != fingerprint:
                raise ValueError(f"Input changed while reading {path.name}")
            self.prepared[key] = prepared
            while len(self.prepared) > self.limit:
                self.prepared.popitem(last=False)
        self.prepared.move_to_end(key)
        prepared = self.prepared[key]
        if gate_key not in self.gated:
            self.gated[gate_key] = evaluate(prepared, recipe)
            while len(self.gated) > self.limit * 2:
                self.gated.popitem(last=False)
        self.gated.move_to_end(gate_key)
        return prepared, self.gated[gate_key]

    def metrics(self, record, recipe, population, detector=None):
        """Cache exact small summaries independently of the bounded event cache.

        A plate can exceed the event cache without re-reading all FCS files on
        every redraw. File replacement, compensation, transforms and effective
        sample gates invalidate entries. No event subsampling is used.
        """
        effective, _, _, gate_key = self._context(record, recipe)
        gates = {g["name"]: g for g in effective["gates"]}

        def metric_key(name):
            dependencies = set()
            pending = [name]
            while pending:
                current = pending.pop()
                if current == "root" or current in dependencies:
                    continue
                dependencies.add(current)
                gate = gates[current]
                pending.extend([gate["parent"], *gate.get("references", [])])
            geometry = [g for g in json.loads(gate_key[1]) if g["name"] in dependencies]
            return (gate_key[0], json.dumps(geometry, sort_keys=True), name, detector)

        if population != "root" and population not in gates:
            raise ValueError(f"{record['sample_id']}: population or detector unavailable")
        key = metric_key(population)
        if key not in self.summaries:
            prepared, masks = self.get(record, recipe)
            if detector is not None and detector not in prepared.values:
                raise ValueError(f"{record['sample_id']}: population or detector unavailable")
            counts = {name: int(mask.sum()) for name, mask in masks.items()}
            # Capture all populations while these events are resident. Changing
            # the selected population then needs no second plate-wide FCS scan.
            for name in [n for n in masks if n != population] + [population]:
                parent = gates[name]["parent"] if name != "root" else "root"
                result = {
                    "event_count": counts[name],
                    "parent_count": counts[parent],
                    "signal_space": "compensated" if prepared.matrix is not None else "raw",
                }
                if detector is not None:
                    values = prepared.values.loc[masks[name], detector].to_numpy()
                    finite = values[np.isfinite(values)]
                    result.update(
                        finite_event_count=len(finite),
                        mean=float(np.mean(finite)) if len(finite) else np.nan,
                        median=float(np.median(finite)) if len(finite) else np.nan,
                    )
                self.summaries[metric_key(name)] = result
                while len(self.summaries) > self.metric_limit:
                    self.summaries.popitem(last=False)
        self.summaries.move_to_end(key)
        return self.summaries[key].copy()
