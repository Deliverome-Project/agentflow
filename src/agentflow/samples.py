"""Sample-sheet metadata, explicit compensation assignments and bounded preview caches."""

import colorsys
import copy
import io
import json
from collections import OrderedDict
from pathlib import Path

import pandas as pd
from matplotlib.colors import is_color_like, to_hex

from .compensation import load_matrix
from .engine import digest, evaluate, prepare

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
    result = copy.deepcopy(recipe)
    if record.get("compensation_path"):
        result["compensation"] = load_matrix(record["compensation_path"])
    return result


class SampleSession:
    """Lazy LRU preparation and gating cache. Neither cache changes analytical counts."""

    def __init__(self, records, limit=8):
        self.records = records
        self.limit = limit
        self.prepared = OrderedDict()
        self.gated = OrderedDict()

    def get(self, record, recipe):
        recipe = sample_recipe(recipe, record)
        path = Path(record["fcs_path"])
        stat = path.stat()
        key = (
            str(path),
            stat.st_mtime_ns,
            stat.st_size,
            json.dumps([recipe["compensation"], recipe["transforms"]], sort_keys=True),
        )
        if key not in self.prepared:
            fingerprint = digest(path)
            prepared = prepare(path, recipe)
            if digest(path) != fingerprint:
                raise ValueError(f"Input changed while reading {path.name}")
            self.prepared[key] = prepared
            while len(self.prepared) > self.limit:
                self.prepared.popitem(last=False)
        self.prepared.move_to_end(key)
        prepared = self.prepared[key]
        gate_key = (key, json.dumps(recipe["gates"], sort_keys=True))
        if gate_key not in self.gated:
            self.gated[gate_key] = evaluate(prepared, recipe)
            while len(self.gated) > self.limit * 2:
                self.gated.popitem(last=False)
        self.gated.move_to_end(gate_key)
        return prepared, self.gated[gate_key]
