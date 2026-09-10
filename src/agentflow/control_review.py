"""Atomic, reproducible compensation review bundles shared by desktop and Python."""

import copy
import json
import shutil
import tempfile
from pathlib import Path

from .compensation import control_diagnostics, estimate_controls, matrix_diagnostic, save_matrix


def resolve_config(config, base):
    config = copy.deepcopy(config)
    for control in config["controls"]:
        control["fcs_path"] = str((Path(base) / control["fcs_path"]).resolve())
    if config.get("cleanup_recipe"):
        config["cleanup_recipe"] = str((Path(base) / config["cleanup_recipe"]).resolve())
    return config


def export_control_review(config, output):
    """Publish config, draft matrix, evidence and diagnostic plots together, or nothing."""
    output = Path(output).resolve()
    if output.exists():
        raise ValueError("Choose a new compensation review directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".compensation-", dir=output.parent))
    try:
        path = stage / "controls.json"
        path.write_text(json.dumps(config, indent=2, allow_nan=False) + "\n")
        spec = estimate_controls(path)
        save_matrix(spec, stage / "compensation.json")
        matrix_diagnostic(spec, stage / "matrix.png")
        control_diagnostics(path, spec, stage / "diagnostics")
        stage.rename(output)
        return spec
    finally:
        if stage.exists():
            shutil.rmtree(stage)
